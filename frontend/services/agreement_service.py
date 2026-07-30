from __future__ import annotations

"""
WMApp Frontend - Acuerdos de pago (parcelamento).

Fala com `/agreements`. O acordo é fechado no balcão: as faturas antigas viram
ANULADA com saldo zero e a dívida passa a viver em parcelas que a geração mensal
soma na fatura de cada mês.
"""
from typing import Optional

from services.api_client import api


class AgreementService:
    """Acordos de pagamento do cliente."""

    def simular(self, total: float, n_parcelas: int, entrada: float = 0) -> dict:
        """
        Cronograma sem gravar nada — a prévia que o cajero mostra ao cliente.

        Vem do backend (e não de uma conta local) para a prévia nunca divergir do
        que vai ser cobrado: quem divide é o mesmo código nos dois casos.
        """
        return api.post("/agreements/simular", data={
            "total": total, "n_parcelas": n_parcelas, "entrada": entrada,
        })

    def crear(
        self,
        client_id: str,
        n_parcelas: int,
        invoice_ids: Optional[list[str]] = None,
        entrada: float = 0,
        metodo: str = "EFECTIVO",
        primera_en_mes_corriente: bool = False,
        cuota_iva_tasa: int = 10,
        cuota_iva_afectacion: int = 1,
        aplicar_subsidio: Optional[bool] = None,
        observacion: Optional[str] = None,
    ) -> dict:
        """Fecha o acordo. Devolve {"acuerdo", "entrada_payment_id"}."""
        data: dict = {
            "client_id": client_id,
            "n_parcelas": n_parcelas,
            "entrada": entrada,
            "metodo": metodo,
            "primera_en_mes_corriente": primera_en_mes_corriente,
            "cuota_iva_tasa": cuota_iva_tasa,
            "cuota_iva_afectacion": cuota_iva_afectacion,
        }
        if invoice_ids:
            data["invoice_ids"] = invoice_ids
        if aplicar_subsidio is not None:
            data["aplicar_subsidio"] = aplicar_subsidio
        if observacion:
            data["observacion"] = observacion
        return api.post("/agreements/", data=data)

    def por_cliente(self, client_id: str, limit: int = 10) -> dict:
        """{"activo": acuerdo|None, "historico": [...]}"""
        return api.get(f"/agreements/client/{client_id}", params={"limit": limit})

    def get(self, agreement_id: str) -> dict:
        """Acordo com as faturas antigas — o que se imprime quando a dívida acaba."""
        return api.get(f"/agreements/{agreement_id}")


agreement_service = AgreementService()
