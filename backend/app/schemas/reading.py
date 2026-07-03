"""
Schemas para leituras.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator


class ReadingCreate(BaseModel):
    """Schema para criacao de leitura individual."""
    client_id: str
    valor_leitura: int = Field(ge=0)
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int = Field(ge=2000, le=2100)
    referencia: Optional[str] = None
    observacion: Optional[str] = None
    # Foto e GPS (app mobile)
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class ReadingBatchItem(BaseModel):
    """Item de leitura em lote."""
    client_id: Optional[str] = None
    valor_leitura: int = Field(ge=0)
    referencia: Optional[str] = None
    observacion: Optional[str] = None
    # Foto e GPS (app mobile)
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    # Identificadores para matching (quando client_id nao informado)
    numero_medidor: Optional[str] = None
    ci_ruc: Optional[str] = None
    nombre: Optional[str] = None

    @model_validator(mode='after')
    def check_identifier(self):
        if not self.client_id and not self.numero_medidor and not self.ci_ruc and not self.nombre:
            raise ValueError(
                "Deve informar client_id ou pelo menos um identificador "
                "(numero_medidor, ci_ruc, nombre)"
            )
        return self


MATCHING_FIELDS_ALLOWED = {"numero_medidor", "ci_ruc", "nombre_completo"}


class ReadingBatch(BaseModel):
    """Schema para insercao de leituras em lote."""
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int = Field(ge=2000, le=2100)
    readings: List[ReadingBatchItem]
    matching_prioridade: Optional[List[str]] = None

    @model_validator(mode='after')
    def validate_matching_prioridade(self):
        if self.matching_prioridade is not None:
            invalid = [f for f in self.matching_prioridade if f not in MATCHING_FIELDS_ALLOWED]
            if invalid:
                raise ValueError(
                    f"matching_prioridade invalido: {invalid}. "
                    f"Valores permitidos: {sorted(MATCHING_FIELDS_ALLOWED)}"
                )
        return self


class ReadingResponse(BaseModel):
    """Schema de resposta com dados da leitura."""
    id: str
    client_id: str
    valor_leitura: int
    mes_referencia: int
    ano_referencia: int
    consumo_calculado: Optional[int]
    referencia: Optional[str]
    observacion: Optional[str]
    fecha_lectura: datetime
    created_at: datetime
    # Foto e GPS
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    gps_timestamp: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReadingWithClient(ReadingResponse):
    """Leitura com dados basicos do cliente."""
    cliente_nombre: str
    cliente_medidor: str
    cliente_manzana: str
    cliente_lote: str
