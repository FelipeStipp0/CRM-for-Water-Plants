from __future__ import annotations

"""
WMApp Frontend - Executor de emissão SIFEN (roda NO PC — modelo A).

Recebe um job do coordenador (doc + items + condicion), busca as credenciais
decifradas no backend, resolve o receptor pela sessão do portal, monta o DTE e
emite (login→generar→sign→guardar→baixar_xml). Devolve os campos do SET + tempos
por fase. É o mesmo pipeline que emitiu a factura real em ~7s, agora dentro do app.

Empacotamento (Option A): o pipeline (backend, puro) e o adapter fechado (junction
em services/sifen_adapter) são bundlados no instalador do Flet.
"""

import re
import sys
import time
from pathlib import Path

# --- torna o pipeline (backend) importável em dev; no build vem bundlado ---
_FRONTEND = Path(__file__).resolve().parent.parent
_BACKEND = _FRONTEND.parent / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.sifen import receptor as _receptor       # pipeline puro
from app.services.sifen import dte_builder as _dte_builder
from services.sifen_adapter import build_provider          # adapter fechado (junction)
from services.sifen_service import sifen_service
from services.sifen_coordinator import EmissionAborted


class EmissionFailed(Exception):
    """Falha de negócio/firma (vira FALHOU, sem guardar)."""


def _sem_fase(_fase: str, _cdc=None) -> dict:
    """Sem reporte de fase (uso direto do executor, fora do coordenador)."""
    return {}


def _extrai(xml: bytes, tag: str):
    m = re.search(rf"<{tag}>(.*?)</{tag}>".encode(), xml)
    return m.group(1).decode("utf-8", "ignore") if m else None


def cancelar_job(job: dict) -> dict:
    """
    Executor local da cancelación fiscal: login → cancelar(cdc, motivo) → logout.
    Levanta em falha (o loop reporta `cancel_error` e o job sai da fila).
    """
    cdc = job.get("cdc")
    if not cdc:
        raise EmissionFailed("Emisión sin CDC — no hay documento que cancelar")

    creds = sifen_service.get_credenciais()
    prov = build_provider(creds["ruc"], creds["clave"], creds["pin"])
    t0 = time.perf_counter()
    prov.login()
    try:
        prov.cancelar(cdc, job.get("cancel_motivo") or "Anulación de pago")
        return {"phases_ms": {"cancelar": int((time.perf_counter() - t0) * 1000)}}
    finally:
        try:
            prov.logout()
        except Exception:
            pass


def emitir_job(job: dict, on_fase=None) -> dict:
    """
    Executor local. Retorna {cdc, numero_documento, dprot_aut, xml_r2_key, phases_ms}.
    Levanta em falha (o loop marca FALHOU).

    `on_fase(fase, cdc=None) -> dict` reporta o andamento (o operador pode estar
    em outro PC) e devolve o estado atual da emissão no backend — é por aí que
    chega o pedido de desistência. Só olhamos esse pedido ANTES da firma: depois
    dela o documento existe no SET e a única saída é o evento de cancelación.
    O CDC vai junto assim que `generar` responde, porque é dele que sai o número
    da factura que o operador vê na tela (e a reconciliação, se o PC cair).
    """
    phases: dict = {}
    on_fase = on_fase or _sem_fase

    def timed(name, fn):
        t0 = time.perf_counter()
        r = fn()
        phases[name] = int((time.perf_counter() - t0) * 1000)
        return r

    creds = sifen_service.get_credenciais()  # {ruc, clave, pin} — decifrado p/ a org
    prov = build_provider(creds["ruc"], creds["clave"], creds["pin"])
    on_fase("GENERAR")
    timed("login", prov.login)
    try:
        rec = timed("resolver", lambda: _receptor.resolver_receptor(
            prov, job["doc"], tipo_id=job.get("tipo_id") or 1,
            nombre=job.get("nombre"),
            ruc_lookup=lambda d: sifen_service.ruc_lookup(d)))
        dte = _dte_builder.build_dte(
            rec, job["items"],
            job.get("condicion") or {"tipo": "contado",
                                     "forma_pago": {"codigo": 1, "desc": "Efectivo"}})
        g = timed("generar", lambda: prov.generar(dte))

        # Ponto de não-retorno: reportar FIRMAR devolve o estado atual, e é a
        # última chance de ver que o operador desistiu.
        estado = on_fase("FIRMAR", g["cdc"]) or {}
        if estado.get("abort_solicitado"):
            raise EmissionAborted("emisión abortada por el operador antes de la firma")

        if not timed("sign", lambda: prov.sign(g["url_proceso"])):
            raise EmissionFailed("firma falhou (breaker) — documento NÃO guardado")
        on_fase("RECUPERAR")
        timed("guardar", lambda: prov.guardar(g["proceso_id"], g["documento_id"]))
        xml = timed("xml", lambda: prov.baixar_xml(g["cdc"]))
        if b"dsig:Signature" not in xml or b"<dCarQR>" not in xml:
            raise EmissionFailed("XML sem assinatura/QR")
        return {
            "cdc": g["cdc"],
            "numero_documento": _extrai(xml, "dNumDoc"),
            "dprot_aut": _extrai(xml, "dProtAut"),
            "xml_r2_key": None,  # XML é público por CDC; storage em R2 fica p/ próximo passo
            "phases_ms": phases,
        }
    finally:
        try:
            prov.logout()
        except Exception:
            pass
