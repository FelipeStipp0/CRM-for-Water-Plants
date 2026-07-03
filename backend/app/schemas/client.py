"""
Schemas para clientes.

NOTA: O sistema usa TARIFA UNICA GLOBAL.
A 'categoria' e apenas para classificacao, NAO afeta valor.
Descontos sao aplicados via sistema de Subsidio/Sponsor.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.client import ClientCategory, ClientStatus


class ClientCreate(BaseModel):
    """Schema para criacao de cliente."""
    nombre_completo: str = Field(min_length=2, max_length=200)
    ci_ruc: str = Field(min_length=3, max_length=20)
    telefono: Optional[str] = None
    celular: Optional[str] = None
    direccion: str = Field(min_length=5, max_length=300)
    manzana: str = Field(default="", max_length=10)
    lote: str = Field(default="", max_length=10)
    numero_medidor: str = Field(default="SIN_MEDIDOR", min_length=1, max_length=50)
    categoria: ClientCategory = ClientCategory.RESIDENCIAL
    # Marcar como sponsor
    is_sponsor: bool = False
    # Subsidio / Aluguel (cliente com pagador externo)
    sponsor_id: Optional[str] = None
    subsidio_porcentagem: Optional[int] = Field(default=None, ge=0, le=100)
    is_aluguel: bool = False  # True = relacao de aluguel; sponsor e o pagador/proprietario
    # GPS e Foto da instalacao (app mobile)
    instalacao_latitude: Optional[float] = None
    instalacao_longitude: Optional[float] = None
    foto_medidor_url: Optional[str] = None


class ClientUpdate(BaseModel):
    """Schema para atualizacao parcial de cliente."""
    nombre_completo: Optional[str] = None
    telefono: Optional[str] = None
    celular: Optional[str] = None
    direccion: Optional[str] = None
    manzana: Optional[str] = None
    lote: Optional[str] = None
    categoria: Optional[ClientCategory] = None
    status: Optional[ClientStatus] = None
    # Sponsor
    is_sponsor: Optional[bool] = None
    # Subsidio / Aluguel (cliente com pagador externo)
    sponsor_id: Optional[str] = None
    subsidio_porcentagem: Optional[int] = Field(default=None, ge=0, le=100)
    is_aluguel: Optional[bool] = None
    # GPS e Foto da instalacao (app mobile)
    instalacao_latitude: Optional[float] = None
    instalacao_longitude: Optional[float] = None
    foto_medidor_url: Optional[str] = None


class ClientResponse(BaseModel):
    """Schema de resposta com dados do cliente."""
    id: str
    nombre_completo: str
    ci_ruc: str
    telefono: Optional[str]
    celular: Optional[str]
    direccion: str
    manzana: str
    lote: str
    numero_medidor: str
    categoria: ClientCategory
    status: ClientStatus
    # Sponsor
    is_sponsor: bool = False
    # Subsidio / Aluguel (cliente com pagador externo)
    sponsor_id: Optional[str] = None
    subsidio_porcentagem: Optional[int] = None
    is_aluguel: bool = False
    has_sponsor: bool = False
    # GPS e Foto da instalacao
    instalacao_latitude: Optional[float] = None
    instalacao_longitude: Optional[float] = None
    foto_medidor_url: Optional[str] = None
    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ClientSearch(BaseModel):
    """Schema para busca de clientes."""
    query: Optional[str] = None  # Busca em nome, CI/RUC ou medidor
    manzana: Optional[str] = None
    lote: Optional[str] = None
    status: Optional[ClientStatus] = None
    categoria: Optional[ClientCategory] = None
    is_sponsor: Optional[bool] = None  # Filtrar apenas sponsors
    sponsor_id: Optional[str] = None  # Filtrar por sponsor
    is_aluguel: Optional[bool] = None  # Filtrar apenas inquilinos


class ClientWithDebt(ClientResponse):
    """Cliente com informacoes de divida."""
    saldo_pendiente: Decimal = Decimal("0")
    facturas_pendientes: int = 0
