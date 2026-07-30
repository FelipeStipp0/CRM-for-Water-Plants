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


class CargoLibreRequest(BaseModel):
    """
    Cargo lançado no balcão, com valor livre.

    Um item só, de propósito: o balcão cobra uma coisa por vez ("reconexión",
    "caño de 1/2"). Fatura com várias linhas é trabalho de escritório e continua
    em `POST /invoices/`.
    """
    client_id: str
    descripcion: str = Field(min_length=3, max_length=200)
    valor: Decimal = Field(gt=0, description="Preço unitário em guaraníes")
    cantidad: int = Field(default=1, ge=1, le=999)
    # iva_afectacion: 1=Gravado, 2=Parcial, 3=Exento ; iva_tasa: 0/5/10
    iva_tasa: int = Field(default=10)
    iva_afectacion: int = Field(default=1, ge=1, le=3)


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
        "sangrias_cantidad": s.sangrias_cantidad,
        "sangrias_total": s.sangrias_total,
        "reposiciones_cantidad": s.reposiciones_cantidad,
        "reposiciones_total": s.reposiciones_total,
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


class MovimientoRequest(BaseModel):
    """Sangría (sale plata de la gaveta) o reposición (entra plata de vuelta)."""
    categoria: str = Field(description="SANGRIA_CAJA o REPOSICION_CAJA")
    valor: Decimal = Field(gt=0)
    descripcion: str = Field(min_length=3, description="A dónde fue / de dónde vino")


@router.post("/movimiento", status_code=status.HTTP_201_CREATED)
async def caja_movimiento(
    body: MovimientoRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session_id: Optional[str] = None,
):
    """
    Lança sangría/reposición no turno aberto e devolve o resumo já recalculado.

    Devolver o resumo no mesmo round-trip é de propósito: o efectivo esperado
    muda na hora, e o cajero precisa ver o novo número sem pedir de novo.
    """
    from app.models.finance import TransactionCategory
    from app.services.caja_service import registrar_movimiento

    try:
        categoria = TransactionCategory(body.categoria)
    except ValueError:
        raise HTTPException(status_code=400, detail="Categoría de movimiento inválida")

    sesion = await _resolver_sesion(current_user, session_id)
    try:
        mov = await registrar_movimiento(
            sesion, categoria, body.valor, body.descripcion, current_user.username)
    except CajaError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    resumen = await computar_sesion(sesion)
    return {"movimiento_id": str(mov.id), "resumen": resumen}


@router.get("/movimientos")
async def caja_movimientos(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session_id: Optional[str] = None,
):
    """Sangrías e reposiciones do turno."""
    from app.services.caja_service import listar_movimientos

    sesion = await _resolver_sesion(current_user, session_id)
    return await listar_movimientos(sesion)


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


@router.get("/productos")
async def caja_productos(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Catálogo ativo, só leitura — atalho de preenchimento do cargo do balcão.

    Vive aqui e não em `/products` porque aquele router inteiro exige o escopo
    `invoices` (é onde se cria e se desativa produto). O cajero precisa ler a
    lista, não administrá-la.
    """
    from app.models.product import Product

    produtos = await Product.find(Product.activo == True).sort("codigo").to_list()  # noqa: E712
    return [
        {
            "id": str(p.id), "codigo": p.codigo, "descripcion": p.descripcion,
            "precio_unitario": p.precio_unitario, "iva_tasa": p.iva_tasa,
            "iva_afectacion": p.iva_afectacion, "unidad": p.unidad,
        }
        for p in produtos
    ]


@router.post("/cargo", status_code=status.HTTP_201_CREATED)
async def caja_cargo(
    body: CargoLibreRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Fatura um cargo de valor livre para cobrar no mesmo atendimento.

    Existe separado de `POST /invoices/` por causa do escopo: aquele router
    inteiro exige `invoices` (criar em lote, anular, apagar fatura), e o cajero
    não tem — a primeira versão disto chamava lá e tomava **403** no balcão.
    Aqui o gate é o mesmo do resto da caja (`caja`/`payments`/`finance`) e o que
    se pode fazer é só isto: uma AVULSA, um item, no período corrente.

    Exige turno aberto: cargo lançado com a caja fechada é fatura que ninguém
    viu nascer.
    """
    from datetime import date

    from app.models.invoice import InvoiceItem
    from app.services.invoice_generation import InvoiceGenerationService

    if body.iva_tasa not in (0, 5, 10):
        raise HTTPException(status_code=422, detail="iva_tasa debe ser 0, 5 o 10")

    try:
        cid = PydanticObjectId(body.client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    # Turno aberto é a regra do balcão inteiro — o cargo nasce dentro dele.
    await _resolver_sesion(current_user, None)

    hoy = date.today()
    item = InvoiceItem(
        descripcion=body.descripcion.strip(),
        cantidad=body.cantidad,
        precio_unitario=body.valor,
        iva_tasa=body.iva_tasa,
        iva_afectacion=body.iva_afectacion,
    )
    result = await InvoiceGenerationService.create_custom_invoice(
        client_id=cid, items=[item],
        mes_referencia=hoy.month, ano_referencia=hoy.year,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    from app.models.invoice import Invoice

    inv = await Invoice.get(result.invoice_id)
    return {
        "id": str(inv.id),
        "numero_factura": inv.numero_factura,
        "valor_total": inv.valor_total,
        "saldo_devedor": inv.saldo_devedor,
        "mes_referencia": inv.mes_referencia,
        "ano_referencia": inv.ano_referencia,
    }


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
