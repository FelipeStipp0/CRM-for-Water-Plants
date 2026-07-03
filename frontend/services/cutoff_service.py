from __future__ import annotations

"""
WMApp Frontend - Cutoff Service
Servicos para workflow de corte e endpoints publicos de QR.
"""

from typing import Optional

from services.api_client import api


class CutoffService:
    """Gerencia operacoes do workflow de corte."""

    def list_candidates(self) -> list[dict]:
        return api.get("/cutoff/candidates")

    def add_notice(self, client_id: str) -> dict:
        return api.post("/cutoff/notices", data={"client_id": client_id})

    def list_notices(
        self,
        status: Optional[str] = None,
        include_exited: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        params = {"include_exited": include_exited, "skip": skip, "limit": limit}
        if status:
            params["status"] = status
        return api.get("/cutoff/notices", params=params)

    def list_ready(self, limit: int = 50) -> list[dict]:
        return api.get("/cutoff/notices/ready", params={"limit": limit})

    def get_notice(self, notice_id: str) -> dict:
        return api.get(f"/cutoff/notices/{notice_id}")

    def get_notice_by_client(self, client_id: str) -> Optional[dict]:
        return api.get(f"/cutoff/notices/client/{client_id}")

    def generate_notice(self, notice_id: str) -> dict:
        return api.post(f"/cutoff/notices/{notice_id}/generate", data={})

    def register_delivery(self, notice_id: str, entregue_por: Optional[str] = None, observacion: Optional[str] = None) -> dict:
        payload: dict = {}
        if entregue_por:
            payload["entregue_por"] = entregue_por
        if observacion:
            payload["observacion"] = observacion
        return api.post(f"/cutoff/notices/{notice_id}/deliver", data=payload)

    def mark_ready(self, notice_id: str) -> dict:
        return api.post(f"/cutoff/notices/{notice_id}/mark-ready", data={})

    def generate_order(self, notice_id: str) -> dict:
        return api.post(f"/cutoff/notices/{notice_id}/generate-order", data={})

    def execute_cutoff(self, notice_id: str, cortado_por: Optional[str] = None, observacion: Optional[str] = None) -> dict:
        payload: dict = {}
        if cortado_por:
            payload["cortado_por"] = cortado_por
        if observacion:
            payload["observacion"] = observacion
        return api.post(f"/cutoff/notices/{notice_id}/execute", data=payload)

    def request_reactivation(self, client_id: str, valor_pago: float) -> dict:
        return api.post(
            "/cutoff/reactivation/request",
            data={"client_id": client_id, "valor_pago": valor_pago},
        )

    def confirm_reactivation(self, notice_id: str, confirmado_por: Optional[str] = None) -> dict:
        payload: dict = {}
        if confirmado_por:
            payload["confirmado_por"] = confirmado_por
        return api.post(f"/cutoff/reactivation/{notice_id}/confirm", data=payload)

    def process_expired(self) -> dict:
        return api.post("/cutoff/notices/process-expired", data={})

    def qr_info(self, token: str) -> dict:
        return api.get(f"/cutoff/qr/{token}/info")

    def qr_confirm(self, token: str, nome_responsavel: str, observacion: Optional[str] = None) -> dict:
        payload = {"nome_responsavel": nome_responsavel}
        if observacion:
            payload["observacion"] = observacion
        return api.post(f"/cutoff/qr/{token}/confirm", data=payload)


cutoff_service = CutoffService()

