"""
Trilha de auditoria: registra ações sensíveis (quem/quando/antes→depois).

Escopo inicial: anulação de pagamento. Genérico o bastante para cobrir depois
alterações de tarifa, anulação de fatura, edição de dados fiscais, etc.
"""

from datetime import datetime
from typing import Optional

from beanie import Indexed
from pydantic import Field

from app.models.base import OrgDocument


class AuditLog(OrgDocument):
    action: Indexed(str)              # ex.: "payment.anular"
    entity_type: str                 # ex.: "payment"
    entity_id: Optional[str] = None
    entity_label: Optional[str] = None  # ex.: "Recibo 00042"
    usuario: str                     # username de quem fez
    motivo: Optional[str] = None
    before: Optional[dict] = None    # estado relevante antes
    after: Optional[dict] = None     # estado relevante depois
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "audit_logs"
        indexes = [
            [("created_at", -1)],
            [("entity_type", 1), ("entity_id", 1)],
            [("action", 1)],
        ]
