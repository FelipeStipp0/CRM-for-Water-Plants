from __future__ import annotations

"""
WMApp Frontend - Sponsor Service
Servicos para operacoes de sponsor/subsidio.
"""
from typing import Optional

from services.api_client import api


class SponsorService:
    """Gerencia operacoes do modulo de sponsors."""

    def list_sponsors(self) -> list[dict]:
        """Lista clientes marcados como sponsor."""
        return api.get("/sponsors/")

    def list_clients(self, sponsor_id: str) -> list[dict]:
        """Lista clientes subsidiados por um sponsor."""
        return api.get(f"/sponsors/{sponsor_id}/clients")

    def get_summary(self, sponsor_id: str) -> dict:
        """Resumo financeiro do sponsor."""
        return api.get(f"/sponsors/{sponsor_id}/summary")

    def list_debts(
        self,
        sponsor_id: str,
        status: Optional[str] = None,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
    ) -> list[dict]:
        """Lista dividas de subsidio com filtros opcionais."""
        params = {}
        if status:
            params["status"] = status
        if mes is not None:
            params["mes"] = mes
        if ano is not None:
            params["ano"] = ano
        return api.get(f"/sponsors/{sponsor_id}/debts", params=params if params else None)

    def list_invoices(self, sponsor_id: str, status: Optional[str] = None) -> list[dict]:
        """Lista faturas agregadas do sponsor."""
        params = {"status": status} if status else None
        return api.get(f"/sponsors/{sponsor_id}/invoices", params=params)

    def generate_invoice(self, sponsor_id: str, mes_referencia: int, ano_referencia: int) -> dict:
        """Gera fatura agregada mensal."""
        return api.post(
            f"/sponsors/{sponsor_id}/invoices/generate",
            data={"mes_referencia": mes_referencia, "ano_referencia": ano_referencia},
        )

    def pay_invoice(self, invoice_id: str, valor: float, recibido_por: Optional[str] = None) -> dict:
        """Registra pagamento de fatura agregada do sponsor."""
        payload = {"valor": valor, "recibido_por": recibido_por}
        return api.post(f"/sponsors/invoices/{invoice_id}/pay", data=payload)


sponsor_service = SponsorService()

