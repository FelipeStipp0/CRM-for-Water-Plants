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

    def get_by_group(self, grupo: str) -> dict:
        """Busca pagamento pelo grupo_pagamento."""
        return api.get(f"/payments/by-group/{grupo}")

    def list_by_client(self, client_id: str, limit: int = 24) -> list[dict]:
        """Lista historico de pagamentos por cliente."""
        return api.get(f"/payments/client/{client_id}", params={"limit": limit})


payment_service = PaymentService()
