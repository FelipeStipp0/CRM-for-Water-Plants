from __future__ import annotations

"""
WMApp Frontend - Invoice Service
Servicos para operacoes de faturas.
"""
from typing import Optional

from services.api_client import api


class InvoiceService:
    """Gerencia operacoes de faturas."""

    def list(
        self,
        status: Optional[str] = None,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """Lista faturas com filtros."""
        params = {"skip": skip, "limit": limit}
        if status:
            params["status"] = status
        if mes is not None:
            params["mes"] = mes
        if ano is not None:
            params["ano"] = ano
        return api.get("/invoices/", params=params)

    def list_paged(
        self,
        status: Optional[str] = None,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """Lista faturas retornando (dados, total_real)."""
        params = {"skip": skip, "limit": limit}
        if status:
            params["status"] = status
        if mes is not None:
            params["mes"] = mes
        if ano is not None:
            params["ano"] = ano
        return api.get_with_total("/invoices/", params=params)

    def get_by_number(self, numero: int) -> dict:
        """Busca fatura pelo número."""
        return api.get(f"/invoices/by-number/{numero}")

    def list_pending(self, limit: int = 100) -> list[dict]:
        """Lista faturas pendentes."""
        return api.get("/invoices/pending", params={"limit": limit})

    def create_custom(self, data: dict) -> dict:
        """Cria fatura avulsa."""
        return api.post("/invoices/", data=data)

    def generate_batch(self, mes_referencia: int, ano_referencia: int, client_ids: Optional[list[str]] = None) -> dict:
        """Gera faturas de consumo em lote."""
        payload = {"mes_referencia": mes_referencia, "ano_referencia": ano_referencia}
        if client_ids:
            payload["client_ids"] = client_ids
        return api.post("/invoices/generate", data=payload)

    def generate_batch_extended(
        self,
        mes_referencia: int,
        ano_referencia: int,
        *,
        client_ids: Optional[list[str]] = None,
        gerar_sem_leitura_valor_minimo: Optional[bool] = None,
        matching_prioridade: Optional[list[str]] = None,
        dia_geracao: Optional[int] = None,
    ) -> dict:
        """
        Gera faturas em lote com payload estendido.

        Mantem compatibilidade: se backend nao suportar os campos extras,
        ele deve retornar 422/400 e o frontend informa a necessidade de update.
        """
        payload = {"mes_referencia": mes_referencia, "ano_referencia": ano_referencia}
        if client_ids:
            payload["client_ids"] = client_ids
        if gerar_sem_leitura_valor_minimo is not None:
            payload["gerar_sem_leitura_valor_minimo"] = bool(gerar_sem_leitura_valor_minimo)
        if matching_prioridade:
            payload["matching_prioridade"] = matching_prioridade
        if dia_geracao is not None:
            payload["dia_geracao"] = int(dia_geracao)
        return api.post("/invoices/generate", data=payload)

    def get(self, invoice_id: str) -> dict:
        """Busca fatura por ID."""
        return api.get(f"/invoices/{invoice_id}")

    def get_with_balance(self, invoice_id: str) -> dict:
        """Busca fatura com saldo pendente anterior."""
        return api.get(f"/invoices/{invoice_id}/with-balance")

    def cancel(self, invoice_id: str) -> dict:
        """Anula uma fatura."""
        return api.patch(f"/invoices/{invoice_id}/cancel", data={})

    def delete(self, invoice_id: str) -> dict:
        """Exclui uma fatura com cascade de registros relacionados."""
        return api.delete(f"/invoices/{invoice_id}")

    def list_by_client(self, client_id: str, status: Optional[str] = None, limit: int = 24) -> list[dict]:
        """Lista faturas de um cliente."""
        params = {"limit": limit}
        if status:
            params["status"] = status
        return api.get(f"/invoices/client/{client_id}", params=params)


invoice_service = InvoiceService()
