"""
Endpoints de clientes.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.models.client import Client, ClientStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.settings import SystemSettings
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.schemas.client import (
    ClientCreate,
    ClientUpdate,
    ClientResponse,
    ClientSearch,
    ClientWithDebt,
)

router = APIRouter(dependencies=[Depends(require_scopes("clients"))])


def client_to_response(client: Client) -> ClientResponse:
    """Converte modelo para schema de resposta."""
    return ClientResponse(
        id=str(client.id),
        nombre_completo=client.nombre_completo,
        ci_ruc=client.ci_ruc,
        telefono=client.telefono,
        celular=client.celular,
        direccion=client.direccion,
        manzana=client.manzana,
        lote=client.lote,
        numero_medidor=client.numero_medidor,
        categoria=client.categoria,
        status=client.status,
        titular_id=str(client.titular_id) if client.titular_id else None,
        is_sponsor=client.is_sponsor,
        sponsor_id=str(client.sponsor_id) if client.sponsor_id else None,
        subsidio_porcentagem=client.subsidio_porcentagem,
        is_aluguel=client.is_aluguel,
        has_sponsor=client.has_sponsor,
        instalacao_latitude=client.instalacao_latitude,
        instalacao_longitude=client.instalacao_longitude,
        foto_medidor_url=client.foto_medidor_url,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


async def _validate_sponsor_id(sponsor_id_str: str) -> PydanticObjectId:
    """Valida que sponsor_id aponta para um cliente com is_sponsor=True."""
    try:
        oid = PydanticObjectId(sponsor_id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="sponsor_id invalido")

    sponsor = await Client.get(oid)
    if not sponsor:
        raise HTTPException(status_code=400, detail="Sponsor nao encontrado")
    if not sponsor.is_sponsor:
        raise HTTPException(
            status_code=400,
            detail=f"Cliente '{sponsor.nombre_completo}' nao esta marcado como sponsor"
        )
    return oid


@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    client_data: ClientCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria um novo cliente."""
    # Verifica duplicata de CI/RUC
    existing = await Client.find_one({"ci_ruc": client_data.ci_ruc})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CI/RUC ja cadastrado"
        )

    # Verifica duplicata de numero_medidor
    if client_data.numero_medidor:
        existing_medidor = await Client.find_one({"numero_medidor": client_data.numero_medidor})
        if existing_medidor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Numero de medidor ja cadastrado"
            )

    # Valida e converte sponsor_id
    data = client_data.model_dump()
    if data.get("sponsor_id"):
        data["sponsor_id"] = await _validate_sponsor_id(data["sponsor_id"])

    client = Client(**data)
    await client.insert()

    return client_to_response(client)


@router.get("/", response_model=List[ClientResponse])
async def list_clients(
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[ClientStatus] = None,
):
    """Lista clientes com paginacao."""
    query = Client.find()

    if status:
        query = query.find(Client.status == status)

    total = await query.count()
    clients = await query.skip(skip).limit(limit).sort("nombre_completo").to_list()

    response.headers["X-Total-Count"] = str(total)
    return [client_to_response(c) for c in clients]


