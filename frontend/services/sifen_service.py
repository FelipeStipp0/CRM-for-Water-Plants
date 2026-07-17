from __future__ import annotations

"""
WMApp Frontend - SIFEN Service
Camada de API da facturación electrónica (emissão + coordenação de dispositivos).
"""
from typing import Optional

from services.api_client import api


class SifenService:
    """Fala com /sifen no backend."""

    # ---------- operador ----------
    def emitir(self, client_request_id: str, doc: str, items: list[dict],
               nombre: Optional[str] = None, tipo_id: int = 1,
               condicion: Optional[dict] = None, client_id: Optional[str] = None,
               payment_id: Optional[str] = None) -> dict:
        """Enfileira uma emissão (idempotente por client_request_id).

        O coordenador resolve o receptor a partir de `doc` (RUC/CI/OEE) na sessão
        do portal — aqui só mandamos o documento e os itens.
        """
        body = {
            "client_request_id": client_request_id,
            "doc": doc,
            "tipo_id": tipo_id,
            "items": items,
        }
        if nombre:
            body["nombre"] = nombre
        if condicion:
            body["condicion"] = condicion
        if client_id:
            body["client_id"] = client_id
        if payment_id:
            body["payment_id"] = payment_id
        return api.post("/sifen/emitir", data=body)

    def ruc_lookup(self, doc: str) -> dict:
        """Consulta o registro DNIT: {found, estado, es_contribuyente, nombre, dv}."""
        return api.get("/sifen/ruc-lookup", params={"doc": doc})

    def get_emision(self, emission_id: str) -> dict:
        return api.get(f"/sifen/emision/{emission_id}")

    def listar_emisiones(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        params = {"limit": limit}
        if status:
            params["status"] = status
        return api.get("/sifen/emisiones", params=params)

    # ---------- credenciais ----------
    def salvar_credenciais(self, ruc: str, clave: str, pin: str) -> dict:
        """Admin (master) seta as credenciais do portal."""
        return api.post("/sifen/credenciais", data={"ruc": ruc, "clave": clave, "pin": pin})

    def get_credenciais(self) -> dict:
        """Credenciais decifradas p/ o coordenador emitir ({ruc, clave, pin})."""
        return api.get("/sifen/credenciais")

    # ---------- dispositivos / coordenação ----------
    def announce(self, machine_id: str, label: Optional[str] = None) -> dict:
        return api.post("/sifen/coordinator/announce",
                        data={"machine_id": machine_id, "label": label})

    def poll(self, machine_id: str) -> Optional[dict]:
        """Reivindica o próximo job (gateado por sessão). None se nada / PC não permitido."""
        return api.post("/sifen/coordinator/poll", data={"machine_id": machine_id})

    def patch_result(self, emission_id: str, payload: dict) -> dict:
        return api.patch(f"/sifen/coordinator/{emission_id}", data=payload)

    def listar_coordinators(self) -> list[dict]:
        return api.get("/sifen/coordinators")

    def permitir(self, machine_id: str, enabled: bool, label: Optional[str] = None) -> dict:
        return api.post("/sifen/coordinator/permitir",
                        data={"machine_id": machine_id, "enabled": enabled, "label": label})


sifen_service = SifenService()
