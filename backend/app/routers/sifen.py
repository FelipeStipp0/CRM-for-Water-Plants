"""
Endpoints da facturación electrónica (SIFEN).

- Operador: emitir (cria job na fila), consultar status, listar, cancelar.
- Coordenador (máquina única com o adapter): claim do próximo job + devolver resultado.
- Master: configurar credenciais cifradas.

A emissão em si (chamadas ao portal) roda no coordenador; aqui é só a fila + estado.
"""

from datetime import datetime
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.sifen import SifenEmission, EmissionStatus
from app.models.user import User
from app.routers.auth import get_current_active_user, get_current_master, require_scopes
from app.services.sifen import queue as sifen_queue
from app.services.sifen import coordinator as sifen_coord
from app.services.sifen.crypto_creds import salvar_credenciais, carregar_credenciais

router = APIRouter(dependencies=[Depends(require_scopes("sifen"))])


# ------------------------- schemas -------------------------

class ItemIn(BaseModel):
    descripcion: str
    cantidad: int = 1
    precio_unit: int
    tasa_iva: int = 10
    afectacion: int = 1
    codigo: str = "1"


class EmitirIn(BaseModel):
    client_request_id: str = Field(..., description="idempotência: reenvio não duplica")
    doc: str = Field(..., description="ci_ruc do receptor (o coordenador resolve RUC/CI/OEE)")
    nombre: Optional[str] = None
    tipo_id: int = 1
    items: List[ItemIn]
    condicion: dict = Field(default_factory=lambda: {
        "tipo": "contado", "forma_pago": {"codigo": 1, "desc": "Efectivo"}})
    client_id: Optional[PydanticObjectId] = None
    payment_id: Optional[PydanticObjectId] = None


class EmissionOut(BaseModel):
    id: str
    status: EmissionStatus
    client_request_id: str
    created_by: str
    # entrada (o coordenador precisa disto para emitir)
    doc: str = ""
    nombre: Optional[str] = None
    tipo_id: int = 1
    items: List[dict] = []
    condicion: dict = {}
    # resultado
    cdc: Optional[str] = None
    numero_documento: Optional[str] = None
    dprot_aut: Optional[str] = None
    xml_r2_key: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @classmethod
    def of(cls, j: SifenEmission) -> "EmissionOut":
        return cls(
            id=str(j.id), status=j.status, client_request_id=j.client_request_id,
            created_by=j.created_by, doc=j.doc, nombre=j.nombre, tipo_id=j.tipo_id,
            items=j.items, condicion=j.condicion,
            cdc=j.cdc, numero_documento=j.numero_documento,
            dprot_aut=j.dprot_aut, xml_r2_key=j.xml_r2_key, error=j.error,
            created_at=j.created_at, updated_at=j.updated_at,
        )


class CredenciaisIn(BaseModel):
    ruc: str
    clave: str
    pin: str


class CoordinatorPatch(BaseModel):
    status: EmissionStatus
    cdc: Optional[str] = None
    proceso_id: Optional[str] = None
    documento_id: Optional[str] = None
    numero_documento: Optional[str] = None
    dprot_aut: Optional[str] = None
    xml_r2_key: Optional[str] = None
    error: Optional[str] = None
    # telemetria reportada pelo device
    duration_ms: Optional[int] = None
    phases_ms: Optional[dict] = None


class AnnounceIn(BaseModel):
    machine_id: str
    label: Optional[str] = None


class PermitirIn(BaseModel):
    machine_id: str
    enabled: bool
    label: Optional[str] = None


class PollIn(BaseModel):
    machine_id: str


class CoordinatorOut(BaseModel):
    machine_id: str
    label: Optional[str] = None
    enabled: bool
    online: bool
    last_heartbeat: Optional[datetime] = None
    permitted_by: Optional[str] = None


# ------------------------- operador -------------------------

