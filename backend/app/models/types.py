"""
Tipos customizados para modelos MongoDB/Pydantic.
"""

from decimal import Decimal
from typing import Annotated, Any
from pydantic import BeforeValidator


def convert_decimal(v: Any) -> Decimal:
    """Converte Decimal128 do MongoDB para Decimal Python."""
    if v is None:
        return None
    if hasattr(v, 'to_decimal'):  # Decimal128
        return v.to_decimal()
    return Decimal(str(v))


# Tipo customizado para Decimal que suporta Decimal128 do MongoDB
MongoDecimal = Annotated[Decimal, BeforeValidator(convert_decimal)]
