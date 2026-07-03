"""
Modelo de Leitura de consumo do medidor.
"""

from datetime import datetime
from typing import Optional
from beanie import Document, Indexed, Link
from pydantic import Field

from app.models.client import Client


class Reading(Document):
    """
    Leitura do medidor de um cliente.
    Cada leitura representa o valor do medidor em uma data especifica.
    O consumo e calculado como: leitura_atual - leitura_anterior.
    """

    client: Link[Client]

    # Valor lido no medidor
    valor_leitura: int

    # Periodo de referencia (mes/ano)
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int

    # Data da leitura
    fecha_lectura: datetime = Field(default_factory=datetime.utcnow)

    # Consumo calculado (preenchido automaticamente)
    consumo_calculado: Optional[int] = None

    # Referencia e observacoes
    referencia: Optional[str] = None
    observacion: Optional[str] = None

    # Foto e GPS (capturados pelo app mobile)
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    gps_timestamp: Optional[datetime] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "readings"
        use_state_management = True
        indexes = [
            # Filtra por {"client.$id": ...} — índice em "client.$id", não no DBRef.
            [("client.$id", 1), ("ano_referencia", -1), ("mes_referencia", -1)],
        ]

    def __repr__(self) -> str:
        return f"Reading(valor={self.valor_leitura}, ref={self.mes_referencia}/{self.ano_referencia})"
