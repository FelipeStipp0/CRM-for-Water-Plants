"""
Schemas para faturas.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.invoice import InvoiceStatus, InvoiceType


class InvoiceItemCreate(BaseModel):
    """Item para fatura avulsa."""
    descripcion: str = Field(min_length=1, max_length=200)
    cantidad: int = Field(ge=1, default=1)
    precio_unitario: Decimal = Field(ge=0)


class InvoiceCreate(BaseModel):
    """
    Schema para criacao de fatura.
    Para CONSUMO: passa client_id e reading_id
    Para AVULSA: passa client_id e items
    """
    client_id: str
    tipo: InvoiceType = InvoiceType.AVULSA
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int = Field(ge=2000, le=2100)
    fecha_vencimiento: Optional[date] = None  # Se nao informado, usa padrao

    # Para faturas avulsas
    items: List[InvoiceItemCreate] = []

    # Para faturas de consumo (opcional, pode ser preenchido automaticamente)
    reading_id: Optional[str] = None


class InvoiceItemResponse(BaseModel):
    """Item de fatura na resposta."""
    descripcion: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal


class InvoiceResponse(BaseModel):
    """Schema de resposta com dados da fatura."""
    id: str
    client_id: str
    client_nombre: Optional[str] = None
    numero_factura: Optional[int] = None
    tipo: InvoiceType
    status: InvoiceStatus
    mes_referencia: int
    ano_referencia: int
    fecha_emision: datetime
    fecha_vencimiento: date

    # Dados de consumo (se aplicavel)
    leitura_anterior: Optional[int]
    leitura_actual: Optional[int]
    consumo: Optional[int]
    tarifa_base: Optional[Decimal]
    excedente: Optional[Decimal]

    # Itens (se fatura avulsa)
    items: List[InvoiceItemResponse] = []

    # Totais
    valor_total: Decimal
    saldo_devedor: Decimal

    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceSummary(BaseModel):
    """Resumo de fatura para listagens."""
    id: str
    client_id: Optional[str] = None
    client_nombre: Optional[str] = None
    numero_factura: Optional[int] = None
    mes_referencia: int
    ano_referencia: int
    tipo: InvoiceType
    status: InvoiceStatus
    valor_total: Decimal
    saldo_devedor: Decimal
    fecha_vencimiento: date


class InvoiceWithPendingBalance(InvoiceResponse):
    """
    Fatura com saldo pendente anterior (para visualizacao/PDF).
    O saldo_pendiente_anterior e calculado somando todas as faturas
    pendentes anteriores a esta.
    """
    saldo_pendiente_anterior: Decimal = Decimal("0")
    total_a_pagar: Decimal = Decimal("0")  # valor_total + saldo_pendiente_anterior


class GenerateInvoicesRequest(BaseModel):
    """Request para geracao de faturas em lote."""
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int = Field(ge=2000, le=2100)
    client_ids: Optional[List[str]] = None  # Se None, gera para todos
    gerar_sem_leitura_valor_minimo: bool = False
    dia_geracao: Optional[int] = Field(None, ge=1, le=28)


class GenerateInvoicesResponse(BaseModel):
    """Resposta da geracao em lote."""
    total_generated: int
    total_skipped: int
    total_minimum_generated: int = 0
    total_minimum_skipped: int = 0
    errors: List[str] = []
