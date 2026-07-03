"""
Schemas para workflow de corte.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field

from app.models.cutoff import CutoffStatus, CutoffActionType


class CutoffCandidateResponse(BaseModel):
    """Cliente candidato a corte."""
    client_id: str
    nombre_completo: str
    ci_ruc: str
    manzana: str
    lote: str
    divida_total: Decimal
    meses_atraso: int
    oldest_invoice_date: date


class CutoffNoticeCreate(BaseModel):
    """Adicionar cliente a lista de corte."""
    client_id: str


class RegisterDeliveryRequest(BaseModel):
    """Registrar entrega manual do aviso."""
    entregue_por: Optional[str] = None
    observacion: Optional[str] = None


class ExecuteCutoffRequest(BaseModel):
    """Executar corte manual."""
    cortado_por: Optional[str] = None
    observacion: Optional[str] = None
    # Foto e GPS (app mobile)
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class QrConfirmRequest(BaseModel):
    """Confirmacao via QR Code scan."""
    nome_responsavel: str = Field(min_length=2)
    observacion: Optional[str] = None
    # Foto e GPS (app mobile)
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class RequestReactivationRequest(BaseModel):
    """Solicitar reativacao."""
    client_id: str
    valor_pago: Decimal = Field(gt=0)


class ConfirmReactivationRequest(BaseModel):
    """Confirmar reativacao manual."""
    confirmado_por: Optional[str] = None
    # Foto e GPS (app mobile)
    foto_url: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class CutoffActionResponse(BaseModel):
    """Resposta de acao no workflow."""
    success: bool
    cutoff_notice_id: Optional[str] = None
    message: Optional[str] = None


class QrTokenInfo(BaseModel):
    """Info do QR token gerado (para embutir no PDF)."""
    qr_token: str
    action_type: CutoffActionType
    cutoff_notice_id: str
    # Dados de pagamento (preenchidos na solicitação de reativação)
    comprobante: Optional[str] = None
    fecha_pago: Optional[datetime] = None


class CutoffNoticeResponse(BaseModel):
    """Resposta com dados do aviso de corte."""
    id: str
    client_id: str
    status: CutoffStatus
    divida_original: Decimal
    meses_atraso: int

    # QR tokens ativos
    has_qr_entrega: bool = False
    has_qr_corte: bool = False
    has_qr_reativacao: bool = False

    # Aviso
    fecha_aviso_gerado: Optional[datetime] = None
    fecha_entrega_aviso: Optional[datetime] = None
    aviso_entregue_por: Optional[str] = None
    observacion_aviso: Optional[str] = None

    # Countdown
    fecha_limite_pago: Optional[date] = None

    # Corte
    fecha_corte: Optional[datetime] = None
    cortado_por: Optional[str] = None
    observacion_corte: Optional[str] = None

    # Fotos/GPS Corte
    foto_instalacao_url: Optional[str] = None
    gps_corte_latitude: Optional[float] = None
    gps_corte_longitude: Optional[float] = None

    # Auto-exit
    saiu_por_pagamento: bool = False
    fecha_saida: Optional[datetime] = None

    # Reativacao
    reativacao_solicitada: bool = False
    fecha_solicitud_reativacao: Optional[datetime] = None
    taxa_reativacao_paga: bool = False
    fecha_reativacao: Optional[datetime] = None
    reativacao_confirmada_por: Optional[str] = None

    # Fotos/GPS Reativacao
    foto_reativacao_url: Optional[str] = None
    gps_reativacao_latitude: Optional[float] = None
    gps_reativacao_longitude: Optional[float] = None

    # Metadata
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CutoffNoticeDetail(CutoffNoticeResponse):
    """Aviso com dados do cliente incluidos."""
    client_nombre: str
    client_ci_ruc: str
    client_telefono: Optional[str] = None
    client_direccion: str
    client_manzana: str
    client_lote: str
    divida_atual: Decimal = Decimal("0")


class QrInfoResponse(BaseModel):
    """Info retornada pelo endpoint publico de QR."""
    notice_id: str
    action_type: str
    already_done: bool
    client_nombre: str
    client_ci_ruc: str
    client_direccion: str
    client_manzana: str
    client_lote: str
    status: str
    divida_original: str
