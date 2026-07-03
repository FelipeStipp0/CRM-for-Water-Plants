"""
Endpoints de pagamentos.
"""

from decimal import Decimal
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.models.client import Client
from app.models.payment import Payment
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentResult,
    AllocationDetail,
    PaymentHistory,
)
from app.services.payment_distribution import PaymentDistributionService

router = APIRouter(dependencies=[Depends(require_scopes("payments"))])


def payment_to_response(payment: Payment) -> PaymentResponse:
    """Converte modelo para schema de resposta."""
    allocations = [
        AllocationDetail(
            invoice_id=str(alloc.invoice_id),
            mes_referencia=alloc.mes_referencia,
            ano_referencia=alloc.ano_referencia,
            valor_original=Decimal("0"),  # Preenchido quando necessario
            saldo_anterior=Decimal("0"),
            valor_aplicado=alloc.valor_aplicado,
            saldo_restante=Decimal("0"),
            status_final="",
        )
        for alloc in payment.allocations
    ]

    return PaymentResponse(
        id=str(payment.id),
        client_id=str(payment.client.ref.id),
        valor_total=payment.valor_total,
        metodo=payment.metodo,
        grupo_pagamento=payment.grupo_pagamento,
        numero_recibo=payment.numero_recibo,
        recibido_por=payment.recibido_por,
        observacion=payment.observacion,
        fecha_pago=payment.fecha_pago,
        allocations=allocations,
    )


