from __future__ import annotations

"""
WMApp Frontend - Payment Service
Servicos para operacoes de pagamentos.
"""
from typing import Optional

from services.api_client import api


class PaymentService:
    """Gerencia operacoes de pagamentos."""

    def create(self, data: dict) -> dict:
        """Processa um pagamento."""
        return api.post("/payments/", data=data)

    def list(self, skip: int = 0, limit: int = 50) -> list[dict]:
        """Lista pagamentos recentes."""
        return api.get("/payments/", params={"skip": skip, "limit": limit})

    def list_paged(self, skip: int = 0, limit: int = 50) -> tuple[list[dict], int]:
        """Lista pagamentos retornando (dados, total_real)."""
        return api.get_with_total("/payments/", params={"skip": skip, "limit": limit})

    def get(self, payment_id: str) -> dict:
        """Busca pagamento por ID."""
        return api.get(f"/payments/{payment_id}")

    def anular(self, payment_id: str, motivo: str) -> dict:
        """Estorna (anula) um pagamento — restaura faturas + estorno no caixa + auditoria."""
        return api.post(f"/payments/{payment_id}/anular", data={"motivo": motivo})

    def get_by_group(self, grupo: str) -> dict:
        """Busca pagamento pelo grupo_pagamento."""
        return api.get(f"/payments/by-group/{grupo}")

    def atenciones(
        self,
        q: Optional[str] = None,
        desde: Optional[str] = None,
        hasta: Optional[str] = None,
        solo_mi_caja: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        """
        Atendimentos anteriores para o balcão: reimprimir, anular e conferir.

        `q` casa com nº de recibo, nome ou CI/RUC. `desde`/`hasta` são ISO **em
        UTC** — quem sabe o fuso do balcão é o app, não o servidor.
        """
        params: dict = {"limit": limit}
        if q:
            params["q"] = q
        if desde:
            params["desde"] = desde
        if hasta:
            params["hasta"] = hasta
        if solo_mi_caja:
            params["solo_mi_caja"] = True
        return api.get("/payments/atenciones", params=params)

    def list_by_client(self, client_id: str, limit: int = 24) -> list[dict]:
        """Lista historico de pagamentos por cliente."""
        return api.get(f"/payments/client/{client_id}", params={"limit": limit})


payment_service = PaymentService()
