"""
Endpoints de leituras.
"""

from datetime import datetime
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.models.client import Client, ClientStatus
from app.models.invoice import Invoice
from app.models.reading import Reading
from app.models.user import User
from app.routers.auth import get_current_active_user, require_scopes
from app.schemas.reading import (
    ReadingCreate,
    ReadingBatch,
    ReadingResponse,
    ReadingWithClient,
)

router = APIRouter(dependencies=[Depends(require_scopes("readings"))])


async def get_previous_reading(client_id: PydanticObjectId, mes: int, ano: int) -> Optional[Reading]:
    """Busca a leitura anterior a um periodo."""
    # Calcula periodo anterior
    if mes == 1:
        prev_mes, prev_ano = 12, ano - 1
    else:
        prev_mes, prev_ano = mes - 1, ano

    # Busca leitura do mes anterior
    reading = await Reading.find_one(
        {"client.$id": client_id},
        Reading.mes_referencia == prev_mes,
        Reading.ano_referencia == prev_ano,
    )

    # Se nao encontrar, busca a mais recente anterior
    if not reading:
        reading = await Reading.find(
            {"client.$id": client_id},
            {"$or": [
                {"ano_referencia": {"$lt": ano}},
                {"$and": [
                    {"ano_referencia": ano},
                    {"mes_referencia": {"$lt": mes}}
                ]}
            ]}
        ).sort([("ano_referencia", -1), ("mes_referencia", -1)]).first_or_none()

    return reading


def reading_to_response(reading: Reading) -> ReadingResponse:
    """Converte modelo para schema de resposta."""
    client_ref = reading.client
    client_id = client_ref.ref.id if hasattr(client_ref, 'ref') else client_ref.id
    return ReadingResponse(
        id=str(reading.id),
        client_id=str(client_id),
        valor_leitura=reading.valor_leitura,
        mes_referencia=reading.mes_referencia,
        ano_referencia=reading.ano_referencia,
        consumo_calculado=reading.consumo_calculado,
        referencia=reading.referencia,
        observacion=reading.observacion,
        fecha_lectura=reading.fecha_lectura,
        created_at=reading.created_at,
        foto_url=reading.foto_url,
        gps_latitude=reading.gps_latitude,
        gps_longitude=reading.gps_longitude,
        gps_timestamp=reading.gps_timestamp,
    )


