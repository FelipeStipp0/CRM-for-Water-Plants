"""
Reset TOTAL de um ambiente: dropa `wmapp_admin` + todos os `wmapp_{slug}`.

DESTRUTIVO E IRREVERSÍVEL. Existe porque o wipe manual é pior: dropar só o
`wmapp_admin` deixa os bancos de org órfãos (as connection strings cifradas que
os endereçavam vão junto), e ninguém lembra de todos os slugs na hora.

Uso (a partir de `backend/`):

    # 1. ver o que cairia — não apaga nada
    MONGODB_URL="mongodb://..." python -m scripts.wipe_prod

    # 2. backup de todas as orgs para o R2 antes (recomendado)
    MONGODB_URL="mongodb://..." python -m scripts.wipe_prod --backup

    # 3. apagar de verdade (pede confirmação digitada)
    MONGODB_URL="mongodb://..." python -m scripts.wipe_prod --backup --apply

A URL vem do ambiente de propósito — credencial de produção não entra no código
nem no histórico do shell se você usar um arquivo de env.

Depois do wipe não sobra org nenhuma: recriar pelo admin-panel (que gera a
connection string nova) e então semear o primeiro usuário.
"""

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

ADMIN_DB = "wmapp_admin"
ORG_PREFIX = "wmapp_"

# O padron RUC (~2 milhoes de registros publicos do DNIT) vive em `wmapp_ruc`
# justamente para sobreviver a um reset: e dado nacional, igual para todas as
# orgs, e reimportar custa caro. Preservado mesmo no wipe "total".
PRESERVAR = {"wmapp_ruc"}


def _host_visivel(url: str) -> str:
    """Host da URL sem a credencial — para exibir e para confirmar o alvo."""
    sem_cred = re.sub(r"://[^@/]*@", "://", url)
    m = re.match(r"[a-z+]+://([^/?]+)", sem_cred)
    return m.group(1) if m else "(desconhecido)"


async def _listar(client) -> tuple[list[str], list[str]]:
    nomes = await client.list_database_names()
    orgs = sorted(n for n in nomes
                  if n.startswith(ORG_PREFIX) and n != ADMIN_DB and n not in PRESERVAR)
    admin = [ADMIN_DB] if ADMIN_DB in nomes else []
    return admin, orgs


async def _inventario(client, dbs: list[str]) -> None:
    """Mostra tamanho de cada banco: é a última chance de notar algo inesperado."""
    for nome in dbs:
        db = client[nome]
        try:
            st = await db.command("dbStats")
            cols = await db.list_collection_names()
            docs = st.get("objects", 0)
            mb = st.get("dataSize", 0) / 1048576
            print(f"    {nome:<28} {len(cols):>3} colls  {docs:>8} docs  {mb:>8.2f} MB")
        except Exception as e:  # noqa: BLE001
            print(f"    {nome:<28} (nao foi possivel inspecionar: {e})")


async def _main(args) -> int:
    # MONGO_PUBLIC_URL vem do serviço MongoDB do Railway (proxy TCP, roteável de
    # fora). O MONGODB_URL do serviço da app aponta para a rede PRIVADA
    # (`*.railway.internal`), que só resolve de dentro — inútil rodando daqui.
    url = (os.environ.get("MONGODB_URL")
           or os.environ.get("MONGO_PUBLIC_URL", "")).strip()
    if not url:
        print("ERRO: defina MONGODB_URL (ou MONGO_PUBLIC_URL) no ambiente.")
        return 1

    # O backup precisa das credenciais do R2, que vivem no serviço da app — mas
    # o MONGODB_URL de lá aponta para a rede privada. `--public-host` troca só o
    # host pelo proxy TCP publico, preservando a credencial dentro do processo.
    if args.public_host:
        url = re.sub(r"(://(?:[^@/]*@)?)[^/?]+", r"\g<1>" + args.public_host, url, count=1)

    host = _host_visivel(url)
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=15000)
    await client.admin.command("ping")

    admin, orgs = await _listar(client)
    alvo = admin + orgs

    print(f"\nAlvo: {host}")
    if not alvo:
        print("Nenhum banco 'wmapp_*' encontrado - nada a fazer.")
        return 0
    print(f"Bancos que seriam APAGADOS ({len(alvo)}):")
    await _inventario(client, alvo)

    preservados = [n for n in await client.list_database_names() if n in PRESERVAR]
    if preservados:
        print("\nPRESERVADOS (nao serao tocados):")
        await _inventario(client, preservados)
    if orgs and not admin:
        print("\n  AVISO: ha bancos de org mas nao ha wmapp_admin - ja estao orfaos.")

    if args.backup:
        print("\n--- backup das orgs para o R2 ---")
        # O backup abre conexao propria via app.config: precisa enxergar a MESMA
        # url ja corrigida, senao volta para a rede privada e nao resolve.
        os.environ["MONGODB_URL"] = url
        from app import database as _db                      # noqa: PLC0415
        from app.database import init_db, close_db           # noqa: PLC0415
        from app.services.backup import backup_all_orgs      # noqa: PLC0415

        # Cada org tem connection string PROPRIA, cifrada no registro — e ela
        # tambem aponta para a rede privada. Rodando de fora, o host dela
        # precisa do mesmo swap, senao so o wmapp_admin fica alcancavel.
        if args.public_host:
            _orig = _db._get_org_connection_string

            async def _publica(slug: str, _o=_orig):
                return re.sub(r"(://(?:[^@/]*@)?)[^/?]+",
                              r"\g<1>" + args.public_host, await _o(slug), count=1)

            _db._get_org_connection_string = _publica

        await init_db()
        try:
            resultados = await backup_all_orgs()
            if not resultados:
                print("  (nenhuma org registrada em wmapp_admin - nada foi salvo)")
            for r in resultados:
                print(f"  {r}")
        finally:
            await close_db()

    if not args.apply:
        print("\nDry-run: nada foi apagado. Rode de novo com --apply para executar.")
        return 0

    print(f"\n*** Isto APAGA {len(alvo)} banco(s) em {host}. NAO HA DESFAZER. ***")
    print("    Depois disso nao existe org nenhuma: recriar pelo admin-panel.")
    if input(f"Digite o host '{host}' para confirmar: ").strip() != host:
        print("Cancelado.")
        return 1

    for nome in alvo:
        await client.drop_database(nome)
        print(f"  dropado: {nome}")

    restantes = [n for n in await client.list_database_names() if n.startswith(ORG_PREFIX)]
    print(f"\nConcluido. Bancos 'wmapp_*' restantes: {restantes or 'nenhum'}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Reset total do ambiente (DESTRUTIVO).")
    p.add_argument("--backup", action="store_true",
                   help="roda backup_all_orgs() para o R2 antes de apagar")
    p.add_argument("--apply", action="store_true",
                   help="executa de verdade (sem isto é dry-run)")
    p.add_argument("--public-host", metavar="HOST:PORT",
                   help="troca o host da URL (proxy TCP publico do Railway)")
    sys.exit(asyncio.run(_main(p.parse_args())))
