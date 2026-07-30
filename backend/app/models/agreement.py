"""
Acordo de pagamento (parcelamento da dívida no balcão).

Ao fechar o acordo, as faturas antigas escolhidas viram ANULADA com o
`saldo_devedor` zerado e ficam vinculadas aqui: o cliente sai da dívida e do
fluxo de corte na hora, e a dívida passa a viver nas `parcelas` — um valor fixo
já agendado para o futuro, que a geração mensal soma na fatura de consumo do mês
correspondente (campo `cuota_valor` da Invoice).

Por que anular as originais funciona: as consultas de dívida contam só faturas
com `saldo_devedor > 0` e status diferente de ANULADA, então a dívida não é
contada duas vezes e o corte não pega quem está em dia. E não há efeito fiscal:
a fatura interna não é um DTE — a factura legal é emitida no *pagamento*, pela
caja.

Regra: **um acordo ATIVO por cliente**. Dívida nova durante o acordo refaz o
acordo (o antigo vira REFEITO e aponta para o novo em `replaced_by`).
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from beanie import Link, PydanticObjectId
from pydantic import BaseModel, Field

from app.models.base import OrgDocument
from app.models.client import Client
from app.models.types import MongoDecimal


class AgreementStatus(str, Enum):
    ACTIVO = "ACTIVO"      # parcelas em andamento
    QUITADO = "QUITADO"    # todas as parcelas pagas
    REFEITO = "REFEITO"    # substituído por um acordo novo (dívida nova entrou)
    CANCELADO = "CANCELADO"  # desfeito (as faturas antigas voltaram)


class CuotaStatus(str, Enum):
    PENDIENTE = "PENDIENTE"    # agendada, o mês ainda não foi faturado
    FACTURADA = "FACTURADA"    # entrou na fatura do mês (invoice_id preenchido)
    PAGADA = "PAGADA"          # a fatura que a carrega foi quitada
    CANCELADA = "CANCELADA"    # o acordo foi refeito/cancelado antes de faturar


class AgreementCuota(BaseModel):
    """Uma parcela agendada."""
    numero: int                      # 1..n
    mes: int = Field(ge=1, le=12)
    ano: int
    valor: MongoDecimal
    status: CuotaStatus = CuotaStatus.PENDIENTE
    invoice_id: Optional[PydanticObjectId] = None   # fatura do mês que a carrega
    facturada_at: Optional[datetime] = None
    pagada_at: Optional[datetime] = None


class AgreementInvoiceSnapshot(BaseModel):
    """
    Retrato de uma fatura antiga anulada pelo acordo.

    Guardado no acordo porque é o que se imprime junto do recibo da última
    parcela, como comprovante de que aquela dívida acabou — e porque o valor
    original não pode mudar depois (a fatura fica com saldo zerado).
    """
    invoice_id: PydanticObjectId
    numero_factura: Optional[int] = None
    tipo: Optional[str] = None
    mes_referencia: int
    ano_referencia: int
    valor_total: MongoDecimal
    saldo_incorporado: MongoDecimal   # o que dessa fatura entrou no acordo


class PaymentAgreement(OrgDocument):
    """Acordo de parcelamento de um cliente."""

    numero: int                      # sequencial legível (Counter "agreement")
    client: Link[Client]
    status: AgreementStatus = AgreementStatus.ACTIVO

    # Dinheiro. total_deuda = soma exata dos saldos das faturas anuladas.
    # Sem juros, multa ou ajuste: total_parcelado = total_deuda − entrada.
    total_deuda: MongoDecimal
    entrada: MongoDecimal = Decimal("0")
    total_parcelado: MongoDecimal
    n_parcelas: int = Field(ge=1)

    # IVA da cuota — escolhido pelo cajero em cada acordo (não vem das
    # configurações: a parcela não é consumo de água).
    cuota_iva_tasa: int = 10
    cuota_iva_afectacion: int = 1

    parcelas: List[AgreementCuota] = []
    facturas_anuladas: List[AgreementInvoiceSnapshot] = []

    # Pagamento da entrada (recibo), quando houve entrada.
    entrada_payment_id: Optional[PydanticObjectId] = None

    # Encadeamento quando o acordo é refeito.
    replaces_id: Optional[PydanticObjectId] = None
    replaced_by_id: Optional[PydanticObjectId] = None

    creado_por: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    observacion: Optional[str] = None

    class Settings:
        name = "payment_agreements"
        indexes = [
            [("client.$id", 1), ("status", 1)],
            [("numero", -1)],
            [("status", 1), ("created_at", -1)],
        ]

    @property
    def numero_fmt(self) -> str:
        return f"{self.numero:04d}"

    @property
    def saldo_pendiente(self) -> Decimal:
        """Quanto do acordo ainda não foi pago (parcelas não PAGADAS)."""
        return sum(
            (c.valor for c in self.parcelas if c.status != CuotaStatus.PAGADA),
            Decimal("0"),
        )

    def __repr__(self) -> str:
        return (f"PaymentAgreement({self.numero_fmt} {self.status.value} "
                f"{self.n_parcelas}x {self.total_parcelado})")
