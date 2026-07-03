"""
Modelo do Workflow de Corte.

Rastreia o processo completo de corte de servico:
EM_LISTA -> EM_AVISO -> EM_CONTAGEM -> PRONTO_PARA_CORTE -> CORTADO

Cada etapa pode ser confirmada via QR Code (entregador/tecnico)
ou manualmente pelo operador no sistema.
"""

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, Link, PydanticObjectId
from pydantic import Field

from app.models.client import Client
from app.models.types import MongoDecimal


class CutoffStatus(str, Enum):
    """Estado do workflow de corte."""
    EM_LISTA = "EM_LISTA"
    EM_AVISO = "EM_AVISO"
    EM_CONTAGEM = "EM_CONTAGEM"
    PRONTO_PARA_CORTE = "PRONTO_PARA_CORTE"
    CORTADO = "CORTADO"


class CutoffActionType(str, Enum):
    """Tipo de acao confirmavel por QR Code."""
    ENTREGA_AVISO = "ENTREGA_AVISO"
    EXECUCAO_CORTE = "EXECUCAO_CORTE"
    CONFIRMACAO_REATIVACAO = "CONFIRMACAO_REATIVACAO"


class CutoffNotice(Document):
    """
    Registro de aviso de corte e rastreamento do workflow.

    Um cliente tem apenas um CutoffNotice ativo por vez.
    Quando cliente paga toda divida, o registro e marcado como saiu_por_pagamento.
    """

    client: Link[Client]

    status: CutoffStatus = CutoffStatus.EM_LISTA

    # Snapshot no momento de entrar no workflow
    divida_original: MongoDecimal
    meses_atraso: int

    # ========== QR TOKENS ==========
    qr_token_entrega: Optional[str] = None
    qr_token_corte: Optional[str] = None
    qr_token_reativacao: Optional[str] = None

    # ========== AVISO ==========
    fecha_aviso_gerado: Optional[datetime] = None
    fecha_entrega_aviso: Optional[datetime] = None
    aviso_entregue_por: Optional[str] = None
    observacion_aviso: Optional[str] = None

    # ========== COUNTDOWN ==========
    fecha_limite_pago: Optional[date] = None

    # ========== CORTE ==========
    fecha_corte: Optional[datetime] = None
    cortado_por: Optional[str] = None
    observacion_corte: Optional[str] = None

    # ========== FOTOS/GPS CORTE ==========
    foto_instalacao_url: Optional[str] = None
    gps_corte_latitude: Optional[float] = None
    gps_corte_longitude: Optional[float] = None

    # ========== AUTO-EXIT ==========
    saiu_por_pagamento: bool = False
    fecha_saida: Optional[datetime] = None

    # ========== REATIVACAO ==========
    reativacao_solicitada: bool = False
    fecha_solicitud_reativacao: Optional[datetime] = None
    taxa_reativacao_paga: bool = False
    fecha_reativacao: Optional[datetime] = None
    reativacao_confirmada_por: Optional[str] = None

    # ========== FOTOS/GPS REATIVACAO ==========
    foto_reativacao_url: Optional[str] = None
    gps_reativacao_latitude: Optional[float] = None
    gps_reativacao_longitude: Optional[float] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "cutoff_notices"
        use_state_management = True
        indexes = [
            [("client.$id", 1)],
            [("status", 1), ("created_at", -1)],
            [("saiu_por_pagamento", 1), ("status", 1)],
            [("qr_token_entrega", 1)],
            [("qr_token_corte", 1)],
            [("qr_token_reativacao", 1)],
        ]

    def __repr__(self) -> str:
        return f"CutoffNotice(client={self.client}, status={self.status})"
