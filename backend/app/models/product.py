"""
Catálogo de produtos/serviços (por org).

Um produto é uma "venda" cadastrada — código, preço e IVA — usada tanto na fatura
manual avulsa quanto na facturación electrónica (FE). A FE exige que o item exista
como produto (não há mais item em texto livre na emissão).
"""

from datetime import datetime
from typing import Optional

from beanie import Indexed
from pydantic import Field

from app.models.types import MongoDecimal

from app.models.base import OrgDocument


class Product(OrgDocument):
    """Produto/serviço faturável."""

    codigo: Indexed(str, unique=True)  # type: ignore[valid-type]
    descripcion: str
    precio_unitario: MongoDecimal
    # Facturación electrónica: IVA por item.
    # iva_afectacion: 1=Gravado, 3=Exento ; iva_tasa: 0/5/10
    iva_tasa: int = 10
    iva_afectacion: int = 1
    unidad: str = "UNI"
    activo: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "products"
        use_state_management = True

    def __repr__(self) -> str:
        return f"Product(codigo={self.codigo}, descripcion={self.descripcion})"
