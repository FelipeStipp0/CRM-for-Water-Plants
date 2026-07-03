"""
Endpoints de Sponsor/Subsidio.

Permite:
- Listar sponsors (clientes que tem subsidiados)
- Ver clientes subsidiados por um sponsor
- Consultar dividas pendentes
- Gerar fatura agregada mensal
- Pagar fatura agregada
"""

from decimal import Decimal
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.client import Client
from app.models.user import User
from app.models.sponsor import SponsorDebt, SponsorDebtStatus, SponsorInvoice
from app.routers.auth import get_current_active_user, require_scopes
from app.routers.clients import client_to_response
from app.schemas.client import ClientResponse
from app.schemas.sponsor import (
    SponsorDebtResponse,
    SponsorSummaryResponse,
    SponsorInvoiceResponse,
    GenerateInvoiceRequest,
    PaySponsorInvoiceRequest,
)
from app.services.sponsor_service import SponsorService

router = APIRouter(dependencies=[Depends(require_scopes("sponsors", "finance"))])


# ---------- Helpers ----------

def _debt_to_response(debt: SponsorDebt, client_name: str = None) -> SponsorDebtResponse:
    """Converte SponsorDebt em response."""
    sponsor_id = debt.sponsor.ref.id if hasattr(debt.sponsor, 'ref') else debt.sponsor
    client_id = debt.client_original.ref.id if hasattr(debt.client_original, 'ref') else debt.client_original
    return SponsorDebtResponse(
        id=str(debt.id),
        sponsor_id=str(sponsor_id),
        client_original_id=str(client_id),
        client_original_name=client_name,
        invoice_id=str(debt.invoice_id),
        mes_referencia=debt.mes_referencia,
        ano_referencia=debt.ano_referencia,
        valor_subsidio=debt.valor_subsidio,
        porcentagem_aplicada=debt.porcentagem_aplicada,
        payment_id=str(debt.payment_id),
        status=debt.status.value if hasattr(debt.status, 'value') else debt.status,
        fatura_agregada_id=str(debt.fatura_agregada_id) if debt.fatura_agregada_id else None,
        created_at=debt.created_at,
    )


def _invoice_to_response(inv: SponsorInvoice) -> SponsorInvoiceResponse:
    """Converte SponsorInvoice em response."""
    sponsor_id = inv.sponsor.ref.id if hasattr(inv.sponsor, 'ref') else inv.sponsor
    return SponsorInvoiceResponse(
        id=str(inv.id),
        sponsor_id=str(sponsor_id),
        mes_referencia=inv.mes_referencia,
        ano_referencia=inv.ano_referencia,
        debts_included=[str(d) for d in inv.debts_included],
        valor_total=inv.valor_total,
        saldo_devedor=inv.saldo_devedor,
        status=inv.status,
        fecha_emision=inv.fecha_emision,
        fecha_pago=inv.fecha_pago,
    )


# ---------- Endpoints ----------

