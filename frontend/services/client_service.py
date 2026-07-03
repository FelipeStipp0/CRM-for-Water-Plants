"""
WMApp Frontend - Client Service
Serviço para operações de clientes
"""
from typing import Optional, List
from services.api_client import api


class ClientService:
    """Gerencia operações de clientes."""
    
    def search(
        self,
        query: Optional[str] = None,
        manzana: Optional[str] = None,
        lote: Optional[str] = None,
        is_sponsor: Optional[bool] = None,
        limit: int = 50,
    ) -> List[dict]:
        """
        Busca clientes por nome, CI/RUC, medidor ou localização.
        """
        params = {"limit": limit}
        if query:
            params["q"] = query
        if manzana:
            params["manzana"] = manzana
        if lote:
            params["lote"] = lote
        if is_sponsor is not None:
            params["is_sponsor"] = is_sponsor
        
        return api.get("/clients/search", params=params)
    
    def list(self, skip: int = 0, limit: int = 50, status: Optional[str] = None) -> List[dict]:
        """Lista clientes com paginação."""
        params = {"skip": skip, "limit": limit}
        if status:
            params["status"] = status
        return api.get("/clients/", params=params)

    def list_paged(self, skip: int = 0, limit: int = 50, status: Optional[str] = None) -> tuple[List[dict], int]:
        """Lista clientes retornando (dados, total_real)."""
        params = {"skip": skip, "limit": limit}
        if status:
            params["status"] = status
        return api.get_with_total("/clients/", params=params)
    
    def get(self, client_id: str) -> dict:
        """Retorna cliente por ID."""
        return api.get(f"/clients/{client_id}")
    
    def create(self, data: dict) -> dict:
        """Cria novo cliente."""
        return api.post("/clients/", data=data)
    
    def update(self, client_id: str, data: dict) -> dict:
        """Atualiza cliente."""
        return api.patch(f"/clients/{client_id}", data=data)
    
    def delete(self, client_id: str) -> None:
        """Remove cliente (apenas sem faturas)."""
        return api.delete(f"/clients/{client_id}")
    
    def list_by_route(self, manzana: Optional[str] = None) -> List[dict]:
        """Lista clientes ordenados por rota (Manzana -> Lote)."""
        params = {}
        if manzana:
            params["manzana"] = manzana
        return api.get("/clients/by-route", params=params)
    
    def list_with_debt(self, limit: int = 100) -> List[dict]:
        """Lista clientes com dívidas pendentes."""
        return api.get("/clients/with-debt", params={"limit": limit})
    
    def get_readings(self, client_id: str, limit: int = 12) -> List[dict]:
        """Retorna histórico de leituras do cliente."""
        return api.get(f"/readings/client/{client_id}", params={"limit": limit})
    
    def get_invoices(self, client_id: str, status: Optional[str] = None, limit: int = 24) -> List[dict]:
        """Retorna faturas do cliente."""
        params = {"limit": limit}
        if status:
            params["status"] = status
        return api.get(f"/invoices/client/{client_id}", params=params)
    
    def get_pending_balance(self, client_id: str) -> dict:
        """Retorna saldo pendente total do cliente."""
        return api.get(f"/invoices/client/{client_id}/pending-balance")


# Instância global
client_service = ClientService()
