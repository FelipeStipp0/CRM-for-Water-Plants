"""
Schemas para pagamentos.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.payment import PaymentMethod


class PaymentCreate(BaseModel):
    """
    Schema para criacao de pagamento.
    O valor sera distribuido automaticamente entre as faturas pendentes.

    IMPORTANTE para Frontend:
    - aplicar_subsidio: checkbox na UI. Se True e cliente tem sponsor,
      cria SponsorDebt. Se False, ignora o sponsor mesmo que exista.
    """
    client_id: str
    valor_total: Decimal = Field(gt=0)
    metodo: PaymentMethod = PaymentMethod.EFECTIVO
    aplicar_subsidio: bool = True  # False = ignora sponsor neste pagamento
    recibido_por: Optional[str] = None
    observacion: Optional[str] = None


class AllocationDetail(BaseModel):
    """Detalhe de alocacao em uma fatura."""
    invoice_id: str
    mes_referencia: int
    ano_referencia: int
    valor_original: Decimal
    saldo_anterior: Decimal
    valor_aplicado: Decimal
    saldo_restante: Decimal
    status_final: str  # PAGADA ou PARCIAL
    # Subsidio (se aplicado)
    subsidio_transferido: Optional[Decimal] = None
    sponsor_debt_id: Optional[str] = None


class PaymentResponse(BaseModel):
    """Schema de resposta com dados do pagamento."""
    id: str
    client_id: str
    valor_total: Decimal
    metodo: PaymentMethod
    grupo_pagamento: str
    numero_recibo: Optional[int] = None
    recibido_por: Optional[str]
    observacion: Optional[str]
    fecha_pago: datetime
    allocations: List[AllocationDetail] = []

    class Config:
        from_attributes = True


class PaymentResult(BaseModel):
    """
    Resultado completo de um pagamento (para impressao).
    Inclui o recibo e as faturas afetadas.
    """
    payment: PaymentResponse
    client_name: str
    client_ci_ruc: str
    invoices_affected: List[AllocationDetail]
    total_debt_before: Decimal
    total_debt_after: Decimal
    overpayment: Decimal = Decimal("0")  # Se pagou mais que devia
    # Subsidio
    subsidio_aplicado: bool = False
    total_subsidio: Decimal = Decimal("0")
    sponsor_name: Optional[str] = None
    # Reativacao automatica disparada por este pagamento (cliente estava CORTADO)
    reactivation_notice_id: Optional[str] = None
    reactivation_qr_token: Optional[str] = None
    reactivation_comprobante: Optional[str] = None


class PaymentHistory(BaseModel):
    """Historico de pagamento para listagens."""
    id: str
    client_id: str
    client_name: str
    valor_total: Decimal
    metodo: PaymentMethod
    fecha_pago: datetime
    invoices_count: int