@router.post("/", response_model=PaymentResult, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_data: PaymentCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Processa um pagamento com distribuicao automatica.

    O valor sera distribuido entre as faturas pendentes do cliente,
    da mais antiga para a mais recente.

    Retorna detalhes completos incluindo faturas afetadas (para impressao).
    """
    try:
        client_id = PydanticObjectId(payment_data.client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    # Busca cliente para dados do recibo
    client = await Client.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    # Calcula divida antes do pagamento
    debt_before = await PaymentDistributionService.calculate_total_debt(client_id)

    # Processa pagamento
    result = await PaymentDistributionService.process_payment(
        client_id=client_id,
        valor_total=payment_data.valor_total,
        metodo=payment_data.metodo,
        aplicar_subsidio=payment_data.aplicar_subsidio,
        recibido_por=payment_data.recibido_por or current_user.full_name,
        observacion=payment_data.observacion,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # Busca pagamento criado
    payment = await Payment.get(result.payment_id)

    # Monta resposta detalhada com info de subsidio
    allocations_detail = [
        AllocationDetail(
            invoice_id=str(alloc.invoice_id),
            mes_referencia=alloc.mes_referencia,
            ano_referencia=alloc.ano_referencia,
            valor_original=alloc.valor_original,
            saldo_anterior=alloc.saldo_anterior,
            valor_aplicado=alloc.valor_aplicado,
            saldo_restante=alloc.saldo_restante,
            status_final=alloc.status_final.value,
            subsidio_transferido=alloc.subsidio_transferido,
            sponsor_debt_id=str(alloc.sponsor_debt_id) if alloc.sponsor_debt_id else None,
        )
        for alloc in result.allocations
    ]

    payment_response = PaymentResponse(
        id=str(payment.id),
        client_id=str(client.id),
        valor_total=payment.valor_total,
        metodo=payment.metodo,
        grupo_pagamento=payment.grupo_pagamento,
        numero_recibo=payment.numero_recibo,
        recibido_por=payment.recibido_por,
        observacion=payment.observacion,
        fecha_pago=payment.fecha_pago,
        allocations=allocations_detail,
    )

    # Resolve nome do sponsor se subsidio foi aplicado
    sponsor_name = None
    if result.total_subsidio > 0 and client.sponsor_id:
        sponsor = await Client.get(client.sponsor_id)
        if sponsor:
            sponsor_name = sponsor.nombre_completo

    return PaymentResult(
        payment=payment_response,
        client_name=client.nombre_completo,
        client_ci_ruc=client.ci_ruc,
        invoices_affected=allocations_detail,
        total_debt_before=debt_before,
        total_debt_after=debt_before - result.total_applied,
        overpayment=result.overpayment,
        subsidio_aplicado=result.total_subsidio > 0,
        total_subsidio=result.total_subsidio,
        sponsor_name=sponsor_name,
        reactivation_notice_id=str(result.reactivation_notice_id) if result.reactivation_notice_id else None,
        reactivation_qr_token=result.reactivation_qr_token,
        reactivation_comprobante=result.reactivation_comprobante,
    )


@router.get("/", response_model=List[PaymentHistory])
async def list_payments(
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista pagamentos recentes."""
    total = await Payment.find().count()
    response.headers["X-Total-Count"] = str(total)

    payments = await Payment.find().skip(skip).limit(limit).sort("-fecha_pago").to_list()

    if not payments:
        return []

    # Batch fetch clientes
    client_ids = list({
        p.client.ref.id if hasattr(p.client, 'ref') else p.client.id
        for p in payments
    })
    clients_list = await Client.find({"_id": {"$in": client_ids}}).to_list()
    clients_map = {c.id: c for c in clients_list}

    result = []
    for p in payments:
        cid = p.client.ref.id if hasattr(p.client, 'ref') else p.client.id
        client = clients_map.get(cid)
        result.append(PaymentHistory(
            id=str(p.id),
            client_id=str(cid),
            client_name=client.nombre_completo if client else "Desconocido",
            valor_total=p.valor_total,
            metodo=p.metodo,
            fecha_pago=p.fecha_pago,
            invoices_count=len(p.allocations),
        ))

    return result


@router.get("/client/{client_id}", response_model=List[PaymentResponse])
async def get_client_payments(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(24, ge=1, le=100),
):
    """Retorna historico de pagamentos de um cliente."""
    try:
        cid = PydanticObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    payments = await Payment.find(
        {"client.$id": cid}
    ).sort("-fecha_pago").limit(limit).to_list()

    return [payment_to_response(p) for p in payments]


@router.get("/by-group/{grupo}", response_model=PaymentResult)
async def get_payment_by_group(
    grupo: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Retorna detalhes de um pagamento pelo grupo.
    Util para reimprimir recibos.
    """
    payment = await Payment.find_one(Payment.grupo_pagamento == grupo)

    if not payment:
        raise HTTPException(status_code=404, detail="Pagamento nao encontrado")

    client = await payment.client.fetch()

    # Batch fetch: busca todas as faturas das alocacoes de uma vez
    from app.models.invoice import Invoice
    invoice_ids = [alloc.invoice_id for alloc in payment.allocations]
    invoices_list = await Invoice.find({"_id": {"$in": invoice_ids}}).to_list()
    invoices_map = {inv.id: inv for inv in invoices_list}

    allocations_detail = []
    for alloc in payment.allocations:
        invoice = invoices_map.get(alloc.invoice_id)
        if invoice:
            allocations_detail.append(AllocationDetail(
                invoice_id=str(alloc.invoice_id),
                mes_referencia=alloc.mes_referencia,
                ano_referencia=alloc.ano_referencia,
                valor_original=invoice.valor_total,
                saldo_anterior=alloc.valor_aplicado + invoice.saldo_devedor,
                valor_aplicado=alloc.valor_aplicado,
                saldo_restante=invoice.saldo_devedor,
                status_final=invoice.status.value,
            ))

    payment_response = PaymentResponse(
        id=str(payment.id),
        client_id=str(client.id),
        valor_total=payment.valor_total,
        metodo=payment.metodo,
        grupo_pagamento=payment.grupo_pagamento,
        numero_recibo=payment.numero_recibo,
        recibido_por=payment.recibido_por,
        observacion=payment.observacion,
        fecha_pago=payment.fecha_pago,
        allocations=allocations_detail,
    )

    return PaymentResult(
        payment=payment_response,
        client_name=client.nombre_completo,
        client_ci_ruc=client.ci_ruc,
        invoices_affected=allocations_detail,
        total_debt_before=Decimal("0"),  # Nao disponivel em consulta
        total_debt_after=Decimal("0"),
        overpayment=Decimal("0"),
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna um pagamento pelo ID."""
    try:
        payment = await Payment.get(PydanticObjectId(payment_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Pagamento nao encontrado")

    if not payment:
        raise HTTPException(status_code=404, detail="Pagamento nao encontrado")

    return payment_to_response(payment)
