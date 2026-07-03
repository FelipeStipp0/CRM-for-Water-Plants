"""
Endpoints do workflow de corte.

Inclui endpoints autenticados (operador) e publicos (QR Code scan).
"""

from decimal import Decimal
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.client import Client
from app.models.cutoff import CutoffNotice, CutoffStatus
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.schemas.cutoff import (
    CutoffActionResponse,
    CutoffCandidateResponse,
    CutoffNoticeCreate,
    CutoffNoticeDetail,
    CutoffNoticeResponse,
    ConfirmReactivationRequest,
    ExecuteCutoffRequest,
    QrConfirmRequest,
    QrInfoResponse,
    QrTokenInfo,
    RegisterDeliveryRequest,
    RequestReactivationRequest,
)
from app.services.cutoff_service import CutoffService


# ==================== HELPER ====================

async def _notice_to_response(notice: CutoffNotice) -> CutoffNoticeResponse:
    """Converte modelo para schema de resposta."""
    return CutoffNoticeResponse(
        id=str(notice.id),
        client_id=str(notice.client.ref.id),
        status=notice.status,
        divida_original=notice.divida_original,
        meses_atraso=notice.meses_atraso,
        has_qr_entrega=notice.qr_token_entrega is not None,
        has_qr_corte=notice.qr_token_corte is not None,
        has_qr_reativacao=notice.qr_token_reativacao is not None,
        fecha_aviso_gerado=notice.fecha_aviso_gerado,
        fecha_entrega_aviso=notice.fecha_entrega_aviso,
        aviso_entregue_por=notice.aviso_entregue_por,
        observacion_aviso=notice.observacion_aviso,
        fecha_limite_pago=notice.fecha_limite_pago,
        fecha_corte=notice.fecha_corte,
        cortado_por=notice.cortado_por,
        observacion_corte=notice.observacion_corte,
        saiu_por_pagamento=notice.saiu_por_pagamento,
        fecha_saida=notice.fecha_saida,
        reativacao_solicitada=notice.reativacao_solicitada,
        fecha_solicitud_reativacao=notice.fecha_solicitud_reativacao,
        taxa_reativacao_paga=notice.taxa_reativacao_paga,
        fecha_reativacao=notice.fecha_reativacao,
        reativacao_confirmada_por=notice.reativacao_confirmada_por,
        # Fotos/GPS
        foto_instalacao_url=notice.foto_instalacao_url,
        gps_corte_latitude=notice.gps_corte_latitude,
        gps_corte_longitude=notice.gps_corte_longitude,
        foto_reativacao_url=notice.foto_reativacao_url,
        gps_reativacao_latitude=notice.gps_reativacao_latitude,
        gps_reativacao_longitude=notice.gps_reativacao_longitude,
        created_at=notice.created_at,
        updated_at=notice.updated_at,
    )


async def _notice_to_detail(notice: CutoffNotice) -> CutoffNoticeDetail:
    """Converte modelo para schema detalhado com dados do cliente."""
    client = await notice.client.fetch()
    divida_atual = await CutoffService._calculate_total_debt(client.id) if client else Decimal("0")

    base = await _notice_to_response(notice)
    return CutoffNoticeDetail(
        **base.model_dump(),
        client_nombre=client.nombre_completo if client else "?",
        client_ci_ruc=client.ci_ruc if client else "?",
        client_telefono=(client.celular or client.telefono) if client else None,
        client_direccion=client.direccion if client else "?",
        client_manzana=client.manzana if client else "?",
        client_lote=client.lote if client else "?",
        divida_atual=divida_atual,
    )


# ==================== ROUTER AUTENTICADO ====================

router = APIRouter(dependencies=[Depends(require_scopes("cutoff"))])


