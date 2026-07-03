from __future__ import annotations

"""
WMApp Frontend - Finance Service
Servicos para o modulo financeiro.
"""
from typing import Optional

from services.api_client import api


class FinanceService:
    """Gerencia operacoes do modulo financeiro."""

    # Cash transactions
    def create_transaction(self, data: dict) -> dict:
        return api.post("/finance/transactions", data=data)

    def list_transactions(
        self,
        tipo: Optional[str] = None,
        categoria: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        params = {"skip": skip, "limit": limit}
        if tipo:
            params["tipo"] = tipo
        if categoria:
            params["categoria"] = categoria
        if fecha_inicio:
            params["fecha_inicio"] = fecha_inicio
        if fecha_fin:
            params["fecha_fin"] = fecha_fin
        return api.get("/finance/transactions", params=params)

    def get_summary(self, fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None) -> dict:
        params = {}
        if fecha_inicio:
            params["fecha_inicio"] = fecha_inicio
        if fecha_fin:
            params["fecha_fin"] = fecha_fin
        return api.get("/finance/summary", params=params)

    def get_by_category(self, fecha_inicio: Optional[str] = None, fecha_fin: Optional[str] = None) -> list[dict]:
        params = {}
        if fecha_inicio:
            params["fecha_inicio"] = fecha_inicio
        if fecha_fin:
            params["fecha_fin"] = fecha_fin
        return api.get("/finance/by-category", params=params)

    # Expenses
    def create_expense(self, data: dict) -> dict:
        return api.post("/finance/expenses", data=data)

    def list_expenses(
        self,
        status: Optional[str] = None,
        categoria: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        params = {"skip": skip, "limit": limit}
        if status:
            params["status"] = status
        if categoria:
            params["categoria"] = categoria
        return api.get("/finance/expenses", params=params)

    def list_pending_expenses(self) -> list[dict]:
        return api.get("/finance/expenses/pending")

    def pay_expense(self, expense_id: str, observacion: Optional[str] = None) -> dict:
        payload = {"observacion": observacion} if observacion else {}
        return api.post(f"/finance/expenses/{expense_id}/pay", data=payload)

    # Employees
    def create_employee(self, data: dict) -> dict:
        return api.post("/finance/employees", data=data)

    def list_employees(self, status: Optional[str] = None) -> list[dict]:
        params = {"status": status} if status else None
        return api.get("/finance/employees", params=params)

    def update_employee(self, employee_id: str, data: dict) -> dict:
        return api.patch(f"/finance/employees/{employee_id}", data=data)

    # Payroll
    def create_payroll(self, data: dict) -> dict:
        return api.post("/finance/payroll", data=data)

    def list_payroll(
        self,
        employee_id: Optional[str] = None,
        status: Optional[str] = None,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        params = {"skip": skip, "limit": limit}
        if employee_id:
            params["employee_id"] = employee_id
        if status:
            params["status"] = status
        if mes is not None:
            params["mes"] = mes
        if ano is not None:
            params["ano"] = ano
        return api.get("/finance/payroll", params=params)

    def pay_payroll(self, payroll_id: str, observacion: Optional[str] = None) -> dict:
        payload = {"observacion": observacion} if observacion else {}
        return api.post(f"/finance/payroll/{payroll_id}/pay", data=payload)

    def cancel_payroll(self, payroll_id: str) -> dict:
        return api.post(f"/finance/payroll/{payroll_id}/cancel", data={})


finance_service = FinanceService()
