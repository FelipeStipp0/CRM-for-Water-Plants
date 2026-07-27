"""
Sincronização do padrón RUC do DNIT (store nacional, compartilhado entre orgs).

O DNIT publica o listado completo em 10 zips (`ruc0.zip`…`ruc9.zip`), atualizados
todo mês. A URL do portal traz um UUID por versão, mas o caminho SEM o UUID serve
o mesmo arquivo (mesmo Content-Length/Last-Modified) — é o que permite automatizar.

Três cuidados que o import manual não tinha:

1. **Troca atômica.** Importar por cima da coleção viva deixaria uma janela em que
   `ruc_lookup` devolve `found=False` para todo mundo — e nessa janela toda factura
   sairia como "no contribuyente", com CI em vez de RUC. Silencioso e errado. Por
   isso carregamos numa coleção temporária e trocamos com `renameCollection` no fim.
2. **Parsing pelas pontas.** ~12 linhas do padrón têm `|` dentro do nome (`M|LLER`).
   Cortar por posição fixa pega o campo errado como estado, e um contribuyente ativo
   viraria "no contribuyente" para sempre. Ancoramos nas extremidades.
3. **Só baixa se mudou.** `Last-Modified` de cada zip é comparado com o da última
   sincronização; sem publicação nova, o job sai em ~10 requisições HEAD.
"""

import gzip  # noqa: F401  (mantém o módulo disponível p/ chamadas externas)
import io
import logging
import zipfile
from datetime import datetime
from typing import Iterator, Optional

import httpx

from app.database import get_ruc_db

logger = logging.getLogger(__name__)

BASE_URL = "https://www.dnit.gov.py/documents/20123/3434104"
ARQUIVOS = [f"ruc{i}.zip" for i in range(10)]

COLLECTION = "ruc_registry"
TMP_COLLECTION = "ruc_registry_tmp"
META_COLLECTION = "ruc_registry_meta"

BATCH = 50_000
TIMEOUT = httpx.Timeout(120.0, connect=30.0)


# --------------------------------------------------------------- parsing (puro)
def parse_linha(linha: str) -> Optional[dict]:
    """
    `RUC|NOMBRE|DV|EQUIVALENCIA|ESTADO|` → dict, ou None se inservível.

    Ancorado nas PONTAS porque o nome pode conter `|`: o estado é o último campo
    não vazio, e o nome é tudo que sobra entre o RUC e o DV.
    """
    partes = linha.rstrip("\n").rstrip("\r").split("|")
    while partes and not partes[-1].strip():
        partes.pop()                      # descarta o pipe final (e vazios)
    if len(partes) < 5:
        return None

    ruc = partes[0].strip()
    if not ruc.isdigit():
        return None

    estado = partes[-1].strip().upper()   # ESTADO
    dv = partes[-3].strip()               # DV (antes da EQUIVALENCIA)
    nombre = "|".join(partes[1:-3]).strip()   # reconstitui pipes internos
    return {"ruc": ruc, "nombre": nombre, "dv": dv, "estado": estado}


def linhas_do_zip(conteudo: bytes) -> Iterator[str]:
    """Cada zip carrega um único `rucN.txt` em UTF-8."""
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        for nome in z.namelist():
            if not nome.lower().endswith(".txt"):
                continue
            with z.open(nome) as fh:
                for bruta in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                    yield bruta


# --------------------------------------------------------------- rede
async def _last_modified() -> dict[str, str]:
    """HEAD em cada zip → {arquivo: Last-Modified}. Barato: não baixa nada."""
    marcas: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        for nome in ARQUIVOS:
            try:
                r = await cli.head(f"{BASE_URL}/{nome}")
                marcas[nome] = r.headers.get("last-modified", "")
            except Exception as e:  # noqa: BLE001
                logger.warning("[ruc] HEAD falhou em %s: %s", nome, e)
                marcas[nome] = ""
    return marcas


async def _versao_anterior() -> dict:
    doc = await get_ruc_db()[META_COLLECTION].find_one({"_id": "ultima"})
    return doc or {}


# --------------------------------------------------------------- sincronização
async def sincronizar(forcar: bool = False) -> dict:
    """
    Baixa o padrón, carrega em coleção temporária e troca atomicamente.

    Devolve um resumo. Não levanta em falha de rede parcial: se algum zip não vier,
    ABORTA a troca — meio padrón é pior que o padrón do mês passado.
    """
    inicio = datetime.utcnow()
    marcas = await _last_modified()
    anterior = await _versao_anterior()

    if not forcar and marcas and marcas == anterior.get("last_modified"):
        logger.info("[ruc] padrón inalterado — nada a fazer")
        return {"status": "sem_mudanca", "verificado_em": inicio,
                "total": anterior.get("total", 0)}

    db = get_ruc_db()
    tmp = db[TMP_COLLECTION]
    await tmp.drop()

    total = malformados = 0
    buffer: list[dict] = []

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        for nome in ARQUIVOS:
            try:
                resp = await cli.get(f"{BASE_URL}/{nome}")
                resp.raise_for_status()
            except Exception as e:  # noqa: BLE001
                await tmp.drop()
                logger.error("[ruc] download falhou em %s: %s — troca abortada", nome, e)
                return {"status": "erro", "arquivo": nome, "error": str(e)}

            for linha in linhas_do_zip(resp.content):
                reg = parse_linha(linha)
                if reg is None:
                    malformados += 1
                    continue
                buffer.append(reg)
                total += 1
                if len(buffer) >= BATCH:
                    await tmp.insert_many(buffer, ordered=False)
                    buffer = []
            logger.info("[ruc] %s processado — acumulado %s", nome, f"{total:,}")

    if buffer:
        await tmp.insert_many(buffer, ordered=False)

    # Um padrón muito menor que o anterior é sinal de publicação truncada.
    esperado = anterior.get("total", 0)
    if esperado and total < esperado * 0.9:
        await tmp.drop()
        logger.error("[ruc] padrón suspeito (%s vs %s antes) — troca abortada",
                     f"{total:,}", f"{esperado:,}")
        return {"status": "suspeito", "total": total, "anterior": esperado}

    await tmp.create_index("ruc", unique=True)
    # Troca: a coleção viva só some no instante do rename.
    await db[TMP_COLLECTION].rename(COLLECTION, dropTarget=True)

    await db[META_COLLECTION].update_one(
        {"_id": "ultima"},
        {"$set": {"last_modified": marcas, "total": total,
                  "malformados": malformados, "sincronizado_em": datetime.utcnow(),
                  "duracao_s": (datetime.utcnow() - inicio).total_seconds()}},
        upsert=True,
    )
    logger.info("[ruc] padrón atualizado: %s registros (%s malformados)",
                f"{total:,}", malformados)
    return {"status": "ok", "total": total, "malformados": malformados}


async def status() -> dict:
    """Estado da última sincronização (para o painel / diagnóstico)."""
    meta = await _versao_anterior()
    vivos = await get_ruc_db()[COLLECTION].estimated_document_count()
    return {
        "registros": vivos,
        "total_ultima_sync": meta.get("total"),
        "sincronizado_em": meta.get("sincronizado_em"),
        "malformados": meta.get("malformados"),
    }
