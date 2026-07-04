"""
Fila de emissão da facturación electrónica (processada pelo coordenador).

- `claim_next`: pega atomicamente o próximo job PENDENTE (marca PROCESSANDO).
- `processar_emissao`: roda o pipeline contra o portal, com **lock de sessão único**,
  **breaker** (não guarda se a firma falha), **logout sempre**, validação do XML
  (dsig+QR), gravação no R2 e **auto-retry** em erro de rede. Idempotente: se o job
  já tem CDC (coordenador caiu no meio), reconcilia via listar em vez de re-emitir.

Só roda numa máquina que tem o adapter (provider_disponivel()). Depende apenas da
interface pública SifenProvider — nada específico do portal mora aqui.
"""

import re
from datetime import datetime
from typing import Callable, Optional

from pymongo import ReturnDocument
from requests.exceptions import ConnectionError as ReqConnError, Timeout

from app.models.sifen import SifenEmission, EmissionStatus
from app.services.sifen import lock
from app.services.sifen.dte_builder import build_dte
from app.services.sifen.receptor import resolver_receptor
from app.services.sifen.provider import get_provider, ProviderNaoInstalado
from app.services.sifen.crypto_creds import carregar_credenciais
from app.utils.r2 import r2_put


class EmissionError(RuntimeError):
    """Erro de negócio/firma que interrompe a emissão (não é rede)."""


def _erro_de_rede(e: Exception) -> bool:
    return isinstance(e, (ReqConnError, Timeout))


def _extrai(xml: bytes, tag: str) -> Optional[str]:
    m = re.search(rf"<{tag}>(.*?)</{tag}>".encode(), xml)
    return m.group(1).decode("utf-8", "ignore") if m else None


def _ja_aprovada(listagem: dict, cdc: str) -> bool:
    """Heurística: o CDC aparece na listagem do portal com estado aprovado."""
    itens = (listagem or {}).get("genericList") or (listagem or {}).get("data") or []
    for it in itens if isinstance(itens, list) else []:
        if str(it.get("cdc") or it.get("CDC") or "") == cdc:
            estado = str(it.get("estado") or it.get("dEstRes") or "").upper()
            return estado in ("APROBADO", "A", "APPROVED")
    return False


async def claim_next(holder: str) -> Optional[SifenEmission]:
    """Reivindica atomicamente o próximo job PENDENTE (mais antigo primeiro)."""
    now = datetime.utcnow()
    coll = SifenEmission.get_pymongo_collection()
    doc = await coll.find_one_and_update(
        {"status": EmissionStatus.PENDENTE.value},
        {"$set": {"status": EmissionStatus.PROCESSANDO.value,
                  "locked_by": holder, "locked_at": now, "started_at": now,
                  "updated_at": now}},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        return None
    # telemetria de atividade: jobs em voo neste instante
    em_voo = await coll.count_documents(
        {"status": {"$in": [EmissionStatus.PENDENTE.value, EmissionStatus.PROCESSANDO.value]}})
    await coll.update_one({"_id": doc["_id"]}, {"$set": {"queue_depth_at_start": em_voo}})
    return await SifenEmission.get(doc["_id"])


async def claim_for_device(machine_id: str) -> Optional[SifenEmission]:
    """
    Serve o próximo job a um device — **gateado pelo lock de sessão** (jamais duas
    sessões). Só entrega job se este device conseguir o lock; se não houver job,
    devolve o lock na hora. O lock fica retido até o device concluir (release_sessao).
    """
    if not await lock.adquirir(machine_id):
        return None  # outro device está com a sessão aberta
    job = await claim_next(machine_id)
    if job is None:
        await lock.liberar(machine_id)  # nada a fazer → solta a sessão
        return None
    return job


async def release_sessao(holder: str) -> None:
    """Libera o lock de sessão (chamado quando o device conclui/reporta o job)."""
    await lock.liberar(holder)


async def processar_emissao(
    job: SifenEmission,
    holder: str,
    *,
    provider_factory: Optional[Callable] = None,
    load_creds: Optional[Callable] = None,
) -> SifenEmission:
    """
    Processa UM job. Requer o lock de sessão; se ocupado, devolve o job a PENDENTE
    (fica na fila). Sempre faz logout e libera o lock no fim.
    """
    provider_factory = provider_factory or get_provider
    load_creds = load_creds or carregar_credenciais

    if not await lock.adquirir(holder):
        # outra máquina detém a sessão → volta pra fila
        job.status = EmissionStatus.PENDENTE
        job.locked_by = None
        job.updated_at = datetime.utcnow()
        await job.save()
        return job

    prov = None
    try:
        ruc, clave, pin = await load_creds()
        prov = provider_factory(ruc, clave, pin)
        prov.login()

        # idempotência: job com CDC já setado (coordenador caiu no meio)
        if job.cdc:
            if _ja_aprovada(prov.listar({"cdc": job.cdc}), job.cdc):
                job.status = EmissionStatus.EMITIDA
                job.error = None
                return job

        # resolve o receptor pela sessão do portal (contribuyente/ciudadano/OEE)
        rec = resolver_receptor(prov, job.doc, tipo_id=job.tipo_id or 1)
        job.receptor = rec
        dte = build_dte(rec, job.items, job.condicion)
        g = prov.generar(dte)
        job.cdc = g["cdc"]
        job.proceso_id = g["proceso_id"]
        job.documento_id = g["documento_id"]
        await job.save()  # PROCESSANDO, com CDC (para reconciliação em caso de crash)

        if not prov.sign(g["url_proceso"]):
            raise EmissionError("firma falhou (breaker) — documento NÃO guardado")

        prov.guardar(job.proceso_id, job.documento_id)
        xml = prov.baixar_xml(job.cdc)
        if b"dsig:Signature" not in xml or b"<dCarQR>" not in xml:
            raise EmissionError("XML sem assinatura/QR")

        key = f"sifen/{job.cdc}.xml"
        r2_put(key, xml, "application/xml")
        job.xml_r2_key = key
        job.numero_documento = _extrai(xml, "dNumDoc")
        job.dprot_aut = _extrai(xml, "dProtAut")
        job.status = EmissionStatus.EMITIDA
        job.error = None

    except ProviderNaoInstalado:
        # esta máquina não é coordenador (sem adapter) → devolve à fila
        job.status = EmissionStatus.PENDENTE
        job.locked_by = None
    except Exception as e:  # noqa: BLE001 — captura ampla proposital (best-effort)
        job.error = str(e)
        # erro de rede: volta pra fila (auto-retry); demais: FALHOU
        job.status = EmissionStatus.PENDENTE if _erro_de_rede(e) else EmissionStatus.FALHOU
    finally:
        if prov is not None:
            try:
                prov.logout()
            except Exception:
                pass
        await lock.liberar(holder)
        job.updated_at = datetime.utcnow()
        await job.save()

    return job
