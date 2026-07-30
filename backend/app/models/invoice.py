"""
Modelo de Fatura.
Suporta faturas de consumo (leituras) e faturas avulsas (itens genericos).
"""

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from beanie import Indexed, Link, PydanticObjectId
from pymongo import IndexModel, ASCENDING, ReturnDocument
from pydantic import Field, BaseModel

from app.models.client import Client
from app.models.types import MongoDecimal

from app.models.base import OrgDocument


class Counter(OrgDocument):
    """Contadores sequenciais atomicos para numeracao."""
    name: str
    seq: int = 0

    class Settings:
        name = "counters"

    @classmethod
    async def get_next(cls, name: str) -> int:
        """Incrementa e retorna o proximo valor atomicamente."""
        collection = cls.get_pymongo_collection()
        result = await collection.find_one_and_update(
            {"name": name},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return result["seq"]


class InvoiceStatus(str, Enum):
    """Status da fatura."""
    PENDENTE = "PENDENTE"
    PAGADA = "PAGADA"
    PARCIAL = "PARCIAL"  # Pagamento parcial
    ANULADA = "ANULADA"


class InvoiceType(str, Enum):
    """Tipo de fatura."""
    CONSUMO = "CONSUMO"  # Gerada a partir de leitura
    AVULSA = "AVULSA"    # Criada manualmente com itens


class InvoiceItem(BaseModel):
    """
    Item de uma fatura avulsa.
    Permite cobrar produtos/servicos arbitrarios.
    """
    descripcion: str
    cantidad: int = 1
    precio_unitario: MongoDecimal

    # Facturación electrónica: IVA por item (AVULSA).
    # afectacion: 1=Gravado, 2=Parcial, 3=Exento ; tasa: 0/5/10
    iva_afectacion: int = 1
    iva_tasa: int = 10

    @property
    def subtotal(self) -> Decimal:
        return Decimal(self.cantidad) * self.precio_unitario


class Invoice(OrgDocument):
    """
    Fatura do cliente.

    IMPORTANTE (Visualizacao Hibrida):
    - No banco: cada fatura representa APENAS o mes de referencia (clean)
    - Na visualizacao/PDF: o frontend calcula e mostra "Saldo Pendente Anterior"
    """

    client: Link[Client]

    # Tipo e status
    tipo: InvoiceType = InvoiceType.CONSUMO
    status: InvoiceStatus = InvoiceStatus.PENDENTE

    # Periodo de referencia
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int

    # Datas
    fecha_emision: datetime = Field(default_factory=datetime.utcnow)
    fecha_vencimiento: date

    # Valores para fatura de CONSUMO
    leitura_anterior: Optional[int] = None
    leitura_actual: Optional[int] = None
    consumo: Optional[int] = None
    tarifa_base: Optional[MongoDecimal] = None
    excedente: Optional[MongoDecimal] = None

    # Itens para fatura AVULSA
    items: List[InvoiceItem] = []

    # Totais
    valor_total: MongoDecimal  # Valor original da fatura
    saldo_devedor: MongoDecimal  # Valor ainda em aberto (atualizado com pagamentos)

    # Numero sequencial unico da fatura
    numero_factura: Optional[int] = None

    # ---- Cuota de acordo de pagamento (parcelamento) ----
    # A parcela NAO reaproveita `items` (que sao so de AVULSA) nem o IVA global das
    # configuracoes: ela tem valor, tasa e afetacao proprios, escolhidos ao fechar o
    # acordo. `valor_total`/`saldo_devedor` desta fatura JA incluem `cuota_valor` —
    # o campo existe para a factura legal poder separar "cuota" de "agua" e para o
    # balcao poder dizer ao cliente o que esta cobrando.
    cuota_valor: Optional[MongoDecimal] = None
    cuota_iva_tasa: Optional[int] = None
    cuota_iva_afectacion: Optional[int] = None
    cuota_numero: Optional[int] = None                      # 3 de 6, por exemplo
    agreement_id: Optional[PydanticObjectId] = None         # acordo que gerou a cuota

    # Acordo que ANULOU esta fatura (a divida velha virou parcelas).
    anulada_por_acuerdo_id: Optional[PydanticObjectId] = None

    # Referencia a leitura que gerou esta fatura (se tipo=CONSUMO)
    reading_id: Optional[PydanticObjectId] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "invoices"
        use_state_management = True
        indexes = [
            # As queries filtram por {"client.$id": cid} (o ObjectId dentro do DBRef),
            # então o índice precisa ser em "client.$id" — um índice em "client"
            # (DBRef inteiro) NÃO é usado e gera collection scan. Ver payments/cutoff.
            [("client.$id", 1), ("status", 1)],
            [("client.$id", 1), ("ano_referencia", -1), ("mes_referencia", -1)],
            [("status", 1), ("fecha_vencimiento", 1)],
            [("fecha_emision", -1)],
            [("agreement_id", 1)],
            [("anulada_por_acuerdo_id", 1)],
            IndexModel(
                [("numero_factura", ASCENDING)],
                unique=True,
                partialFilterExpression={"numero_factura": {"$type": "int"}},
            ),
        ]

    def __repr__(self) -> str:
        return f"Invoice(ref={self.mes_referencia}/{self.ano_referencia}, valor={self.valor_total}, status={self.status})"

    @property
    def is_paid(self) -> bool:
        """Verifica se a fatura esta totalmente paga."""
        return self.saldo_devedor <= 0
