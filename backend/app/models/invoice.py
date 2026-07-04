"""
Modelo de Fatura.
Suporta faturas de consumo (leituras) e faturas avulsas (itens genericos).
"""

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from beanie import Document, Indexed, Link, PydanticObjectId
from pymongo import IndexModel, ASCENDING, ReturnDocument
from pydantic import Field, BaseModel

from app.models.client import Client
from app.models.types import MongoDecimal


class Counter(Document):
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


class Invoice(Document):
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
