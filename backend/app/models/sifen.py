"""
Modelos da facturación electrónica (SIFEN/DNIT).

Infra genérica de emissão de documentos eletrônicos: registro de emissão (com
idempotência), lock de sessão único por RUC e credenciais cifradas. NÃO contém
nada específico do portal — a comunicação real fica atrás da interface de provider
(services/sifen/provider.py), cujo adapter concreto é injetado à parte.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List

from beanie import Document, Link, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, ASCENDING

from app.models.client import Client


class EmissionStatus(str, Enum):
    PENDENTE = "PENDENTE"        # criado, aguardando coordenador
    PROCESSANDO = "PROCESSANDO"  # um coordenador pegou (com lock de job)
    EMITIDA = "EMITIDA"          # finalizado + XML validado (assinatura + QR)
    FALHOU = "FALHOU"            # erro (breaker/assinatura/negócio)
    CANCELADA = "CANCELADA"      # evento de cancelación aplicado


class ReceptorTipo(str, Enum):
    CONTRIBUYENTE = "CONTRIBUYENTE"  # RUC
    CI = "CI"                        # cédula (no contribuyente)
    INNOMINADO = "INNOMINADO"        # consumidor final


class SifenEmission(Document):
    """Uma ordem de emissão de documento eletrônico (fila do coordenador)."""

    # idempotência (o operador gera; reenvio não duplica)
    client_request_id: str

    status: EmissionStatus = EmissionStatus.PENDENTE
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    # vínculo ao domínio interno
    client: Optional[Link[Client]] = None
    payment_id: Optional[PydanticObjectId] = None          # recibo do cliente
    sponsor_invoice_id: Optional[PydanticObjectId] = None   # DTE consolidado do subsidiador

    # entrada (o que emitir) — snapshot, imutável após criar
    tipo_documento: int = 1                 # 1 = Factura
    doc: str = ""                           # ci_ruc do receptor (o coordenador resolve)
    nombre: Optional[str] = None            # nome do receptor (fallback/cadastro)
    tipo_id: int = 1                         # tipo de identificação (1=cédula, ...) p/ no-contribuyente
    items: List[dict]                       # [{descripcion, cantidad, precio_unit, iva_afect, iva_tasa}]
    condicion: dict                         # {tipo: contado|credito, forma_pago}
    receptor: Optional[dict] = None         # gDatRec RESOLVIDO (preenchido na emissão, pela sessão)

    # resultado (SET)
    cdc: Optional[str] = None
    numero_documento: Optional[str] = None
    proceso_id: Optional[str] = None
    documento_id: Optional[str] = None
    dprot_aut: Optional[str] = None
    xml_r2_key: Optional[str] = None        # chave do XML assinado no R2
    error: Optional[str] = None

    # telemetria (tempo de geração + atividade) — analisar variação por hora/carga
    started_at: Optional[datetime] = None        # quando um device pegou o job
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None            # tempo total de geração (do coordenador)
    phases_ms: Optional[dict] = None             # por fase: {generar, sign, guardar, xml}
    queue_depth_at_start: Optional[int] = None   # jobs em voo quando começou (atividade)

    # lock de JOB (diferente do lock de sessão): quem está processando ESTE job
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None

    class Settings:
        name = "sifen_emissions"
        use_state_management = True
        indexes = [
            [("client_request_id", 1)],  # idempotência
            [("status", 1), ("created_at", 1)],
            [("cdc", 1)],
        ]


class SifenSessionLock(Document):
    """Lock SINGLETON da sessão do portal da org (uma sessão ativa por RUC)."""

    key: str = "session"
    holder: Optional[str] = None            # id do coordenador
    acquired_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None

    class Settings:
        name = "sifen_session_lock"
        indexes = [
            IndexModel([("key", ASCENDING)], unique=True),  # garante singleton
        ]


class SifenCoordinator(Document):
    """
    PC liberado para emitir documentos eletrônicos ("Liberar este PC").
    O backend serve jobs da fila só a coordenadores enabled + online (heartbeat fresco),
    garantindo que a emissão só sai de uma máquina confiável da rede local.
    """

    machine_id: str                          # id estável por instalação/PC
    label: Optional[str] = None              # nome do PC / operador (exibição)
    enabled: bool = False                    # o ADMIN permite (ou não) este PC gerar docs
    last_heartbeat: Optional[datetime] = None
    permitted_by: Optional[str] = None       # admin que permitiu/revogou
    registered_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "sifen_coordinators"
        indexes = [
            IndexModel([("machine_id", ASCENDING)], unique=True),
        ]


class SifenCredential(Document):
    """Credenciais cifradas do portal da org (clave + PIN de assinatura)."""

    key: str = "default"
    ruc: str
    clave_enc: str                          # AES-256 (utils/crypto)
    pin_enc: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "sifen_credentials"
