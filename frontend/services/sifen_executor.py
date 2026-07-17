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


class EmissionFailed(Exception):
    """Falha de negócio/firma (vira FALHOU, sem guardar)."""


def _extrai(xml: bytes, tag: str):
    m = re.search(rf"<{tag}>(.*?)</{tag}>".encode(), xml)
    return m.group(1).decode("utf-8", "ignore") if m else None


def emitir_job(job: dict) -> dict:
    """
    Executor local. Retorna {cdc, numero_documento, dprot_aut, xml_r2_key, phases_ms}.
    Levanta em falha (o loop marca FALHOU).
    """
    phases: dict = {}

    def timed(name, fn):
        t0 = time.perf_counter()
        r = fn()
        phases[name] = int((time.perf_counter() - t0) * 1000)
        return r

    creds = sifen_service.get_credenciais()  # {ruc, clave, pin} — decifrado p/ a org
    prov = build_provider(creds["ruc"], creds["clave"], creds["pin"])
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
        if not timed("sign", lambda: prov.sign(g["url_proceso"])):
            raise EmissionFailed("firma falhou (breaker) — documento NÃO guardado")
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
