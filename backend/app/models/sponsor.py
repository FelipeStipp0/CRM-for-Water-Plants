"""
Modelo de Divida de Sponsor (Subsidio).

Quando um cliente com sponsor paga sua fatura:
1. Cliente paga (Total - Subsidio)
2. O valor do subsidio vira uma divida do Sponsor
3. Mensalmente, gera-se uma fatura agregada para o Sponsor
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from beanie import Document, Indexed, Link, PydanticObjectId
from pydantic import Field, BaseModel

from app.models.client import Client
from app.models.types import MongoDecimal


class SponsorDebtStatus(str, Enum):
    """Status da divida do sponsor."""
    PENDENTE = "PENDENTE"  # Aguardando cobranca
    FATURADO = "FATURADO"  # Incluido em fatura agregada
    PAGO = "PAGO"


class SponsorDebt(Document):
    """
    Registro de divida transferida para um Sponsor.
    Cada vez que um cliente subsidiado paga, um registro deste e criado.
    """

    # Sponsor que deve pagar
    sponsor: Link[Client]

    # Cliente original que foi subsidiado
    client_original: Link[Client]

    # Fatura original que gerou este subsidio
    invoice_id: PydanticObjectId
    mes_referencia: int
    ano_referencia: int

    # Valores
    valor_subsidio: MongoDecimal  # Valor que o sponsor deve pagar
    porcentagem_aplicada: int  # % que foi aplicada

    # Pagamento que originou esta divida
    payment_id: PydanticObjectId

    status: SponsorDebtStatus = SponsorDebtStatus.PENDENTE

    # Se faturado, referencia a fatura agregada
    fatura_agregada_id: Optional[PydanticObjectId] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "sponsor_debts"
        indexes = [
            [("sponsor", 1), ("status", 1)],
            [("client_original", 1)],
            [("fatura_agregada_id", 1)],
        ]

    def __repr__(self) -> str:
        return f"SponsorDebt(valor={self.valor_subsidio}, status={self.status})"


class SponsorInvoice(Document):
    """
    Fatura agregada do Sponsor.
    Consolida todas as dividas de subsidio de um periodo.
    """

    sponsor: Link[Client]

    # Periodo de referencia
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int

    # Lista de dividas incluidas
    debts_included: List[PydanticObjectId] = []

    # Totais
    valor_total: MongoDecimal
    saldo_devedor: MongoDecimal

    # Status
    status: str = "PENDENTE"  # PENDENTE, PAGADA

    # Datas
    fecha_emision: datetime = Field(default_factory=datetime.utcnow)
    fecha_pago: Optional[datetime] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "sponsor_invoices"
        indexes = [
            [("sponsor", 1), ("ano_referencia", -1), ("mes_referencia", -1)],
            [("status", 1)],
        ]

    def __repr__(self) -> str:
        return f"SponsorInvoice(ref={self.mes_referencia}/{self.ano_referencia}, valor={self.valor_total})"
