"""
Endpoints da sessao de caja (apertura/cierre do turno).

Router separado de `/finance` de proposito: quem abre e fecha a caja e o cajero,
que tem escopo "caja"/"payments" e NAO tem "finance". O master passa por qualquer
escopo (ver `require_scopes`).
"""

from decimal import Decimal
from typing import Annotated, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.user import User
from app.models.finance import CashSession, CashSessionStatus
from app.routers.auth import get_current_active_user, require_scopes
from app.services.caja_service import (
    CajaError,
    abrir_caja,
    cerrar_caja,
    computar_sesion,
    get_caja_abierta,
)

router = APIRouter(dependencies=[Depends(require_scopes("caja", "payments", "finance"))])


class AbrirCajaRequest(BaseModel):
    monto_inicial: Decimal = Field(default=Decimal("0"), ge=0,
                                   description="Fondo de cambio inicial en la gaveta")
    operador: Optional[str] = Field(default=None,
                                    description="Solo master: abrir en nombre de otro operador")


class CerrarCajaRequest(BaseModel):
    efectivo_fisico: Decimal = Field(ge=0, description="Efectivo contado físicamente")
    observaciones: Optional[str] = None


def _sesion_to_dict(s: CashSession) -> dict:
    return {
        "id": str(s.id),
        "numero": s.numero,
        "numero_fmt": s.numero_fmt,
        "status": s.status.value,
        "operador": s.operador,
        "abierto_por": s.abierto_por,
        "fecha_apertura": s.fecha_apertura,
        "monto_inicial": s.monto_inicial,
        "fecha_cierre": s.fecha_cierre,
        "cerrado_por": s.cerrado_por,
        "cantidad_pagos": s.cantidad_pagos,
        "ingresos_efectivo": s.ingresos_efectivo,
        "ingresos_transferencia": s.ingresos_transferencia,
        "ingresos_cheque": s.ingresos_cheque,
        "ingresos_total": s.ingresos_total,
        "estornos_cantidad": s.estornos_cantidad,
        "estornos_total": s.estornos_total,
        "estornos_efectivo": s.estornos_efectivo,
        "estornos_efectivo_previos": s.estornos_efectivo_previos,
        "efectivo_esperado": s.efectivo_esperado,
        "efectivo_fisico": s.efectivo_fisico,
        "diferencia": s.diferencia,
        "observaciones": s.observaciones,
        "created_at": s.created_at,
    }


@router.get("/actual")
async def caja_actual(
    current_user: Annotated[User, Depends(get_current_active_user)],
    operador: Optional[str] = None,
):
    """Caja aberta do operador (ou `null` se nao houver). Base do boot do Modo Caja."""
    quien = operador if (operador and current_user.role == "master") else current_user.username
    sesion = await get_caja_abierta(quien)
    return _sesion_to_dict(sesion) if sesion else None


@router.post("/abrir", status_code=status.HTTP_201_CREATED)
async def caja_abrir(
    body: AbrirCajaRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Abre um turno (numero sequencial de caja) com o fondo inicial contado."""
    quien = body.operador if (body.operador and current_user.role == "master") else current_user.username
    try:
        sesion = await abrir_caja(quien, body.monto_inicial, abierto_por=current_user.username)
    except CajaError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _sesion_to_dict(sesion)


@router.get("/preview")
async def caja_preview(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session_id: Optional[str] = None,
):
    """Resumo do turno em andamento (sem gravar) — o que o operador confere ao fechar."""
    sesion = await _resolver_sesion(current_user, session_id)
    return await computar_sesion(sesion)


@router.post("/cerrar")
async def caja_cerrar(
    body: CerrarCajaRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session_id: Optional[str] = None,
):
    """Fecha o turno com o efectivo contado; grava esperado, contado e diferencia."""
    sesion = await _resolver_sesion(current_user, session_id)
    try:
        sesion = await cerrar_caja(
            sesion, body.efectivo_fisico, current_user.username,
            observaciones=body.observaciones,
        )
    except CajaError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _sesion_to_dict(sesion)


@router.get("/sesiones")
async def caja_list(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(50, le=200),
    operador: Optional[str] = None,
    estado: Optional[CashSessionStatus] = None,
):
    """Historico de cajas (mais recentes primeiro). Operator so enxerga as suas."""
    q = CashSession.find()
    if current_user.role != "master":
        q = q.find(CashSession.operador == current_user.username)
    elif operador:
        q = q.find(CashSession.operador == operador)
    if estado:
        q = q.find(CashSession.status == estado)
    sesiones = await q.sort(-CashSession.numero).limit(limit).to_list()
    return [_sesion_to_dict(s) for s in sesiones]


async def _resolver_sesion(current_user: User, session_id: Optional[str]) -> CashSession:
    """Sessao explicita (master) ou a caja aberta do proprio usuario."""
    if session_id:
        try:
            sesion = await CashSession.get(PydanticObjectId(session_id))
        except Exception:
            sesion = None
        if not sesion:
            raise HTTPException(status_code=404, detail="Caja no encontrada")
        if current_user.role != "master" and sesion.operador != current_user.username:
            raise HTTPException(status_code=403, detail="Caja de otro operador")
        return sesion

    sesion = await get_caja_abierta(current_user.username)
    if not sesion:
        raise HTTPException(status_code=404, detail="No hay caja abierta")
    return sesion
