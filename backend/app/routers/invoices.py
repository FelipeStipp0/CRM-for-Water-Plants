"""
Endpoints de faturas.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Annotated, List, Optional

from bson import Decimal128
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.models.client import Client
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType, InvoiceItem
from app.models.payment import Payment
from app.models.finance import CashTransaction
from app.models.sponsor import SponsorDebt
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceResponse,
    InvoiceSummary,
    InvoiceItemResponse,
    InvoiceWithPendingBalance,
    GenerateInvoicesRequest,
    GenerateInvoicesResponse,
)
from app.services.invoice_generation import InvoiceGenerationService

router = APIRouter(dependencies=[Depends(require_scopes("invoices"))])


def _to_decimal(value) -> Decimal:
    """Converte Decimal128 do MongoDB para Decimal do Python."""
    if isinstance(value, Decimal128):
        return value.to_decimal()
    return Decimal(str(value))


def invoice_to_response(invoice: Invoice, client_nombre: Optional[str] = None) -> InvoiceResponse:
    """Converte modelo para schema de resposta."""
    items = [
        InvoiceItemResponse(
            descripcion=item.descripcion,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
            subtotal=item.subtotal,
        )
        for item in invoice.items
    ]

    return InvoiceResponse(
        id=str(invoice.id),
        client_id=str(invoice.client.ref.id),
        client_nombre=client_nombre,
        numero_factura=invoice.numero_factura,
        tipo=invoice.tipo,
        status=invoice.status,
        mes_referencia=invoice.mes_referencia,
        ano_referencia=invoice.ano_referencia,
        fecha_emision=invoice.fecha_emision,
        fecha_vencimiento=invoice.fecha_vencimiento,
        leitura_anterior=invoice.leitura_anterior,
        leitura_actual=invoice.leitura_actual,
        consumo=invoice.consumo,
        tarifa_base=invoice.tarifa_base,
        excedente=invoice.excedente,
        items=items,
        valor_total=invoice.valor_total,
        saldo_devedor=invoice.saldo_devedor,
        created_at=invoice.created_at,
    )


async def _resolve_client_nombre(invoice: Invoice) -> Optional[str]:
    """Resolve o nome do cliente a partir do Link."""
    try:
        client = await invoice.client.fetch()
        return client.nombre_completo if client else None
    except Exception:
        return None


@router.post("/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    invoice_data: InvoiceCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Cria uma fatura avulsa com itens personalizados.
    Para faturas de consumo, use o endpoint /generate.
    """
    try:
        client_id = PydanticObjectId(invoice_data.client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    if invoice_data.tipo != InvoiceType.AVULSA:
        raise HTTPException(
            status_code=400,
            detail="Use POST /invoices/generate para faturas de consumo"
        )

    if not invoice_data.items:
        raise HTTPException(status_code=400, detail="Fatura avulsa deve ter itens")

    items = [
        InvoiceItem(
            descripcion=item.descripcion,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
        )
        for item in invoice_data.items
    ]

    result = await InvoiceGenerationService.create_custom_invoice(
        client_id=client_id,
        items=items,
        mes_referencia=invoice_data.mes_referencia,
        ano_referencia=invoice_data.ano_referencia,
        fecha_vencimiento=invoice_data.fecha_vencimiento,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    invoice = await Invoice.get(result.invoice_id)
    client_nombre = await _resolve_client_nombre(invoice)
    return invoice_to_response(invoice, client_nombre)


@router.post("/generate", response_model=GenerateInvoicesResponse)
async def generate_invoices(
    request: GenerateInvoicesRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Gera faturas de consumo em lote para um periodo.
    Baseado nas leituras ja cadastradas.

    Se gerar_sem_leitura_valor_minimo=True, tambem gera faturas
    de valor minimo para clientes ativos sem leitura.
    """
    client_ids = None
    if request.client_ids:
        try:
            client_ids = [PydanticObjectId(cid) for cid in request.client_ids]
        except Exception:
            raise HTTPException(status_code=400, detail="client_ids invalidos")

    result = await InvoiceGenerationService.generate_batch(
        mes=request.mes_referencia,
        ano=request.ano_referencia,
        client_ids=client_ids,
        gerar_sem_leitura_valor_minimo=request.gerar_sem_leitura_valor_minimo,
        dia_geracao=request.dia_geracao,
    )

    return GenerateInvoicesResponse(
        total_generated=result.total_generated,
        total_skipped=result.total_skipped,
        total_minimum_generated=result.total_minimum_generated,
        total_minimum_skipped=result.total_minimum_skipped,
        errors=result.errors,
    )


@router.get("/", response_model=List[InvoiceSummary])
async def list_invoices(
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista faturas com filtros."""
    match_filter: dict = {}
    if status_filter:
        match_filter["status"] = status_filter.value
    if mes:
        match_filter["mes_referencia"] = mes
    if ano:
        match_filter["ano_referencia"] = ano

    collection = Invoice.get_pymongo_collection()

    total = await collection.count_documents(match_filter)
    response.headers["X-Total-Count"] = str(total)

    pipeline = [
        {"$match": match_filter} if match_filter else {"$match": {}},
        {"$sort": {"numero_factura": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {"$lookup": {
            "from": "clients",
            "localField": "client.$id",
            "foreignField": "_id",
            "as": "_client",
        }},
        {"$unwind": {"path": "$_client", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {"client_nombre": "$_client.nombre_completo"}},
    ]

    cursor = collection.aggregate(pipeline)
    docs = await cursor.to_list(length=None)

    return [
        InvoiceSummary(
            id=str(doc["_id"]),
            client_id=str(doc["_client"]["_id"]) if doc.get("_client") else None,
            client_nombre=doc.get("client_nombre"),
            numero_factura=doc.get("numero_factura"),
            mes_referencia=doc["mes_referencia"],
            ano_referencia=doc["ano_referencia"],
            tipo=doc["tipo"],
            status=doc["status"],
            valor_total=_to_decimal(doc["valor_total"]),
            saldo_devedor=_to_decimal(doc["saldo_devedor"]),
            fecha_vencimiento=doc["fecha_vencimiento"],
        )
        for doc in docs
    ]


@router.get("/by-number/{numero}", response_model=InvoiceSummary)
async def get_invoice_by_number(
    numero: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Busca fatura pelo número (numero_factura)."""
    collection = Invoice.get_pymongo_collection()
    pipeline = [
        {"$match": {"numero_factura": numero}},
        {"$limit": 1},
        {"$lookup": {
            "from": "clients",
            "localField": "client.$id",
            "foreignField": "_id",
            "as": "_client",
        }},
        {"$unwind": {"path": "$_client", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {"client_nombre": "$_client.nombre_completo"}},
    ]
    docs = await collection.aggregate(pipeline).to_list(length=1)
    if not docs:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")
    doc = docs[0]
    return InvoiceSummary(
        id=str(doc["_id"]),
        client_nombre=doc.get("client_nombre"),
        numero_factura=doc.get("numero_factura"),
        mes_referencia=doc["mes_referencia"],
        ano_referencia=doc["ano_referencia"],
        tipo=doc["tipo"],
        status=doc["status"],
        valor_total=_to_decimal(doc["valor_total"]),
        saldo_devedor=_to_decimal(doc["saldo_devedor"]),
        fecha_vencimiento=doc["fecha_vencimiento"],
    )


@router.get("/pending", response_model=List[InvoiceSummary])
async def list_pending_invoices(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(100, ge=1, le=500),
):
    """Lista faturas pendentes ordenadas por vencimento."""
    pipeline = [
        {"$match": {"status": {"$in": [InvoiceStatus.PENDENTE.value, InvoiceStatus.PARCIAL.value]}}},
        {"$sort": {"fecha_vencimiento": 1}},
        {"$limit": limit},
        {"$lookup": {
            "from": "clients",
            "localField": "client.$id",
            "foreignField": "_id",
            "as": "_client",
        }},
        {"$unwind": {"path": "$_client", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {"client_nombre": "$_client.nombre_completo"}},
    ]

    collection = Invoice.get_pymongo_collection()
    cursor = collection.aggregate(pipeline)
    docs = await cursor.to_list(length=None)

    return [
        InvoiceSummary(
            id=str(doc["_id"]),
            client_id=str(doc["_client"]["_id"]) if doc.get("_client") else None,
            client_nombre=doc.get("client_nombre"),
            numero_factura=doc.get("numero_factura"),
            mes_referencia=doc["mes_referencia"],
            ano_referencia=doc["ano_referencia"],
            tipo=doc["tipo"],
            status=doc["status"],
            valor_total=_to_decimal(doc["valor_total"]),
            saldo_devedor=_to_decimal(doc["saldo_devedor"]),
            fecha_vencimiento=doc["fecha_vencimiento"],
        )
        for doc in docs
    ]


@router.get("/client/{client_id}", response_model=List[InvoiceResponse])
async def get_client_invoices(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    limit: int = Query(24, ge=1, le=100),
):
    """Retorna faturas de um cliente."""
    try:
        cid = PydanticObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    client = await Client.get(cid)
    client_nombre = client.nombre_completo if client else None

    query = Invoice.find({"client.$id": cid})

    if status_filter:
        query = query.find(Invoice.status == status_filter)

    invoices = await query.sort([
        ("ano_referencia", -1),
        ("mes_referencia", -1)
    ]).limit(limit).to_list()

    return [invoice_to_response(inv, client_nombre) for inv in invoices]


@router.get("/client/{client_id}/pending-balance")
async def get_client_pending_balance(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Retorna o saldo pendente total de um cliente.
    Util para calcular "Saldo Pendente Anterior" no PDF.
    """
    try:
        cid = PydanticObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    invoices = await Invoice.find(
        {"client.$id": cid},
        Invoice.saldo_devedor > 0,
        Invoice.status != InvoiceStatus.ANULADA,
    ).to_list()

    total = sum(inv.saldo_devedor for inv in invoices)
    count = len(invoices)

    return {
        "client_id": client_id,
        "saldo_pendiente": total,
        "facturas_pendientes": count,
    }


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna uma fatura pelo ID."""
    try:
        invoice = await Invoice.get(PydanticObjectId(invoice_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    client_nombre = await _resolve_client_nombre(invoice)
    return invoice_to_response(invoice, client_nombre)


@router.get("/{invoice_id}/with-balance", response_model=InvoiceWithPendingBalance)
async def get_invoice_with_balance(
    invoice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Retorna fatura com saldo pendente anterior calculado.
    Para uso na geracao de PDF com visualizacao hibrida.
    """
    try:
        invoice = await Invoice.get(PydanticObjectId(invoice_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    # Busca faturas anteriores pendentes
    pending_before = await Invoice.find(
        {"client.$id": invoice.client.ref.id},
        Invoice.saldo_devedor > 0,
        Invoice.status != InvoiceStatus.ANULADA,
        {"$or": [
            {"ano_referencia": {"$lt": invoice.ano_referencia}},
            {"$and": [
                {"ano_referencia": invoice.ano_referencia},
                {"mes_referencia": {"$lt": invoice.mes_referencia}}
            ]}
        ]}
    ).to_list()

    saldo_anterior = sum(inv.saldo_devedor for inv in pending_before)

    client_nombre = await _resolve_client_nombre(invoice)
    base_response = invoice_to_response(invoice, client_nombre)

    return InvoiceWithPendingBalance(
        **base_response.model_dump(),
        saldo_pendiente_anterior=saldo_anterior,
        total_a_pagar=invoice.saldo_devedor + saldo_anterior,
    )


@router.patch("/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(
    invoice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Anula uma fatura."""
    try:
        invoice = await Invoice.get(PydanticObjectId(invoice_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    if invoice.status == InvoiceStatus.PAGADA:
        raise HTTPException(
            status_code=400,
            detail="Nao e possivel anular fatura ja paga"
        )

    await invoice.update({
        "$set": {
            "status": InvoiceStatus.ANULADA,
            "saldo_devedor": Decimal("0"),
            "updated_at": datetime.utcnow(),
        }
    })
    await invoice.sync()

    client_nombre = await _resolve_client_nombre(invoice)
    return invoice_to_response(invoice, client_nombre)


@router.delete("/{invoice_id}", status_code=status.HTTP_200_OK)
async def delete_invoice(
    invoice_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Deleta uma fatura e reverte todos os pagamentos associados.

    Para cada pagamento que tocou esta fatura:
    - Reverte alocacoes em OUTRAS faturas (restaura saldo_devedor e status)
    - Remove CashTransaction associada
    - Remove SponsorDebts associados
    - Remove o pagamento
    Por fim, remove a fatura.
    """
    try:
        invoice = await Invoice.get(PydanticObjectId(invoice_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura nao encontrada")

    inv_oid = invoice.id
    payments_deleted = 0
    invoices_reverted = 0

    # Busca todos os pagamentos que tem alocacao nesta fatura
    payments = await Payment.find(
        {"allocations.invoice_id": inv_oid}
    ).to_list()

    for payment in payments:
        # Reverte alocacoes em OUTRAS faturas afetadas por este pagamento
        for alloc in payment.allocations:
            if alloc.invoice_id == inv_oid:
                continue  # Pula a fatura que sera deletada

            other_invoice = await Invoice.get(alloc.invoice_id)
            if other_invoice:
                new_saldo = other_invoice.saldo_devedor + alloc.valor_aplicado
                new_status = (
                    InvoiceStatus.PENDENTE
                    if new_saldo >= other_invoice.valor_total
                    else InvoiceStatus.PARCIAL
                )
                await other_invoice.update({
                    "$set": {
                        "saldo_devedor": new_saldo,
                        "status": new_status.value,
                        "updated_at": datetime.utcnow(),
                    }
                })
                invoices_reverted += 1

        # Remove CashTransactions vinculadas a este pagamento
        await CashTransaction.find(
            CashTransaction.reference_id == payment.id,
            CashTransaction.reference_type == "payment",
        ).delete()

        # Remove SponsorDebts vinculados a este pagamento
        await SponsorDebt.find(
            SponsorDebt.payment_id == payment.id,
        ).delete()

        # Remove o pagamento
        await payment.delete()
        payments_deleted += 1

    # Remove a fatura
    await invoice.delete()

    return {
        "detail": "Fatura e pagamentos associados removidos",
        "invoice_id": invoice_id,
        "payments_deleted": payments_deleted,
        "invoices_reverted": invoices_reverted,
    }
