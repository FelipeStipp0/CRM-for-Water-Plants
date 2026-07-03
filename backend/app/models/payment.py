"""
Modelo de Pagamento com suporte a distribuicao recursiva.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from beanie import Document, Indexed, Link, PydanticObjectId
from pydantic import Field, BaseModel

from app.models.client import Client
from app.models.types import MongoDecimal


class PaymentMethod(str, Enum):
    """Metodo de pagamento."""
    EFECTIVO = "EFECTIVO"
    TRANSFERENCIA = "TRANSFERENCIA"
    CHEQUE = "CHEQUE"


class PaymentAllocation(BaseModel):
    """
    Alocacao de pagamento em uma fatura especifica.
    Um pagamento pode ser distribuido em multiplas faturas.
    """
    invoice_id: PydanticObjectId
    valor_aplicado: MongoDecimal
    mes_referencia: int
    ano_referencia: int


class Payment(Document):
    """
    Pagamento recebido de um cliente.

    Suporta distribuicao recursiva: um unico pagamento pode quitar
    multiplas faturas, da mais antiga para a mais recente.

    O campo `grupo_pagamento` vincula todas as alocacoes feitas
    numa mesma transacao para fins de recibo.
    """

    client: Link[Client]

    # Valor e metodo
    valor_total: MongoDecimal
    metodo: PaymentMethod = PaymentMethod.EFECTIVO

    # Identificador do grupo (para recibo unico)
    grupo_pagamento: Indexed(str)

    # Numero sequencial legivel do recibo (ex.: 1 -> exibido como "00001").
    numero_recibo: Optional[int] = None

    # Distribuicao do pagamento entre faturas
    allocations: List[PaymentAllocation] = []

    # Quem recebeu
    recibido_por: Optional[str] = None

    # Observacoes
    observacion: Optional[str] = None

    # Datas
    fecha_pago: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "payments"
        use_state_management = True
        indexes = [
            # Filtra por {"client.$id": cid}: índice precisa ser em "client.$id"
            # (não "client", que é o DBRef inteiro e não casa com a query).
            [("client.$id", 1), ("fecha_pago", -1)],
            [("grupo_pagamento", 1)],
            [("numero_recibo", 1)],
        ]

    def __repr__(self) -> str:
        return f"Payment(valor={self.valor_total}, allocations={len(self.allocations)})"

    @property
    def numero_recibo_fmt(self) -> str:
        """Numero do recibo com 5 digitos (ex.: '00001'). '-' se ausente."""
        return f"{self.numero_recibo:05d}" if self.numero_recibo is not None else "-"

    @property
    def invoices_affected(self) -> List[PydanticObjectId]:
        """Lista de IDs das faturas afetadas por este pagamento."""
        return [alloc.invoice_id for alloc in self.allocations]
