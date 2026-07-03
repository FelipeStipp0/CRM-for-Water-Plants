"""
Schemas para Sponsor/Subsidio.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field


class SponsorDebtResponse(BaseModel):
    """Resposta de uma divida individual do sponsor."""
    id: str
    sponsor_id: str
    client_original_id: str
    client_original_name: Optional[str] = None
    invoice_id: str
    mes_referencia: int
    ano_referencia: int
    valor_subsidio: Decimal
    porcentagem_aplicada: int
    payment_id: str
    status: str
    fatura_agregada_id: Optional[str] = None
    created_at: datetime


class SponsorSummaryResponse(BaseModel):
    """Resumo financeiro do sponsor."""
    sponsor_id: str
    sponsor_name: str
    total_pendente: Decimal
    total_faturado: Decimal
    total_pago: Decimal
    count_debts: int


class SponsorInvoiceResponse(BaseModel):
    """Resposta de fatura agregada do sponsor."""
    id: str
    sponsor_id: str
    mes_referencia: int
    ano_referencia: int
    debts_included: List[str]
    valor_total: Decimal
    saldo_devedor: Decimal
    status: str
    fecha_emision: datetime
    fecha_pago: Optional[datetime] = None


class GenerateInvoiceRequest(BaseModel):
    """Request para gerar fatura agregada."""
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int = Field(ge=2020)


class PaySponsorInvoiceRequest(BaseModel):
    """Request para pagar fatura do sponsor."""
    valor: Decimal = Field(gt=0)
    recibido_por: Optional[str] = None
