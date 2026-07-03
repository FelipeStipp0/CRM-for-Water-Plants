from __future__ import annotations

"""
WMApp Frontend - Reading Service
Servicos para operacoes de leituras.
"""
from typing import Optional

from services.api_client import api


class ReadingService:
    """Gerencia operacoes de leituras."""

    def list(self, mes: Optional[int] = None, ano: Optional[int] = None, skip: int = 0, limit: int = 50) -> list[dict]:
        """Lista leituras com filtros opcionais."""
        params = {"skip": skip, "limit": limit}
        if mes is not None:
            params["mes"] = mes
        if ano is not None:
            params["ano"] = ano
        return api.get("/readings/", params=params)

    def list_paged(self, mes: Optional[int] = None, ano: Optional[int] = None, skip: int = 0, limit: int = 50) -> tuple[list[dict], int]:
        """Lista leituras retornando (dados, total_real)."""
        params = {"skip": skip, "limit": limit}
        if mes is not None:
            params["mes"] = mes
        if ano is not None:
            params["ano"] = ano
        return api.get_with_total("/readings/", params=params)

    def create(self, data: dict) -> dict:
        """Cria leitura individual."""
        return api.post("/readings/", data=data)

    def create_batch(self, data: dict) -> dict:
        """Insere leituras em lote."""
        return api.post("/readings/batch", data=data)

    def list_by_route(self, mes: int, ano: int, manzana: Optional[str] = None) -> list[dict]:
        """Lista leituras por rota."""
        params = {"mes": mes, "ano": ano}
        if manzana:
            params["manzana"] = manzana
        return api.get("/readings/by-route", params=params)

    def list_pending(self, mes: int, ano: int, manzana: Optional[str] = None) -> list[dict]:
        """Lista clientes sem leitura para o periodo."""
        params = {"mes": mes, "ano": ano}
        if manzana:
            params["manzana"] = manzana
        return api.get("/readings/pending", params=params)

    def list_by_client(self, client_id: str, limit: int = 12) -> list[dict]:
        """Lista leituras de um cliente."""
        return api.get(f"/readings/client/{client_id}", params={"limit": limit})


reading_service = ReadingService()
