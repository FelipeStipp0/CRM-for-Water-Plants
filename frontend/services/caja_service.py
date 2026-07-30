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

    def movimiento(self, categoria: str, valor: float, descripcion: str) -> dict:
        """
        Sangría (dinheiro sai da gaveta) ou reposición (volta a entrar).

        Devolve {"movimiento_id", "resumen"} — o resumo já vem recalculado, então
        o efectivo esperado na tela muda na hora, sem segundo round-trip.
        """
        return api.post("/caja/movimiento", data={
            "categoria": categoria, "valor": valor, "descripcion": descripcion,
        })

    def movimientos(self) -> list[dict]:
        """Sangrías e reposiciones do turno aberto."""
        return api.get("/caja/movimientos")

    def productos(self) -> list[dict]:
        """
        Catálogo ativo, só leitura — atalho de preenchimento do cargo do balcão.

        Não é `/products/`: aquele router exige o escopo `invoices`, que o cajero
        não tem, e a chamada voltava **403**.
        """
        return api.get("/caja/productos")

    def cargo(self, client_id: str, descripcion: str, valor: float,
              cantidad: int = 1, iva_tasa: int = 10, iva_afectacion: int = 1) -> dict:
        """
        Fatura um cargo de valor livre para cobrar no mesmo atendimento.

        Não é `POST /invoices/` pelo mesmo motivo de `productos()`: escopo. Exige
        turno aberto e devolve a fatura AVULSA criada (com `id` e `numero_factura`).
        """
        return api.post("/caja/cargo", data={
            "client_id": client_id, "descripcion": descripcion, "valor": valor,
            "cantidad": cantidad, "iva_tasa": iva_tasa, "iva_afectacion": iva_afectacion,
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
