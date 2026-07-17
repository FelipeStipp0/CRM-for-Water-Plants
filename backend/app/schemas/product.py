"""Schemas Pydantic do catálogo de produtos."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    codigo: Optional[str] = Field(default=None, max_length=40,
                                  description="Se vazio, gera sequencial automático.")
    descripcion: str = Field(min_length=1, max_length=200)
    precio_unitario: Decimal = Field(ge=0)
    iva_tasa: int = Field(default=10)          # 0 / 5 / 10
    iva_afectacion: int = Field(default=1)     # 1=Gravado, 3=Exento
    unidad: str = Field(default="UNI", max_length=10)
    activo: bool = True


class ProductUpdate(BaseModel):
    codigo: Optional[str] = Field(default=None, max_length=40)
    descripcion: Optional[str] = Field(default=None, min_length=1, max_length=200)
    precio_unitario: Optional[Decimal] = Field(default=None, ge=0)
    iva_tasa: Optional[int] = None
    iva_afectacion: Optional[int] = None
    unidad: Optional[str] = Field(default=None, max_length=10)
    activo: Optional[bool] = None


class ProductResponse(BaseModel):
    id: str
    codigo: str
    descripcion: str
    precio_unitario: Decimal
    iva_tasa: int
    iva_afectacion: int
    unidad: str
    activo: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
