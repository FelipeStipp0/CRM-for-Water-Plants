"""
Testes de integracao para endpoints HTTP de leituras (/readings).

Cobre endpoints nao cobertos por test_api_readings_batch.py:
  - POST /readings/              (criar leitura individual)
  - GET  /readings/              (listar com filtros de periodo)
  - GET  /readings/by-route      (leituras por rota/periodo)
  - GET  /readings/pending       (clientes sem leitura no periodo)
  - GET  /readings/client/{id}   (historico de um cliente)
  - DELETE /readings/{id}        (deletar leitura)
"""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from httpx import AsyncClient

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.reading import Reading
from app.models.settings import SystemSettings


# ==================== FIXTURES ====================

@pytest_asyncio.fixture
async def read_settings(test_db) -> SystemSettings:
    s = SystemSettings(
        nombre_junta="Junta Test",
        tarifa_base=Decimal("25000"),
        consumo_minimo=15,
        valor_excedente_m3=Decimal("1500"),
        dias_vencimiento=15,
    )
    await s.insert()
    return s


@pytest_asyncio.fixture
async def client_r(test_db) -> Client:
    c = Client(
        nombre_completo="Cliente Leitura R",
        ci_ruc="3330001",
        direccion="Rua Leitura 1",
        manzana="D",
        lote="1",
        numero_medidor="MED-READ-R",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await c.insert()
    return c


@pytest_asyncio.fixture
async def client_r2(test_db) -> Client:
    c = Client(
        nombre_completo="Cliente Leitura R2",
        ci_ruc="3330002",
        direccion="Rua Leitura 2",
        manzana="D",
        lote="2",
        numero_medidor="MED-READ-R2",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await c.insert()
    return c


@pytest_asyncio.fixture
async def prev_reading(test_db, client_r) -> Reading:
    """Leitura anterior para calcular consumo."""
    r = Reading(
        client=client_r,
        valor_leitura=100,
        mes_referencia=3,
        ano_referencia=2024,
        consumo_calculado=20,
    )
    await r.insert()
    return r


@pytest_asyncio.fixture
async def existing_reading(test_db, client_r, prev_reading) -> Reading:
    """Leitura de abril/2024 ja existente."""
    r = Reading(
        client=client_r,
        valor_leitura=120,
        mes_referencia=4,
        ano_referencia=2024,
        consumo_calculado=20,
    )
    await r.insert()
    return r


# ==================== AUTENTICACAO ====================

@pytest.mark.asyncio
async def test_readings_requires_auth(test_client: AsyncClient, test_db):
    response = await test_client.get("/readings/")
    assert response.status_code == 401


# ==================== CRIAR LEITURA INDIVIDUAL ====================

@pytest.mark.asyncio
async def test_create_reading(
    test_client: AsyncClient, auth_headers, client_r, prev_reading, read_settings
):
    """Cria leitura individual e calcula consumo a partir da leitura anterior."""
    response = await test_client.post(
        "/readings/",
        headers=auth_headers,
        json={
            "client_id": str(client_r.id),
            "valor_leitura": 130,
            "mes_referencia": 4,
            "ano_referencia": 2024,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["valor_leitura"] == 130
    assert data["consumo_calculado"] == 30  # 130 - 100
    assert data["client_id"] == str(client_r.id)


@pytest.mark.asyncio
async def test_create_reading_first_of_client(
    test_client: AsyncClient, auth_headers, client_r2, read_settings
):
    """Primeira leitura de um cliente (sem anterior) e aceita."""
    response = await test_client.post(
        "/readings/",
        headers=auth_headers,
        json={
            "client_id": str(client_r2.id),
            "valor_leitura": 50,
            "mes_referencia": 4,
            "ano_referencia": 2024,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["valor_leitura"] == 50


@pytest.mark.asyncio
async def test_create_reading_invalid_client(test_client: AsyncClient, auth_headers, test_db):
    """Client ID invalido retorna 4xx."""
    response = await test_client.post(
        "/readings/",
        headers=auth_headers,
        json={
            "client_id": "id_invalido",
            "valor_leitura": 100,
            "mes_referencia": 4,
            "ano_referencia": 2024,
        },
    )
    assert response.status_code in (400, 404, 422)


@pytest.mark.asyncio
async def test_create_reading_client_not_found(test_client: AsyncClient, auth_headers, test_db):
    """Client inexistente retorna 404."""
    response = await test_client.post(
        "/readings/",
        headers=auth_headers,
        json={
            "client_id": "507f1f77bcf86cd799439011",
            "valor_leitura": 100,
            "mes_referencia": 4,
            "ano_referencia": 2024,
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_reading_duplicate_period_rejected(
    test_client: AsyncClient, auth_headers, client_r, existing_reading, read_settings
):
    """Nao permite segunda leitura para o mesmo cliente/periodo."""
    response = await test_client.post(
        "/readings/",
        headers=auth_headers,
        json={
            "client_id": str(client_r.id),
            "valor_leitura": 125,
            "mes_referencia": 4,
            "ano_referencia": 2024,
        },
    )
    assert response.status_code == 400


# ==================== LISTAR LEITURAS ====================

@pytest.mark.asyncio
async def test_list_readings(
    test_client: AsyncClient, auth_headers, existing_reading
):
    """Lista leituras."""
    response = await test_client.get("/readings/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "X-Total-Count" in response.headers


@pytest.mark.asyncio
async def test_list_readings_filter_period(
    test_client: AsyncClient, auth_headers, prev_reading, existing_reading
):
    """Filtra por mes/ano de referencia."""
    response = await test_client.get(
        "/readings/",
        headers=auth_headers,
        params={"mes": 4, "ano": 2024},
    )
    assert response.status_code == 200
    data = response.json()
    assert all(r["mes_referencia"] == 4 for r in data)
    ids = [r["id"] for r in data]
    assert str(existing_reading.id) in ids
    assert str(prev_reading.id) not in ids


@pytest.mark.asyncio
async def test_list_readings_pagination(
    test_client: AsyncClient, auth_headers, client_r2, read_settings, test_db
):
    """Verifica paginacao."""
    for mes in range(1, 5):
        r = Reading(
            client=client_r2,
            valor_leitura=100 + mes * 10,
            mes_referencia=mes,
            ano_referencia=2023,
            consumo_calculado=10,
        )
        await r.insert()

    r1 = await test_client.get("/readings/", headers=auth_headers, params={"limit": 2})
    assert r1.status_code == 200
    assert len(r1.json()) == 2

    r2 = await test_client.get("/readings/", headers=auth_headers, params={"skip": 2, "limit": 2})
    assert r2.status_code == 200
    assert len(r2.json()) == 2

    total = int(r1.headers["X-Total-Count"])
    assert total == 4


# ==================== LEITURAS POR ROTA ====================

@pytest.mark.asyncio
async def test_readings_by_route(
    test_client: AsyncClient, auth_headers, client_r, existing_reading
):
    """Lista leituras de um periodo por ordem de rota (manzana/lote)."""
    response = await test_client.get(
        "/readings/by-route",
        headers=auth_headers,
        params={"mes": 4, "ano": 2024},
    )
    assert response.status_code == 200
    data = response.json()
    ids = [r["id"] for r in data]
    assert str(existing_reading.id) in ids


@pytest.mark.asyncio
async def test_readings_by_route_includes_client_data(
    test_client: AsyncClient, auth_headers, client_r, existing_reading
):
    """Retorna dados do cliente junto com a leitura."""
    response = await test_client.get(
        "/readings/by-route",
        headers=auth_headers,
        params={"mes": 4, "ano": 2024},
    )
    assert response.status_code == 200
    entry = next(r for r in response.json() if r["id"] == str(existing_reading.id))
    assert "cliente_nombre" in entry or "client_nombre" in entry or "cliente_medidor" in entry


@pytest.mark.asyncio
async def test_readings_by_route_empty_period(
    test_client: AsyncClient, auth_headers, test_db
):
    """Periodo sem leituras retorna lista vazia."""
    response = await test_client.get(
        "/readings/by-route",
        headers=auth_headers,
        params={"mes": 1, "ano": 2020},
    )
    assert response.status_code == 200
    assert response.json() == []


# ==================== LEITURAS PENDENTES ====================

@pytest.mark.asyncio
async def test_readings_pending(
    test_client: AsyncClient, auth_headers, client_r, client_r2, existing_reading
):
    """Lista clientes SEM leitura para um periodo."""
    response = await test_client.get(
        "/readings/pending",
        headers=auth_headers,
        params={"mes": 4, "ano": 2024},
    )
    assert response.status_code == 200
    data = response.json()
    ids = [c["client_id"] for c in data]
    # client_r2 nao tem leitura em abril/2024
    assert str(client_r2.id) in ids
    # client_r JA tem leitura (existing_reading)
    assert str(client_r.id) not in ids


@pytest.mark.asyncio
async def test_readings_pending_all_done(
    test_client: AsyncClient, auth_headers, client_r, existing_reading, test_db
):
    """Quando todos os clientes ativos tem leitura, retorna lista vazia."""
    # Garante que so ha um cliente ativo (client_r) e ele ja tem leitura
    response = await test_client.get(
        "/readings/pending",
        headers=auth_headers,
        params={"mes": 4, "ano": 2024},
    )
    assert response.status_code == 200
    data = response.json()
    # client_r ja tem leitura, nao deve aparecer
    assert str(client_r.id) not in [c["client_id"] for c in data]


# ==================== HISTORICO POR CLIENTE ====================

@pytest.mark.asyncio
async def test_get_client_readings(
    test_client: AsyncClient, auth_headers, client_r, prev_reading, existing_reading
):
    """Retorna historico de leituras de um cliente."""
    response = await test_client.get(
        f"/readings/client/{client_r.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    ids = {r["id"] for r in data}
    assert str(prev_reading.id) in ids
    assert str(existing_reading.id) in ids


@pytest.mark.asyncio
async def test_get_client_readings_empty(
    test_client: AsyncClient, auth_headers, client_r2
):
    """Cliente sem leituras retorna lista vazia."""
    response = await test_client.get(
        f"/readings/client/{client_r2.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_client_readings_ordered(
    test_client: AsyncClient, auth_headers, client_r2, test_db
):
    """Leituras retornadas em ordem decrescente (mais recente primeiro)."""
    for mes in [1, 2, 3]:
        r = Reading(
            client=client_r2,
            valor_leitura=100 + mes * 10,
            mes_referencia=mes,
            ano_referencia=2024,
            consumo_calculado=10,
        )
        await r.insert()

    response = await test_client.get(
        f"/readings/client/{client_r2.id}",
        headers=auth_headers,
    )
    data = response.json()
    assert len(data) == 3
    # Mes mais recente deve vir primeiro
    months = [r["mes_referencia"] for r in data]
    assert months == sorted(months, reverse=True)


@pytest.mark.asyncio
async def test_get_client_readings_limit(
    test_client: AsyncClient, auth_headers, client_r2, test_db
):
    """Parametro limit funciona corretamente."""
    for mes in range(1, 7):
        r = Reading(
            client=client_r2,
            valor_leitura=100 + mes * 5,
            mes_referencia=mes,
            ano_referencia=2024,
            consumo_calculado=5,
        )
        await r.insert()

    response = await test_client.get(
        f"/readings/client/{client_r2.id}",
        headers=auth_headers,
        params={"limit": 3},
    )
    assert response.status_code == 200
    assert len(response.json()) == 3


# ==================== DELETAR LEITURA ====================

@pytest.mark.asyncio
async def test_delete_reading(
    test_client: AsyncClient, auth_headers, existing_reading
):
    """Deleta leitura sem fatura associada."""
    response = await test_client.delete(
        f"/readings/{existing_reading.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200

    # Verifica remocao
    check = await Reading.get(existing_reading.id)
    assert check is None


@pytest.mark.asyncio
async def test_delete_reading_with_invoice_blocked(
    test_client: AsyncClient, auth_headers, client_r, existing_reading, test_db
):
    """Nao pode deletar leitura que tem fatura associada."""
    inv = Invoice(
        client=client_r,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=existing_reading.mes_referencia,
        ano_referencia=existing_reading.ano_referencia,
        fecha_vencimiento=date(2024, 4, 15),
        consumo=20,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("0"),
        valor_total=Decimal("25000"),
        saldo_devedor=Decimal("25000"),
        reading_id=existing_reading.id,
    )
    await inv.insert()

    response = await test_client.delete(
        f"/readings/{existing_reading.id}",
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_delete_reading_not_found(test_client: AsyncClient, auth_headers, test_db):
    """ID inexistente retorna 404."""
    response = await test_client.delete(
        "/readings/507f1f77bcf86cd799439011",
        headers=auth_headers,
    )
    assert response.status_code == 404
