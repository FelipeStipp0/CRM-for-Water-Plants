from __future__ import annotations

"""
WMApp Frontend - Caja Service
Sessao de caja (turno): apertura, resumo do turno e cierre.

Endpoints em `/caja/*` — separados de `/finance/*` porque o cajero nao tem o
escopo "finance".
"""
from typing import Optional

from services.api_client import api


class CajaService:
    """Apertura/cierre do turno de caja."""

    def actual(self) -> Optional[dict]:
        """Caja aberta do usuario logado, ou None se nao houver."""
        return api.get("/caja/actual")

    def abrir(self, monto_inicial: float = 0) -> dict:
        """Abre um turno com o fondo de cambio contado. 409 se ja houver uma aberta."""
        return api.post("/caja/abrir", data={"monto_inicial": monto_inicial})

    def preview(self, session_id: Optional[str] = None) -> dict:
        """Resumo do turno em andamento (sem gravar)."""
        params = {"session_id": session_id} if session_id else None
        return api.get("/caja/preview", params=params)

    def cerrar(
        self, efectivo_fisico: float, observaciones: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Fecha o turno com o efectivo contado; devolve a sessao com a diferencia."""
        endpoint = "/caja/cerrar"
        if session_id:
            endpoint += f"?session_id={session_id}"
        return api.post(endpoint, data={
            "efectivo_fisico": efectivo_fisico,
            "observaciones": observaciones,
        })

    def sesiones(
        self, limit: int = 50, operador: Optional[str] = None,
        estado: Optional[str] = None,
    ) -> list[dict]:
        """Historico de cajas (mais recentes primeiro)."""
        params: dict = {"limit": limit}
        if operador:
            params["operador"] = operador
        if estado:
            params["estado"] = estado
        return api.get("/caja/sesiones", params=params)


caja_service = CajaService()