@router.post("/", response_model=ReadingResponse, status_code=status.HTTP_201_CREATED)
async def create_reading(
    reading_data: ReadingCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria uma nova leitura."""
    try:
        client = await Client.get(PydanticObjectId(reading_data.client_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    # Verifica se ja existe leitura para o periodo
    existing = await Reading.find_one(
        {"client.$id": client.id},
        Reading.mes_referencia == reading_data.mes_referencia,
        Reading.ano_referencia == reading_data.ano_referencia,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ja existe leitura para {reading_data.mes_referencia}/{reading_data.ano_referencia}"
        )

    # Busca leitura anterior para calcular consumo
    prev_reading = await get_previous_reading(
        client.id,
        reading_data.mes_referencia,
        reading_data.ano_referencia
    )

    consumo = None
    if prev_reading:
        consumo = reading_data.valor_leitura - prev_reading.valor_leitura
        if consumo < 0:
            consumo = 0  # Evita consumo negativo (troca de medidor, etc)

    reading = Reading(
        client=client,
        valor_leitura=reading_data.valor_leitura,
        mes_referencia=reading_data.mes_referencia,
        ano_referencia=reading_data.ano_referencia,
        consumo_calculado=consumo,
        referencia=reading_data.referencia,
        observacion=reading_data.observacion,
        foto_url=reading_data.foto_url,
        gps_latitude=reading_data.gps_latitude,
        gps_longitude=reading_data.gps_longitude,
        gps_timestamp=datetime.utcnow() if reading_data.gps_latitude else None,
    )
    await reading.insert()

    return reading_to_response(reading)


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def create_readings_batch(
    batch_data: ReadingBatch,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Insere leituras em lote para um periodo.

    Aceita items com client_id direto OU identificadores
    (numero_medidor, ci_ruc, nombre) para matching automatico.
    """
    from app.services.client_matching import ClientMatchingService

    results = {
        "created": 0,
        "skipped": 0,
        "matched": 0,
        "unmatched": 0,
        "errors": [],
        "unmatched_details": [],
    }

    # Instancia matcher apenas se algum item nao tem client_id
    matcher = None
    needs_matching = any(not item.client_id for item in batch_data.readings)
    if needs_matching:
        matcher = await ClientMatchingService.create(
            prioridade=batch_data.matching_prioridade
        )

    for item in batch_data.readings:
        try:
            client = None

            if item.client_id:
                client = await Client.get(PydanticObjectId(item.client_id))
                if not client:
                    results["errors"].append(f"Cliente {item.client_id} nao encontrado")
                    continue
            else:
                client = matcher.match(
                    numero_medidor=item.numero_medidor,
                    ci_ruc=item.ci_ruc,
                    nombre=item.nombre,
                )
                if not client:
                    results["unmatched"] += 1
                    results["unmatched_details"].append({
                        "numero_medidor": item.numero_medidor,
                        "ci_ruc": item.ci_ruc,
                        "nombre": item.nombre,
                        "valor_leitura": item.valor_leitura,
                    })
                    continue
                results["matched"] += 1

            # Verifica duplicata
            existing = await Reading.find_one(
                {"client.$id": client.id},
                Reading.mes_referencia == batch_data.mes_referencia,
                Reading.ano_referencia == batch_data.ano_referencia,
            )
            if existing:
                results["skipped"] += 1
                continue

            # Calcula consumo
            prev_reading = await get_previous_reading(
                client.id,
                batch_data.mes_referencia,
                batch_data.ano_referencia
            )

            consumo = None
            if prev_reading:
                consumo = item.valor_leitura - prev_reading.valor_leitura
                if consumo < 0:
                    consumo = 0

            reading = Reading(
                client=client,
                valor_leitura=item.valor_leitura,
                mes_referencia=batch_data.mes_referencia,
                ano_referencia=batch_data.ano_referencia,
                consumo_calculado=consumo,
                referencia=item.referencia,
                observacion=item.observacion,
                foto_url=item.foto_url,
                gps_latitude=item.gps_latitude,
                gps_longitude=item.gps_longitude,
                gps_timestamp=datetime.utcnow() if item.gps_latitude else None,
            )
            await reading.insert()
            results["created"] += 1

        except Exception as e:
            identifier = item.client_id or item.numero_medidor or item.ci_ruc or item.nombre or "unknown"
            results["errors"].append(f"Erro item {identifier}: {str(e)}")

    return results


@router.get("/", response_model=List[ReadingResponse])
async def list_readings(
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista leituras com filtros opcionais."""
    query = Reading.find()

    if mes:
        query = query.find(Reading.mes_referencia == mes)
    if ano:
        query = query.find(Reading.ano_referencia == ano)

    total = await query.count()
    response.headers["X-Total-Count"] = str(total)

    readings = await query.skip(skip).limit(limit).sort("-created_at").to_list()

    return [reading_to_response(r) for r in readings]


@router.get("/by-route", response_model=List[ReadingWithClient])
async def list_readings_by_route(
    current_user: Annotated[User, Depends(get_current_active_user)],
    mes: int = Query(..., ge=1, le=12),
    ano: int = Query(..., ge=2000, le=2100),
    manzana: Optional[str] = None,
):
    """
    Lista leituras ordenadas por rota com dados do cliente.
    Se manzana for especificada, filtra apenas essa manzana.
    """
    # Busca clientes ativos ordenados por rota
    client_query = Client.find(Client.status == ClientStatus.ATIVO)
    if manzana:
        client_query = client_query.find(Client.manzana == manzana)

    clients = await client_query.sort([("manzana", 1), ("lote", 1)]).to_list()

    if not clients:
        return []

    # Batch fetch: busca todas as leituras do periodo de uma vez
    client_ids = [c.id for c in clients]
    readings = await Reading.find(
        {"client.$id": {"$in": client_ids}},
        Reading.mes_referencia == mes,
        Reading.ano_referencia == ano,
    ).to_list()

    readings_map = {r.client.ref.id: r for r in readings}

    results = []
    for client in clients:
        reading = readings_map.get(client.id)
        if reading:
            results.append(ReadingWithClient(
                **reading_to_response(reading).model_dump(),
                cliente_nombre=client.nombre_completo,
                cliente_medidor=client.numero_medidor,
                cliente_manzana=client.manzana,
                cliente_lote=client.lote,
            ))

    return results


@router.get("/pending", response_model=List[dict])
async def list_pending_readings(
    current_user: Annotated[User, Depends(get_current_active_user)],
    mes: int = Query(..., ge=1, le=12),
    ano: int = Query(..., ge=2000, le=2100),
    manzana: Optional[str] = None,
):
    """
    Lista clientes que ainda nao tem leitura para o periodo.
    Util para controle do leiturista.
    """
    # Busca clientes ativos
    client_query = Client.find(Client.status == ClientStatus.ATIVO)
    if manzana:
        client_query = client_query.find(Client.manzana == manzana)

    clients = await client_query.sort([("manzana", 1), ("lote", 1)]).to_list()

    # Busca quais ja tem leitura
    readings = await Reading.find(
        Reading.mes_referencia == mes,
        Reading.ano_referencia == ano,
    ).to_list()

    clients_with_reading = {r.client.ref.id for r in readings}

    # Filtra os que nao tem
    pending = []
    for client in clients:
        if client.id not in clients_with_reading:
            pending.append({
                "client_id": str(client.id),
                "nombre": client.nombre_completo,
                "medidor": client.numero_medidor,
                "manzana": client.manzana,
                "lote": client.lote,
            })

    return pending


@router.get("/client/{client_id}", response_model=List[ReadingResponse])
async def get_client_readings(
    client_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(12, ge=1, le=60),
):
    """Retorna historico de leituras de um cliente."""
    try:
        client = await Client.get(PydanticObjectId(client_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    if not client:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    readings = await Reading.find(
        {"client.$id": client.id}
    ).sort([("ano_referencia", -1), ("mes_referencia", -1)]).limit(limit).to_list()

    return [reading_to_response(r) for r in readings]


@router.delete("/{reading_id}", status_code=status.HTTP_200_OK)
async def delete_reading(
    reading_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Deleta uma leitura.
    Bloqueia se existir fatura vinculada (delete a fatura primeiro).
    """
    try:
        reading = await Reading.get(PydanticObjectId(reading_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Leitura nao encontrada")

    if not reading:
        raise HTTPException(status_code=404, detail="Leitura nao encontrada")

    # Verifica se existe fatura gerada a partir desta leitura
    linked_invoice = await Invoice.find_one(
        Invoice.reading_id == reading.id,
    )
    if linked_invoice:
        raise HTTPException(
            status_code=400,
            detail="Existe fatura vinculada a esta leitura. Delete a fatura primeiro.",
        )

    await reading.delete()

    return {
        "detail": "Leitura removida",
        "reading_id": reading_id,
    }
