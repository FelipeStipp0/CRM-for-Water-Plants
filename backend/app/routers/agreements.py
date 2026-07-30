"""
Endpoints do acordo de pagamento (parcelamento no balcão).

Quem fecha acordo é quem está no caixa, então o router aceita os mesmos escopos
do Modo Caja — não existe "a tesouraria aprova depois".
"""

from decimal import Decimal
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.agreement import AgreementStatus, PaymentAgreement
from app.models.payment import PaymentMethod
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.services.agreement_service import (
    AgreementError,
    acuerdo_to_dict,
    crear_acuerdo,
    dividir_parcelas,
)

router = APIRouter(dependencies=[Depends(require_scopes("caja", "payments", "finance"))])


class AcuerdoCreate(BaseModel):
    client_id: str
    n_parcelas: int = Field(ge=1, le=60, description="Número de cuotas — lo decide el cajero")
    invoice_ids: Optional[List[str]] = Field(
        default=None,
        description="Facturas que entran. Vacío = toda la deuda en abierto.")
    entrada: Decimal = Field(default=Decimal("0"), ge=0,
                             description="Pago en el acto; reduce el total antes de dividir")
    metodo: PaymentMethod = PaymentMethod.EFECTIVO
    primera_en_mes_corriente: bool = Field(
        default=False,
        description="Primera cuota en el mes corriente (como AVULSA) o en el siguiente")
    cuota_iva_tasa: int = Field(default=10, description="0, 5 o 10")
    cuota_iva_afectacion: int = Field(default=1, description="1=Gravado, 2=Parcial, 3=Exento")
    aplicar_subsidio: Optional[bool] = None
    observacion: Optional[str] = None


class SimulacionRequest(BaseModel):
    total: Decimal = Field(gt=0)
    n_parcelas: int = Field(ge=1, le=60)
    entrada: Decimal = Field(default=Decimal("0"), ge=0)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear(
    body: AcuerdoCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Fecha um acordo: anula as faturas antigas e agenda as parcelas.

    Se o cliente já tem um acordo ATIVO, este **refaz** o acordo — junta o saldo
    remanescente com a dívida nova, e o antigo fica REFEITO.
    """
    try:
        cid = PydanticObjectId(body.client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    invoice_ids = None
    if body.invoice_ids:
        try:
            invoice_ids = [PydanticObjectId(i) for i in body.invoice_ids]
        except Exception:
            raise HTTPException(status_code=400, detail="invoice_ids invalido")

    if body.cuota_iva_tasa not in (0, 5, 10):
        raise HTTPException(status_code=400, detail="La tasa de IVA debe ser 0, 5 o 10")
    if body.cuota_iva_afectacion not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Afectación de IVA inválida")

    try:
        return await crear_acuerdo(
            client_id=cid,
            invoice_ids=invoice_ids,
            n_parcelas=body.n_parcelas,
            usuario=current_user.username,
            entrada=body.entrada,
            metodo=body.metodo,
            primera_en_mes_corriente=body.primera_en_mes_corriente,
            cuota_iva_tasa=body.cuota_iva_tasa,
            cuota_iva_afectacion=body.cuota_iva_afectacion,
            aplicar_subsidio=body.aplicar_subsidio,
            recibido_por=current_user.full_name or current_user.username,
            observacion=body.observacion,
        )
    except AgreementError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/simular")
async def simular(
    body: SimulacionRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Cronograma sem gravar nada — o cajero mostra ao cliente antes de decidir.

    Mesma divisão que o fechamento usa (última parcela absorve a sobra), para a
    prévia nunca divergir do que vai ser cobrado.
    """
    restante = Decimal(str(body.total)) - Decimal(str(body.entrada))
    if restante <= 0:
        raise HTTPException(
            status_code=400,
            detail="La entrada cubre todo: cobralo como pago normal, sin acuerdo.")
    try:
        valores = dividir_parcelas(restante, body.n_parcelas)
    except AgreementError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"total_parcelado": restante, "n_parcelas": body.n_parcelas,
            "valores": valores}


@router.get("/client/{client_id}")
async def por_cliente(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(10, ge=1, le=50),
):
    """Acordos do cliente (o ATIVO primeiro, depois o histórico)."""
    try:
        cid = PydanticObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    acuerdos = await PaymentAgreement.find(
        {"client.$id": cid}).sort("-numero").limit(limit).to_list()
    activo = next((a for a in acuerdos if a.status == AgreementStatus.ACTIVO), None)
    return {
        "activo": acuerdo_to_dict(activo) if activo else None,
        "historico": [acuerdo_to_dict(a) for a in acuerdos],
    }


@router.get("/{agreement_id}")
async def detalle(
    agreement_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Um acordo com as faturas antigas resolvidas — é o que se imprime quando a
    dívida acaba, junto do recibo da última parcela.
    """
    try:
        ac = await PaymentAgreement.get(PydanticObjectId(agreement_id))
    except Exception:
        ac = None
    if not ac:
        raise HTTPException(status_code=404, detail="Acuerdo no encontrado")

    client = await ac.client.fetch() if hasattr(ac.client, "fetch") else ac.client
    data = acuerdo_to_dict(ac)
    data["client"] = {
        "id": str(client.id),
        "nombre_completo": client.nombre_completo,
        "ci_ruc": client.ci_ruc,
        "numero_medidor": client.numero_medidor,
    } if client else None
    return data