@router.get("/candidates", response_model=List[CutoffCandidateResponse])
async def get_cutoff_candidates(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Lista candidatos a corte (inadimplentes nao no workflow)."""
    candidates = await CutoffService.get_cutoff_candidates()
    return [
        CutoffCandidateResponse(
            client_id=str(c.client_id),
            nombre_completo=c.nombre_completo,
            ci_ruc=c.ci_ruc,
            manzana=c.manzana,
            lote=c.lote,
            divida_total=c.divida_total,
            meses_atraso=c.meses_atraso,
            oldest_invoice_date=c.oldest_invoice_date,
        )
        for c in candidates
    ]


@router.post("/notices", response_model=CutoffActionResponse, status_code=status.HTTP_201_CREATED)
async def create_cutoff_notice(
    data: CutoffNoticeCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Adiciona cliente a lista de corte (EM_LISTA)."""
    try:
        client_id = PydanticObjectId(data.client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    result = await CutoffService.add_to_list(client_id)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return CutoffActionResponse(
        success=True,
        cutoff_notice_id=str(result.cutoff_notice_id),
        message=result.message,
    )


@router.get("/notices", response_model=List[CutoffNoticeDetail])
async def list_cutoff_notices(
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[CutoffStatus] = Query(None, alias="status"),
    include_exited: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista avisos de corte com filtros, já com os dados do cliente.

    Faz batch-fetch dos clientes (1 query) em vez de obrigar o frontend a
    chamar /notices/{id} por linha (N+1). divida_atual = divida_original aqui
    (o detalhe recalcula ao abrir o aviso); o workflow só exibe a original.
    """
    filters = []
    if not include_exited:
        filters.append(CutoffNotice.saiu_por_pagamento == False)
    if status_filter:
        filters.append(CutoffNotice.status == status_filter)

    query = CutoffNotice.find(*filters) if filters else CutoffNotice.find()
    notices = await query.skip(skip).limit(limit).sort("-created_at").to_list()

    if not notices:
        return []

    # Batch fetch dos clientes de uma só vez.
    client_ids = [n.client.ref.id for n in notices]
    clients_list = await Client.find({"_id": {"$in": client_ids}}).to_list()
    clients_map = {c.id: c for c in clients_list}

    results = []
    for n in notices:
        client = clients_map.get(n.client.ref.id)
        base = await _notice_to_response(n)
        results.append(CutoffNoticeDetail(
            **base.model_dump(),
            client_nombre=client.nombre_completo if client else "?",
            client_ci_ruc=client.ci_ruc if client else "?",
            client_telefono=(client.celular or client.telefono) if client else None,
            client_direccion=client.direccion if client else "?",
            client_manzana=client.manzana if client else "?",
            client_lote=client.lote if client else "?",
            divida_atual=base.divida_original,
        ))
    return results


@router.get("/notices/ready", response_model=List[CutoffNoticeDetail])
async def list_ready_for_cutoff(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(50, ge=1, le=200),
):
    """Lista avisos PRONTO_PARA_CORTE com dados do cliente."""
    notices = await CutoffNotice.find(
        CutoffNotice.status == CutoffStatus.PRONTO_PARA_CORTE,
        CutoffNotice.saiu_por_pagamento == False,
    ).limit(limit).sort("fecha_limite_pago").to_list()

    if not notices:
        return []

    # Batch fetch: busca todos os clientes de uma vez
    client_ids = [n.client.ref.id for n in notices]
    clients_list = await Client.find({"_id": {"$in": client_ids}}).to_list()
    clients_map = {c.id: c for c in clients_list}

    results = []
    for n in notices:
        client = clients_map.get(n.client.ref.id)
        divida_atual = await CutoffService._calculate_total_debt(n.client.ref.id) if client else Decimal("0")
        base = await _notice_to_response(n)
        results.append(CutoffNoticeDetail(
            **base.model_dump(),
            client_nombre=client.nombre_completo if client else "?",
            client_ci_ruc=client.ci_ruc if client else "?",
            client_telefono=(client.celular or client.telefono) if client else None,
            client_direccion=client.direccion if client else "?",
            client_manzana=client.manzana if client else "?",
            client_lote=client.lote if client else "?",
            divida_atual=divida_atual,
        ))
    return results


@router.get("/notices/client/{client_id}", response_model=Optional[CutoffNoticeDetail])
async def get_client_cutoff_notice(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna aviso ativo de um cliente (se existir)."""
    try:
        cid = PydanticObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    notice = await CutoffService._has_active_notice(cid)
    if not notice:
        return None

    return await _notice_to_detail(notice)


@router.get("/notices/{notice_id}", response_model=CutoffNoticeDetail)
async def get_cutoff_notice(
    notice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna detalhes completos de um aviso."""
    try:
        notice = await CutoffNotice.get(PydanticObjectId(notice_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Aviso nao encontrado")

    if not notice:
        raise HTTPException(status_code=404, detail="Aviso nao encontrado")

    return await _notice_to_detail(notice)


@router.post("/notices/{notice_id}/generate", response_model=QrTokenInfo)
async def generate_notice(
    notice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Gera aviso de corte + QR token (EM_LISTA -> EM_AVISO). Retorna QR token."""
    try:
        nid = PydanticObjectId(notice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="notice_id invalido")

    result = await CutoffService.generate_notice(nid)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return QrTokenInfo(
        qr_token=result.qr_token,
        action_type=result.action_type,
        cutoff_notice_id=str(result.cutoff_notice_id),
    )


@router.post("/notices/{notice_id}/deliver", response_model=CutoffActionResponse)
async def register_delivery(
    notice_id: str,
    data: RegisterDeliveryRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Registra entrega manual do aviso (EM_AVISO -> EM_CONTAGEM)."""
    try:
        nid = PydanticObjectId(notice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="notice_id invalido")

    result = await CutoffService.register_delivery_manual(
        nid,
        entregue_por=data.entregue_por or current_user.full_name,
        observacion=data.observacion,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return CutoffActionResponse(
        success=True,
        cutoff_notice_id=str(result.cutoff_notice_id),
        message=result.message,
    )


@router.post("/notices/{notice_id}/mark-ready", response_model=CutoffActionResponse)
async def mark_ready_for_cutoff(
    notice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Marca como pronto para corte (EM_CONTAGEM -> PRONTO_PARA_CORTE)."""
    try:
        nid = PydanticObjectId(notice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="notice_id invalido")

    result = await CutoffService.mark_ready_for_cutoff(nid)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return CutoffActionResponse(
        success=True,
        cutoff_notice_id=str(result.cutoff_notice_id),
        message=result.message,
    )


@router.post("/notices/{notice_id}/generate-order", response_model=QrTokenInfo)
async def generate_cutoff_order(
    notice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Gera ordem de corte + QR token (PRONTO_PARA_CORTE)."""
    try:
        nid = PydanticObjectId(notice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="notice_id invalido")

    result = await CutoffService.generate_cutoff_order(nid)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return QrTokenInfo(
        qr_token=result.qr_token,
        action_type=result.action_type,
        cutoff_notice_id=str(result.cutoff_notice_id),
    )


@router.post("/notices/{notice_id}/execute", response_model=CutoffActionResponse)
async def execute_cutoff(
    notice_id: str,
    data: ExecuteCutoffRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Executa corte manual (PRONTO_PARA_CORTE -> CORTADO)."""
    try:
        nid = PydanticObjectId(notice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="notice_id invalido")

    result = await CutoffService.execute_cutoff_manual(
        nid,
        cortado_por=data.cortado_por or current_user.full_name,
        observacion=data.observacion,
        foto_url=data.foto_url,
        gps_latitude=data.gps_latitude,
        gps_longitude=data.gps_longitude,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return CutoffActionResponse(
        success=True,
        cutoff_notice_id=str(result.cutoff_notice_id),
        message=result.message,
    )


@router.post("/reactivation/request", response_model=QrTokenInfo)
async def request_reactivation(
    data: RequestReactivationRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Solicita reativacao. Requer pagamento >= divida + taxa. Retorna QR token para ordem de reativacao."""
    try:
        client_id = PydanticObjectId(data.client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    result = await CutoffService.request_reactivation(
        client_id=client_id,
        valor_pago=data.valor_pago,
        registrado_por=current_user.full_name,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return QrTokenInfo(
        qr_token=result.qr_token,
        action_type=result.action_type,
        cutoff_notice_id=str(result.cutoff_notice_id),
        comprobante=result.comprobante,
        fecha_pago=result.fecha_pago,
    )


@router.post("/reactivation/{notice_id}/confirm", response_model=CutoffActionResponse)
async def confirm_reactivation(
    notice_id: str,
    data: ConfirmReactivationRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Confirma reativacao manual pelo tecnico."""
    try:
        nid = PydanticObjectId(notice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="notice_id invalido")

    result = await CutoffService.confirm_reactivation_manual(
        nid,
        confirmado_por=data.confirmado_por or current_user.full_name,
        foto_url=data.foto_url,
        gps_latitude=data.gps_latitude,
        gps_longitude=data.gps_longitude,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return CutoffActionResponse(
        success=True,
        cutoff_notice_id=str(result.cutoff_notice_id),
        message=result.message,
    )


@router.post("/notices/process-expired", response_model=CutoffActionResponse)
async def process_expired_countdowns(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Processa countdowns expirados (batch)."""
    count = await CutoffService.process_expired_countdowns()
    return CutoffActionResponse(
        success=True,
        message=f"{count} aviso(s) marcado(s) como PRONTO PARA CORTE",
    )


# ==================== ENDPOINTS PUBLICOS (QR CODE) ====================

qr_router = APIRouter()


@qr_router.get("/qr/{token}/info", response_model=QrInfoResponse)
async def get_qr_info(token: str):
    """Retorna info do aviso pelo QR token (sem autenticacao)."""
    info = await CutoffService.get_qr_info(token)
    if not info:
        raise HTTPException(status_code=404, detail="Token invalido")

    return QrInfoResponse(**info)


@qr_router.post("/qr/{token}/confirm", response_model=CutoffActionResponse)
async def confirm_by_qr(token: str, data: QrConfirmRequest):
    """Confirma acao via QR Code scan (sem autenticacao)."""
    info = await CutoffService.get_qr_info(token)
    if not info:
        raise HTTPException(status_code=404, detail="Token invalido")

    if info["already_done"]:
        raise HTTPException(status_code=400, detail="Acao ja foi realizada")

    action_type = info["action_type"]

    if action_type == "ENTREGA_AVISO":
        result = await CutoffService.confirm_delivery_by_qr(
            token, data.nome_responsavel, data.observacion
        )
    elif action_type == "EXECUCAO_CORTE":
        result = await CutoffService.confirm_cutoff_by_qr(
            token, data.nome_responsavel, data.observacion,
            foto_url=data.foto_url,
            gps_latitude=data.gps_latitude,
            gps_longitude=data.gps_longitude,
        )
    elif action_type == "CONFIRMACAO_REATIVACAO":
        result = await CutoffService.confirm_reactivation_by_qr(
            token, data.nome_responsavel,
            foto_url=data.foto_url,
            gps_latitude=data.gps_latitude,
            gps_longitude=data.gps_longitude,
        )
    else:
        raise HTTPException(status_code=400, detail="Tipo de acao desconhecido")

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return CutoffActionResponse(
        success=True,
        cutoff_notice_id=str(result.cutoff_notice_id),
        message=result.message,
    )
