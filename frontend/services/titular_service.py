"""
WMApp Frontend - Titular Service

O titular é a PESSOA; a ligação (Client) é a casa. Um dono costuma ter várias —
residência, imóveis de aluguel, comércio. Este service responde "quais casas são
desta pessoa?" e cria uma casa nova sem redigitar nome/documento/contato.
"""
from typing import List, Optional

from services.api_client import api


class TitularService:
    """Fala com /titulares no backend."""

    def buscar(self, query: Optional[str] = None, limit: int = 50) -> List[dict]:
        """Busca por nome ou documento. Cada item traz `total_conexiones`."""
        params = {"limit": limit}
        if query:
            params["q"] = query
        return api.get("/titulares/", params=params)

    def get(self, titular_id: str) -> dict:
        return api.get(f"/titulares/{titular_id}")

    def conexiones(self, titular_id: str) -> List[dict]:
        """Todas as ligações do titular."""
        return api.get(f"/titulares/{titular_id}/conexiones")

    def crear(self, data: dict) -> dict:
        return api.post("/titulares/", data=data)

    def actualizar(self, titular_id: str, data: dict) -> dict:
        return api.patch(f"/titulares/{titular_id}", data=data)

    def agregar_residencia(self, titular_id: str, data: dict) -> dict:
        """
        Cria uma ligação nova para o titular.

        Só o que muda de casa para casa: direccion, manzana, lote, medidor,
        categoria e uma `etiqueta` opcional ("Casa 02") que entra no nome da
        ligação — nome e documento vêm do titular.
        """
        return api.post(f"/titulares/{titular_id}/residencias", data=data)


titular_service = TitularService()
