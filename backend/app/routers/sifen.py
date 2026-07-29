"""
Endpoints da facturación electrónica (SIFEN).

- Operador: emitir (cria job na fila), consultar status, listar, cancelar.
- Coordenador (máquina única com o adapter): claim do próximo job + devolver resultado.
- Master: configurar credenciais cifradas.

A emissão em si (chamadas ao portal) roda no coordenador; aqui é só a fila + estado.
"""

import asyncio
from datetime import datetime
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.models.sifen import (
    SifenEmission, EmissionStatus, EmissionFase, FASES_ABORTAVEIS,
)
from app.models.user import User
from app.routers.auth import get_current_active_user, get_current_master, require_scopes
from app.services.sifen import queue as sifen_queue
from app.services.sifen import coordinator as sifen_coord
from app.services.sifen.crypto_creds import salvar_credenciais, carregar_credenciais

router = APIRouter(dependencies=[Depends(require_scopes("sifen"))])


def numero_formateado(cdc: Optional[str], numero_documento: Optional[str] = None) -> Optional[str]:
    """
    Número legível da factura (`001-001-0000123`) a partir do CDC.

    O CDC de 44 dígitos carrega estabelecimento (11:14), punto de expedición
    (14:17) e número (17:24) — por isso dá para mostrar o número na tela assim
    que `generar` responde, muito antes do XML assinado trazer o `dNumDoc`.
    Fora desse formato, devolve o `dNumDoc` cru (ou None).
    """
    if cdc and len(cdc) == 44 and cdc.isdigit():
        return f"{cdc[11:14]}-{cdc[14:17]}-{cdc[17:24]}"
    return numero_documento or None


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
    # progresso ao vivo (tela do operador) + desistência antes da firma
    fase: Optional[EmissionFase] = None
    abort_solicitado: bool = False
    # resultado
    cdc: Optional[str] = None
    numero_documento: Optional[str] = None
    numero_formateado: Optional[str] = None   # 001-001-0000123 (derivado do CDC)
    dprot_aut: Optional[str] = None
    xml_r2_key: Optional[str] = None
    error: Optional[str] = None
    # cancelación fiscal — o device usa isto para saber que o job é uma cancelación
    cancel_solicitada: bool = False
    cancel_motivo: Optional[str] = None
    cancelada_at: Optional[datetime] = None
    cancel_error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @classmethod
    def of(cls, j: SifenEmission) -> "EmissionOut":
        return cls(
            id=str(j.id), status=j.status, client_request_id=j.client_request_id,
            created_by=j.created_by, doc=j.doc, nombre=j.nombre, tipo_id=j.tipo_id,
            items=j.items, condicion=j.condicion,
            fase=j.fase, abort_solicitado=j.abort_solicitado,
            cdc=j.cdc, numero_documento=j.numero_documento,
            numero_formateado=numero_formateado(j.cdc, j.numero_documento),
            dprot_aut=j.dprot_aut, xml_r2_key=j.xml_r2_key, error=j.error,
            cancel_solicitada=j.cancel_solicitada, cancel_motivo=j.cancel_motivo,
            cancelada_at=j.cancelada_at, cancel_error=j.cancel_error,
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
    # cancelación reportada pelo device
    cancel_error: Optional[str] = None
    # telemetria reportada pelo device
    duration_ms: Optional[int] = None
    phases_ms: Optional[dict] = None


class CancelarIn(BaseModel):
    motivo: str = Field(..., min_length=3, description="Motivo del evento de cancelación")


class FaseIn(BaseModel):
    fase: EmissionFase
    # O CDC nasce em `generar`, antes da firma: chega aqui para a tela mostrar o
    # número da factura e para reconciliar se o coordenador cair no meio.
    cdc: Optional[str] = None


class UltimoNumeroOut(BaseModel):
    """Último documento que ESTE sistema emitiu (o SET é quem numera)."""

    numero_documento: Optional[str] = None
    numero_formateado: Optional[str] = None
    cdc: Optional[str] = None
    emitida_at: Optional[datetime] = None
    total_emitidas: int = 0


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


@router.post("/emision/{emission_id}/cancelar", response_model=EmissionOut)
async def cancelar_emision(
    emission_id: PydanticObjectId,
    body: CancelarIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Pede a cancelación fiscal de um DTE emitido (o coordenador executa depois).

    O caminho normal é o estorno do pagamento, que já pede sozinho; este endpoint
    cobre a factura sem pagamento vinculado e a re-tentativa depois de um erro.
    """
    job = await SifenEmission.get(emission_id)
    if not job:
        raise HTTPException(404, "Emisión no encontrada")
    try:
        job = await sifen_queue.solicitar_cancelacion(job, body.motivo, current_user.username)
    except sifen_queue.EmissionError as exc:
        raise HTTPException(409, str(exc))
    return EmissionOut.of(job)


@router.post("/emision/{emission_id}/abortar", response_model=EmissionOut)
async def abortar_emision(
    emission_id: PydanticObjectId,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Desiste de uma emissão que ainda NÃO foi assinada.

    Diferente de `/cancelar`: aqui o documento nunca chegou ao SET, então basta
    largar o job. Depois da firma o documento existe e a única saída é o evento
    de cancelación — daí o 409.
    """
    job = await SifenEmission.get(emission_id)
    if not job:
        raise HTTPException(404, "Emisión no encontrada")

    if job.status == EmissionStatus.ABORTADA:
        return EmissionOut.of(job)
    if job.status not in (EmissionStatus.PENDENTE, EmissionStatus.PROCESSANDO):
        raise HTTPException(
            409, "La factura ya fue emitida; solo se puede cancelar por SIFEN.")
    if job.fase not in FASES_ABORTAVEIS:
        raise HTTPException(
            409, "El documento ya fue firmado; solo se puede cancelar por SIFEN.")

    job.abort_solicitado = True
    job.abort_por = current_user.username
    job.abort_solicitado_at = datetime.utcnow()
    job.updated_at = job.abort_solicitado_at

    # Ninguém pegou ainda → morre aqui mesmo. Se um coordenador está com ele, o
    # executor vê a solicitação antes de assinar e larga (e aí solta a sessão).
    if job.status == EmissionStatus.PENDENTE:
        job.status = EmissionStatus.ABORTADA
        job.finished_at = job.abort_solicitado_at
    await job.save()
    return EmissionOut.of(job)


@router.get("/ultimo-numero", response_model=UltimoNumeroOut)
async def ultimo_numero(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Último número de factura que este sistema emitiu.

    Quem numera é o SET (o número só existe depois de `generar`), então isto é
    histórico — serve para o operador conferir a sequência, não para prever o
    próximo número.
    """
    ultima = await SifenEmission.find(
        SifenEmission.status == EmissionStatus.EMITIDA
    ).sort(-SifenEmission.finished_at).limit(1).to_list()
    total = await SifenEmission.find(
        SifenEmission.status == EmissionStatus.EMITIDA).count()
    if not ultima:
        return UltimoNumeroOut(total_emitidas=total)
    j = ultima[0]
    return UltimoNumeroOut(
        numero_documento=j.numero_documento,
        numero_formateado=numero_formateado(j.cdc, j.numero_documento),
        cdc=j.cdc,
        emitida_at=j.finished_at or j.updated_at,
        total_emitidas=total,
    )


@router.get("/emision/{emission_id}/xml")
async def emision_xml(
    emission_id: PydanticObjectId,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    XML assinado de uma emissão EMITIDA (para o cliente gerar/imprimir o KuDE).
    Preferimos o storage (R2, via xml_r2_key); fallback = endpoint público por CDC
    através do adapter (mantém a URL real do SET no servidor).
    """
    job = await SifenEmission.get(emission_id)
    if not job:
        raise HTTPException(404, "Emisión no encontrada")

    xml: Optional[bytes] = None
    if job.xml_r2_key:
        from app.utils.r2 import r2_get
        try:
            xml = await asyncio.to_thread(r2_get, job.xml_r2_key)
        except Exception:
            xml = None
    if xml is None and job.cdc:
        from app.services.sifen.provider import get_provider
        try:
            ruc, clave, pin = await carregar_credenciais()
            prov = get_provider(ruc, clave, pin)
            xml = await asyncio.to_thread(prov.baixar_xml, job.cdc)
        except Exception:
            xml = None
    if not xml:
        raise HTTPException(404, "XML no disponible para esta emisión")
    return Response(content=xml, media_type="application/xml")


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


@router.post("/coordinator/{emission_id}/fase", response_model=EmissionOut)
async def coordinator_fase(
    emission_id: PydanticObjectId,
    body: FaseIn,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Coordenador reporta em que fase está o job (tela de progresso do operador).

    Devolve a emissão inteira de propósito: é assim que o executor descobre, no
    mesmo round-trip, que alguém pediu para abortar antes da firma.
    """
    job = await SifenEmission.get(emission_id)
    if not job:
        raise HTTPException(404, "Emisión no encontrada")
    job.fase = body.fase
    job.fase_at = datetime.utcnow()
    job.updated_at = job.fase_at
    if body.cdc:
        job.cdc = body.cdc

    # O coordenador só reporta RECUPERAR depois de firmar, guardar E baixar o XML
    # — o download precisa da sessão viva (a rota pública do SET só serve o RUC
    # que tem sessão com consulta feita). Daqui em diante resta montar e imprimir
    # o KuDE, que é local. Segurar a sessão até o fim fazia a próxima factura
    # esperar pelo PAPEL da anterior; libera aqui.
    if body.fase == EmissionFase.RECUPERAR and job.locked_by:
        await sifen_queue.release_sessao(job.locked_by)

    await job.save()
    return EmissionOut.of(job)


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

    # terminou (emitida/falhou/abortada/cancelada) → marca fim e LIBERA a sessão
    if body.status in (EmissionStatus.EMITIDA, EmissionStatus.FALHOU,
                       EmissionStatus.ABORTADA, EmissionStatus.CANCELADA):
        job.finished_at = datetime.utcnow()
        if job.locked_by:
            await sifen_queue.release_sessao(job.locked_by)

    # cancelación: solta o claim sempre; carimba a data só quando o SET aceitou.
    if body.status == EmissionStatus.CANCELADA:
        job.cancelada_at = job.cancelada_at or datetime.utcnow()
        job.cancel_error = None
    if job.cancel_locked_by:
        if body.cancel_error is not None or body.status == EmissionStatus.CANCELADA:
            await sifen_queue.release_sessao(job.cancel_locked_by)
            job.cancel_locked_by = None
            job.cancel_locked_at = None
    await job.save()
    return EmissionOut.of(job)