@router.post("/emitir", response_model=EmissionOut)
async def emitir(
    body: EmitirIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria (ou retorna, se já existe) o job de emissão — idempotente por client_request_id."""
    existente = await SifenEmission.find_one(
        SifenEmission.client_request_id == body.client_request_id)
    if existente:
        return EmissionOut.of(existente)

    job = SifenEmission(
        client_request_id=body.client_request_id,
        created_by=current_user.username,
        doc=body.doc,
        nombre=body.nombre,
        tipo_id=body.tipo_id,
        items=[it.model_dump() for it in body.items],
        condicion=body.condicion,
        client_id=body.client_id,
        payment_id=body.payment_id,
    )
    await job.insert()
    return EmissionOut.of(job)


@router.get("/ruc-lookup")
async def ruc_lookup(
    doc: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Consulta o registro DNIT: {found, estado, es_contribuyente, nombre, dv}.
    Usado pelo modal (preview do nome/natureza) e pelo coordenador (resolver).
    Regra: contribuyente = só estado ACTIVO.
    """
    from app.services.sifen.ruc_lookup import lookup
    return await lookup(doc)


@router.get("/emision/{emission_id}", response_model=EmissionOut)
async def status_emision(
    emission_id: PydanticObjectId,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    job = await SifenEmission.get(emission_id)
    if not job:
        raise HTTPException(404, "Emisión no encontrada")
    return EmissionOut.of(job)


@router.get("/emisiones", response_model=List[EmissionOut])
async def listar_emisiones(
    current_user: Annotated[User, Depends(get_current_active_user)],
    status: Optional[EmissionStatus] = None,
    limit: int = Query(50, le=200),
):
    q = SifenEmission.find()
    if status:
        q = SifenEmission.find(SifenEmission.status == status)
    jobs = await q.sort(-SifenEmission.created_at).limit(limit).to_list()
    return [EmissionOut.of(j) for j in jobs]


@router.post("/credenciais")
async def configurar_credenciais(
    body: CredenciaisIn,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """Salva as credenciais cifradas do portal (clave + PIN). Só o admin (master) seta."""
    await salvar_credenciais(body.ruc, body.clave, body.pin)
    return {"ok": True}


@router.get("/credenciais")
async def obter_credenciais(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Retorna as credenciais DECIFRADAS do portal para o coordenador emitir.
    Acessível a qualquer user da org (o isolamento multi-tenant garante que ninguém
    de fora vê). 404 se ainda não configuradas.
    """
    try:
        ruc, clave, pin = await carregar_credenciais()
    except RuntimeError:
        raise HTTPException(404, "Credenciais SIFEN no configuradas.")
    return {"ruc": ruc, "clave": clave, "pin": pin}


# ------------------------- coordenador -------------------------

@router.post("/coordinator/announce")
async def coordinator_announce(
    body: AnnounceIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Auto-registro do dispositivo (na inicialização). Entra desabilitado até o admin permitir."""
    coord = await sifen_coord.anunciar(body.machine_id, body.label)
    return {"ok": True, "enabled": coord.enabled}


@router.post("/coordinator/permitir")
async def coordinator_permitir(
    body: PermitirIn,
    current_user: Annotated[User, Depends(get_current_master)],
):
    """Admin permite (ou revoga) a geração de docs neste dispositivo. Só master."""
    coord = await sifen_coord.permitir(
        body.machine_id, body.enabled, admin=current_user.username, label=body.label)
    return {"ok": True, "enabled": coord.enabled}


@router.get("/coordinators", response_model=List[CoordinatorOut])
async def listar_coordinators(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Dispositivos + permissão + presença/uptime (para o painel de configurações)."""
    coords = await sifen_coord.listar()
    return [
        CoordinatorOut(
            machine_id=c.machine_id, label=c.label, enabled=c.enabled,
            online=sifen_coord.esta_online(c), last_heartbeat=c.last_heartbeat,
            permitted_by=c.permitted_by,
        )
        for c in coords
    ]


@router.post("/coordinator/poll", response_model=Optional[EmissionOut])
async def coordinator_poll(
    body: PollIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Dispositivo marca presença e reivindica o próximo job PENDENTE.
    403 se o PC não estiver **permitido** — a emissão só sai de máquina autorizada.
    """
    if not await sifen_coord.heartbeat(body.machine_id):
        raise HTTPException(
            403, "Este PC no está habilitado para generar documentos.")
    # gateado pelo lock de sessão: nunca duas sessões abertas ao mesmo tempo
    job = await sifen_queue.claim_for_device(body.machine_id)
    return EmissionOut.of(job) if job else None


@router.patch("/coordinator/{emission_id}", response_model=EmissionOut)
async def coordinator_patch(
    emission_id: PydanticObjectId,
    body: CoordinatorPatch,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """O coordenador devolve o resultado da emissão (status + campos do SET)."""
    job = await SifenEmission.get(emission_id)
    if not job:
        raise HTTPException(404, "Emisión no encontrada")
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()

    # terminou (emitida/falhou/cancelada) → marca fim e LIBERA a sessão
    if body.status in (EmissionStatus.EMITIDA, EmissionStatus.FALHOU, EmissionStatus.CANCELADA):
        job.finished_at = datetime.utcnow()
        if job.locked_by:
            await sifen_queue.release_sessao(job.locked_by)
    await job.save()
    return EmissionOut.of(job)
