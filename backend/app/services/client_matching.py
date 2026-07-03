"""
Servico de matching de clientes por identificadores.

Move a logica de matching que hoje existe apenas no frontend
(readings_view.py excel import) para o backend.
"""

import re
from typing import Optional, List

from app.models.client import Client, ClientStatus


def normalize_identifier(value: str) -> str:
    """Normaliza identificador removendo caracteres nao alfanumericos."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def normalize_name(value: str) -> str:
    """Normaliza nome para matching: lowercase, colapsa espacos."""
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


class ClientMatchingService:
    """
    Matching de clientes por identificadores com prioridade configuravel.

    Estrategia: pre-carrega todos os clientes ativos em dicionarios de lookup,
    depois faz matching O(1) por item.
    """

    def __init__(
        self,
        clients: List[Client],
        prioridade: Optional[List[str]] = None,
    ):
        self.prioridade = prioridade or [
            "numero_medidor", "ci_ruc", "nombre_completo"
        ]

        self.by_meter: dict[str, Client] = {}
        self.by_doc: dict[str, Client] = {}
        self.by_name: dict[str, Client] = {}

        for client in clients:
            meter_key = normalize_identifier(client.numero_medidor)
            if meter_key:
                self.by_meter[meter_key] = client

            doc_key = normalize_identifier(client.ci_ruc)
            if doc_key:
                self.by_doc[doc_key] = client

            name_key = normalize_name(client.nombre_completo)
            if name_key and name_key not in self.by_name:
                self.by_name[name_key] = client

    def match(
        self,
        numero_medidor: Optional[str] = None,
        ci_ruc: Optional[str] = None,
        nombre: Optional[str] = None,
    ) -> Optional[Client]:
        """
        Tenta encontrar cliente seguindo a lista de prioridade.
        Retorna o Client encontrado ou None.
        """
        lookup_map = {
            "numero_medidor": (numero_medidor, self.by_meter, normalize_identifier),
            "ci_ruc": (ci_ruc, self.by_doc, normalize_identifier),
            "nombre_completo": (nombre, self.by_name, normalize_name),
        }

        for field_name in self.prioridade:
            if field_name not in lookup_map:
                continue
            raw_value, lookup, normalizer = lookup_map[field_name]
            if not raw_value:
                continue
            key = normalizer(raw_value)
            if key and key in lookup:
                return lookup[key]

        return None

    @classmethod
    async def create(
        cls,
        prioridade: Optional[List[str]] = None,
    ) -> "ClientMatchingService":
        """Factory: carrega todos clientes ativos e constroi o matcher."""
        clients = await Client.find(
            Client.status == ClientStatus.ATIVO
        ).to_list()
        return cls(clients=clients, prioridade=prioridade)