@router.get("/", response_model=List[ClientResponse])
async def list_sponsors(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Lista todos os clientes que sao sponsors (tem pelo menos um subsidiado).
    """
    # Busca IDs unicos de sponsors
    pipeline = [
        {"$match": {"sponsor_id": {"$ne": None}}},
        {"$group": {"_id": "$sponsor_id"}},
    ]
    cursor = Client.get_pymongo_collection().aggregate(pipeline)
    sponsor_ids_docs = await cursor.to_list(length=500)
    sponsor_ids = [doc["_id"] for doc in sponsor_ids_docs]

    if not sponsor_ids:
        return []

    # Batch fetch: busca todos os sponsors de uma vez
    sponsors = await Client.find({"_id": {"$in": sponsor_ids}}).to_list()
    return [client_to_response(s) for s in sponsors]


@router.get("/{sponsor_id}/clients", response_model=List[ClientResponse])
async def list_sponsor_clients(
    sponsor_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna todos os clientes subsidiados por este sponsor."""
    try:
        oid = PydanticObjectId(sponsor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID invalido")

    clients = await SponsorService.get_sponsor_clients(oid)
    return [client_to_response(c) for c in clients]


@router.get("/{sponsor_id}/summary", response_model=SponsorSummaryResponse)
async def get_sponsor_summary(
    sponsor_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna resumo financeiro do sponsor."""
    try:
        oid = PydanticObjectId(sponsor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID invalido")

    try:
        summary = await SponsorService.get_sponsor_summary(oid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return SponsorSummaryResponse(
        sponsor_id=str(summary.sponsor_id),
        sponsor_name=summary.sponsor_name,
        total_pendente=summary.total_pendente,
        total_faturado=summary.total_faturado,
        total_pago=summary.total_pago,
        count_debts=summary.count_debts,
    )


@router.get("/{sponsor_id}/debts", response_model=List[SponsorDebtResponse])
async def list_sponsor_debts(
    sponsor_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[str] = Query(None, alias="status"),
    mes: Optional[int] = None,
    ano: Optional[int] = None,
):
    """
    Lista dividas de subsidio do sponsor.

    Query params:
    - status: PENDENTE, FATURADO, PAGO
    - mes: filtrar por mes
    - ano: filtrar por ano
    """
    try:
        oid = PydanticObjectId(sponsor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID invalido")

    query = {"sponsor.$id": oid}
    if status_filter:
        query["status"] = status_filter
    if mes is not None:
        query["mes_referencia"] = mes
    if ano is not None:
        query["ano_referencia"] = ano

    debts = await SponsorDebt.find(query).sort("-created_at").limit(200).to_list()

    if not debts:
        return []

    # Batch fetch: busca todos os clientes originais de uma vez
    client_ids = set()
    for debt in debts:
        cid = debt.client_original.ref.id if hasattr(debt.client_original, 'ref') else debt.client_original
        client_ids.add(cid)

    clients_list = await Client.find({"_id": {"$in": list(client_ids)}}).to_list()
    clients_map = {c.id: c.nombre_completo for c in clients_list}

    results = []
    for debt in debts:
        cid = debt.client_original.ref.id if hasattr(debt.client_original, 'ref') else debt.client_original
        results.append(_debt_to_response(debt, clients_map.get(cid)))

    return results


@router.get("/{sponsor_id}/invoices", response_model=List[SponsorInvoiceResponse])
async def list_sponsor_invoices(
    sponsor_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """Lista faturas agregadas do sponsor."""
    try:
        oid = PydanticObjectId(sponsor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID invalido")

    invoices = await SponsorService.list_sponsor_invoices(
        oid, status=status_filter
    )
    return [_invoice_to_response(inv) for inv in invoices]


@router.post("/{sponsor_id}/invoices/generate", response_model=SponsorInvoiceResponse)
async def generate_aggregated_invoice(
    sponsor_id: str,
    body: GenerateInvoiceRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Gera fatura agregada mensal para o sponsor.

    Consolida todas as SponsorDebts PENDENTES em uma unica fatura.
    """
    try:
        oid = PydanticObjectId(sponsor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID invalido")

    result = await SponsorService.generate_aggregated_invoice(
        sponsor_id=oid,
        mes_referencia=body.mes_referencia,
        ano_referencia=body.ano_referencia,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    invoice = await SponsorInvoice.get(result.invoice_id)
    return _invoice_to_response(invoice)


@router.post("/invoices/{invoice_id}/pay")
async def pay_sponsor_invoice(
    invoice_id: str,
    body: PaySponsorInvoiceRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Paga fatura agregada do sponsor.

    Aceita pagamento parcial ou total.
    Se total quitado, marca todas as debts como PAGO.
    """
    try:
        oid = PydanticObjectId(invoice_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID invalido")

    result = await SponsorService.pay_sponsor_invoice(
        invoice_id=oid,
        valor=body.valor,
        recibido_por=body.recibido_por,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Erro desconhecido"),
        )

    return result