@router.get("/search", response_model=List[ClientResponse])
async def search_clients(
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    q: Optional[str] = Query(None, min_length=2),
    manzana: Optional[str] = None,
    lote: Optional[str] = None,
    is_sponsor: Optional[bool] = Query(None),
    is_aluguel: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """
    Busca clientes por nome, CI/RUC, medidor ou localizacao.
    Filtros opcionais: is_sponsor, is_aluguel.

    `X-Total-Count` traz o total que casa com a busca, nao so os devolvidos: quem
    chama com `limit` baixo (o Modo Caja usa 20) precisa poder dizer "20 de 137"
    em vez de esconder o resto sem avisar.
    """
    filters = []

    if q:
        # Busca em multiplos campos
        filters.append({
            "$or": [
                {"nombre_completo": {"$regex": q, "$options": "i"}},
                {"ci_ruc": {"$regex": q, "$options": "i"}},
                {"numero_medidor": {"$regex": q, "$options": "i"}},
            ]
        })

    if manzana:
        filters.append({"manzana": manzana})

    if lote:
        filters.append({"lote": lote})

    if is_sponsor is not None:
        filters.append({"is_sponsor": is_sponsor})

    if is_aluguel is not None:
        filters.append({"is_aluguel": is_aluguel})

    if filters:
        query = Client.find({"$and": filters})
    else:
        query = Client.find()

    total = await query.count()
    clients = await query.limit(limit).to_list()

    response.headers["X-Total-Count"] = str(total)
    return [client_to_response(c) for c in clients]


@router.get("/by-route", response_model=List[ClientResponse])
async def list_by_route(
    current_user: Annotated[User, Depends(get_current_active_user)],
    manzana: Optional[str] = None,
):
    """
    Lista clientes ordenados por rota (Manzana -> Lote).
    Util para leituristas e entregadores.
    """
    query = Client.find(Client.status == ClientStatus.ATIVO)

    if manzana:
        query = query.find(Client.manzana == manzana)

    clients = await query.sort([("manzana", 1), ("lote", 1)]).to_list()

    return [client_to_response(c) for c in clients]


@router.get("/with-debt", response_model=List[ClientWithDebt])
async def list_clients_with_debt(
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(100, ge=1, le=500),
):
    """Lista clientes com dividas pendentes."""
    # Agregacao para calcular divida por cliente
    pipeline = [
        {"$match": {"status": {"$ne": InvoiceStatus.PAGADA.value}}},
        {"$group": {
            "_id": "$client.$id",
            "saldo_pendiente": {"$sum": "$saldo_devedor"},
            "facturas_pendientes": {"$sum": 1}
        }},
        {"$match": {"saldo_pendiente": {"$gt": 0}}},
        {"$sort": {"saldo_pendiente": -1}},
        {"$limit": limit}
    ]

    cursor = Invoice.get_pymongo_collection().aggregate(pipeline)
    debts = await cursor.to_list(length=limit)

    if not debts:
        return []

    # Batch fetch: busca todos os clientes de uma vez
    client_ids = [debt["_id"] for debt in debts]
    clients_list = await Client.find({"_id": {"$in": client_ids}}).to_list()
    clients_map = {c.id: c for c in clients_list}

    results = []
    for debt in debts:
        client = clients_map.get(debt["_id"])
        if client:
            resp = ClientWithDebt(
                **client_to_response(client).model_dump(),
                saldo_pendiente=Decimal(str(debt["saldo_pendiente"])),
                facturas_pendientes=debt["facturas_pendientes"]
            )
            results.append(resp)

    return results


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna um cliente pelo ID."""
    try:
        client = await Client.get(PydanticObjectId(client_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    return client_to_response(client)


@router.get("/{client_id}/payment-context")
async def get_payment_context(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    meses_futuro: int = Query(6, ge=0, le=36),
):
    """
    Contexto completo para o modal de cobro numa unica chamada: dados do cliente,
    saldo/faturas pendentes (detalhadas, mais antigas primeiro) e taxa de reativacao.
    Substitui os 3 round-trips (get + pending-balance + list_by_client) do frontend.

    `meses_futuro` estica a grade para frente (o cajero que quer adiantar o ano
    inteiro pede 12, 18...). O teto de 36 evita uma grade infinita por engano.
    """
    try:
        cid = PydanticObjectId(client_id)
    except Exception:
        raise HTTPException(status_code=400, detail="client_id invalido")

    client = await Client.get(cid)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    pendientes = await Invoice.find(
        {"client.$id": cid},
        Invoice.saldo_devedor > 0,
        Invoice.status != InvoiceStatus.ANULADA,
    ).to_list()
    pendientes.sort(key=lambda inv: (inv.ano_referencia, inv.mes_referencia, inv.fecha_emision))

    facturas = [_factura_dict(inv) for inv in pendientes]

    # "Otros cargos": o que a tesouraria lançou como AVULSA (reconexión, material,
    # cuota de conexión, contribución extraordinaria). Sai da grade de meses e vira
    # lista própria — somar isso no mês faria o balcão ler consumo de água onde não é.
    otros_cargos = [f for f in facturas if f["tipo"] != InvoiceType.CONSUMO.value]

    settings = await SystemSettings.get_instance()

    # Grade de meses (para o Modo Caja): de -3 a +`meses_futuro` do atual, mais
    # qualquer pendente mais antiga. Cada célula: pago / pendente / sem factura.
    # SÓ faturas de CONSUMO — cada célula é o mês de água daquele período.
    todas = await Invoice.find(
        {"client.$id": cid},
        Invoice.tipo == InvoiceType.CONSUMO,
        Invoice.status != InvoiceStatus.ANULADA,
    ).to_list()

    def _add(key: tuple, n: int) -> tuple:
        idx = key[0] * 12 + (key[1] - 1) + n
        return idx // 12, idx % 12 + 1

    por_mes: dict = {}
    for inv in todas:
        k = (inv.ano_referencia, inv.mes_referencia)
        cell = por_mes.setdefault(
            k, {"saldo": Decimal("0"), "invoice_ids": [], "pendente": False,
                "cuota": Decimal("0")})
        if inv.saldo_devedor and inv.saldo_devedor > 0:
            cell["saldo"] += inv.saldo_devedor
            cell["invoice_ids"].append(str(inv.id))
            cell["pendente"] = True
            # Parte do mês que é cuota de um acordo, não consumo: o cajero precisa
            # saber que está cobrando parcela quando lê o valor em voz alta.
            if inv.cuota_valor:
                cell["cuota"] += inv.cuota_valor

    hoy = date.today()
    atual = (hoy.year, hoy.month)
    pendentes_keys = [k for k, v in por_mes.items() if v["pendente"]]
    inicio = min([_add(atual, -3)] + pendentes_keys)
    fim = _add(atual, meses_futuro)

    grade = []
    k = inicio
    while k <= fim:
        v = por_mes.get(k)
        if v is None:
            estado = "sem_factura"
            grade.append({"ano": k[0], "mes": k[1], "estado": estado,
                          "saldo": Decimal("0"), "invoice_ids": [],
                          "cuota": Decimal("0")})
        else:
            estado = "pendente" if v["pendente"] else "pagada"
            grade.append({"ano": k[0], "mes": k[1], "estado": estado,
                          "saldo": v["saldo"], "invoice_ids": v["invoice_ids"],
                          "cuota": v["cuota"]})
        k = _add(k, 1)

    # Acordo ativo: a caja mostra o andamento e impede abrir um segundo.
    from app.services.agreement_service import acuerdo_activo_dict

    return {
        "client": client_to_response(client),
        "saldo_pendiente": sum(inv.saldo_devedor for inv in pendientes),
        "facturas_pendientes": len(pendientes),
        "facturas": facturas,
        "otros_cargos": otros_cargos,
        "taxa_reativacao": settings.taxa_reativacao,
        "tarifa_base": settings.tarifa_base,
        "iva_tasa_agua": settings.iva_tasa_agua,
        "iva_afectacion_agua": settings.iva_afectacion_agua,
        "grade_meses": grade,
        "acuerdo": await acuerdo_activo_dict(cid),
    }


def _factura_dict(inv: Invoice) -> dict:
    """Fatura como o balcão precisa dela: id (para cobrar direcionado) e itens."""
    return {
        "id": str(inv.id),
        "tipo": inv.tipo.value if hasattr(inv.tipo, "value") else str(inv.tipo),
        "numero_factura": inv.numero_factura,
        "mes_referencia": inv.mes_referencia,
        "ano_referencia": inv.ano_referencia,
        "fecha_emision": inv.fecha_emision,
        "fecha_vencimiento": inv.fecha_vencimiento,
        "saldo_devedor": inv.saldo_devedor,
        "valor_total": inv.valor_total,
        "status": inv.status,
        # Recorte da cuota do acordo dentro do mês, com o IVA dela: a factura
        # legal precisa separar "cuota" de "agua", e a cuota não usa o IVA das
        # configurações — usa o que foi escolhido ao fechar o acordo.
        "cuota_valor": inv.cuota_valor,
        "cuota_iva_tasa": inv.cuota_iva_tasa,
        "cuota_iva_afectacion": inv.cuota_iva_afectacion,
        "cuota_numero": inv.cuota_numero,
        "items": [
            {
                "descripcion": it.descripcion,
                "cantidad": it.cantidad,
                "precio_unitario": it.precio_unitario,
                "iva_tasa": it.iva_tasa,
                "iva_afectacion": it.iva_afectacion,
            }
            for it in (inv.items or [])
        ],
    }


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str,
    client_data: ClientUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Atualiza dados de um cliente."""
    try:
        client = await Client.get(PydanticObjectId(client_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    update_data = client_data.model_dump(exclude_unset=True)
    if update_data:
        # Valida e converte sponsor_id
        if "sponsor_id" in update_data and update_data["sponsor_id"]:
            update_data["sponsor_id"] = await _validate_sponsor_id(update_data["sponsor_id"])
        update_data["updated_at"] = datetime.utcnow()
        await client.update({"$set": update_data})
        await client.sync()

    return client_to_response(client)


@router.post("/bulk/assign-lote", response_model=dict)
async def bulk_assign_lote(
    assignments: List[dict],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Atribui manzana/lote a múltiplos clientes de uma vez.
    Body: [{"client_id": "...", "manzana": "33", "lote": "05"}, ...]
    """
    updated = 0
    errors = []
    for item in assignments:
        client_id = item.get("client_id")
        manzana = str(item.get("manzana", "")).strip()
        lote = str(item.get("lote", "")).strip()
        if not client_id or not manzana or not lote:
            errors.append({"client_id": client_id, "error": "dados incompletos"})
            continue
        try:
            client = await Client.get(PydanticObjectId(client_id))
            if not client:
                errors.append({"client_id": client_id, "error": "não encontrado"})
                continue
            await client.update({"$set": {"manzana": manzana, "lote": lote, "updated_at": datetime.utcnow()}})
            updated += 1
        except Exception as ex:
            errors.append({"client_id": client_id, "error": str(ex)})
    return {"updated": updated, "errors": errors}


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Remove um cliente.
    Apenas clientes sem faturas podem ser removidos.
    """
    try:
        client = await Client.get(PydanticObjectId(client_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    # Verifica se tem faturas
    invoice_count = await Invoice.find({"client.$id": client.id}).count()
    if invoice_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cliente possui {invoice_count} faturas. Inative em vez de deletar."
        )

    await client.delete()
