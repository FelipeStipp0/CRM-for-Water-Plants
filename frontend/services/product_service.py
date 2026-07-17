from __future__ import annotations

"""
WMApp Frontend - Product Service
Catálogo de produtos/serviços (/products). Usado no cadastro e nos pickers de
fatura manual e facturación electrónica.
"""
from typing import Optional

from services.api_client import api


class ProductService:
    def listar(self, activo: Optional[bool] = None) -> list[dict]:
        params = {}
        if activo is not None:
            params["activo"] = str(activo).lower()
        return api.get("/products/", params=params or None)

    def criar(self, data: dict) -> dict:
        return api.post("/products/", data=data)

    def atualizar(self, product_id: str, data: dict) -> dict:
        return api.patch(f"/products/{product_id}", data=data)

    def desativar(self, product_id: str) -> None:
        return api.delete(f"/products/{product_id}")


product_service = ProductService()
