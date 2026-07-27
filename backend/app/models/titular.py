"""
Titular: a PESSOA por trás de uma ou mais ligações de água.

Numa junta o mesmo dono costuma ter várias ligações — casas na mesma manzana,
imóveis de aluguel, um comércio e a residência. Cada ligação continua sendo um
`Client` próprio, porque é ela que tem medidor, leitura, fatura e corte. O que o
Titular acrescenta é o agrupamento: dado de contato num lugar só e a resposta
para "quais casas são desta pessoa?".

Não confundir com o RECEPTOR da factura: quem paga pode ser o inquilino, não o
titular. A emissão continua olhando o `Client`.
"""

from datetime import datetime
from typing import Optional

from beanie import Indexed
from pydantic import Field

from app.models.base import OrgDocument


class Titular(OrgDocument):
    nombre_completo: str
    # Indexado para busca, NAO unico: quem não tem documento válido entra com o
    # RUC de cliente ocasional (44444401-7), que por definição se repete entre
    # pessoas diferentes.
    ci_ruc: Indexed(str)
    es_contribuyente: Optional[bool] = None

    telefono: Optional[str] = None
    celular: Optional[str] = None
    email: Optional[str] = None

    observaciones: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "titulares"
        use_state_management = True
        indexes = [
            [("nombre_completo", 1)],
        ]

    def __repr__(self) -> str:
        return f"Titular(nombre={self.nombre_completo}, doc={self.ci_ruc})"
