"""
Testes de integracao para endpoints HTTP de pagamentos (/payments).

Cobre:
  - POST /payments/                     (processar pagamento)
  - GET  /payments/                     (listar)
  - GET  /payments/client/{client_id}   (historico por cliente)
  - GET  /payments/by-group/{grupo}     (busca por grupo, para reimpressao de recibo)
  - GET  /payments/{payment_id}         (busca por ID)
"""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from httpx import AsyncClient

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.payment import Payment
from app.models.settings import SystemSettings


# ==================== FIXTURES ====================

@pytest_asyncio.fixture
async def pay_settings(test_db) -> SystemSettings:
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
async def payer(test_db) -> Client:
    c = Client(
        nombre_completo="Cliente Pagador",
        ci_ruc="2220001",
        direccion="Rua Pagamento 1",
        manzana="B",
        lote="1",
        numero_medidor="MED-PAY-001",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await c.insert()
    return c


@pytest_asyncio.fixture
async def payer_b(test_db) -> Client:
    c = Client(
        nombre_completo="Cliente Pagador B",
        ci_ruc="2220002",
        direccion="Rua Pagamento 2",
        manzana="B",
        lote="2",
        numero_medidor="MED-PAY-002",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await c.insert()
    return c


@pytest_asyncio.fixture
async def invoice_p1(test_db, payer) -> Invoice:
    inv = Invoice(
        client=payer,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=1,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 1, 15),
        consumo=15,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("0"),
        valor_total=Decimal("25000"),
        saldo_devedor=Decimal("25000"),
    )
    await inv.insert()
    return inv


@pytest_asyncio.fixture
async def invoice_p2(test_db, payer) -> Invoice:
    inv = Invoice(
        client=payer,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=2,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 2, 15),
        consumo=20,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("7500"),
        valor_total=Decimal("32500"),
        saldo_devedor=Decimal("32500"),
    )
    await inv.insert()
    return inv


# ==================== AUTENTICACAO ====================

@pytest.mark.asyncio
async def test_payments_requires_auth(test_client: AsyncClient, test_db):
    response = await test_client.get("/payments/")
    assert response.status_code == 401


# ==================== PROCESSAR PAGAMENTO ====================

@pytest.mark.asyncio
async def test_create_payment_full(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Processa pagamento que quita uma fatura integralmente."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={
            "client_id": str(payer.id),
            "valor_total": "25000",
            "recibido_por": "Caixa",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["payment"]["valor_total"] == "25000"
    assert data["client_name"] == "Cliente Pagador"
    assert len(data["invoices_affected"]) == 1
    assert Decimal(data["total_debt_after"]) == Decimal("0")


@pytest.mark.asyncio
async def test_create_payment_partial(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Processa pagamento parcial de uma fatura."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={
            "client_id": str(payer.id),
            "valor_total": "10000",
            "recibido_por": "Caixa",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert Decimal(data["total_debt_after"]) == Decimal("15000")

    # Verifica fatura atualizada
    inv = await Invoice.get(invoice_p1.id)
    assert inv.status == InvoiceStatus.PARCIAL
    assert inv.saldo_devedor == Decimal("15000")


@pytest.mark.asyncio
async def test_create_payment_multiple_invoices(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, invoice_p2, pay_settings
):
    """Pagamento distribui entre multiplas faturas, da mais antiga para a mais nova."""
    total = Decimal("57500")  # Quita as duas faturas
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={
            "client_id": str(payer.id),
            "valor_total": str(total),
            "recibido_por": "Caixa",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["invoices_affected"]) == 2
    assert Decimal(data["total_debt_after"]) == Decimal("0")


@pytest.mark.asyncio
async def test_create_payment_with_overpayment(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Pagamento acima da divida registra overpayment."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={
            "client_id": str(payer.id),
            "valor_total": "50000",
            "recibido_por": "Caixa",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert Decimal(data["overpayment"]) == Decimal("25000")


@pytest.mark.asyncio
async def test_create_payment_triggers_cutoff_auto_exit(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings, test_db
):
    """Pagamento que quita toda divida de cliente em workflow dispara auto-exit."""
    from app.models.cutoff import CutoffNotice, CutoffStatus

    notice = CutoffNotice(
        client=payer,
        status=CutoffStatus.EM_LISTA,
        divida_original=Decimal("25000"),
        meses_atraso=3,
    )
    await notice.insert()

    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={
            "client_id": str(payer.id),
            "valor_total": "25000",
            "recibido_por": "Caixa",
        },
    )
    assert response.status_code == 201

    notice_updated = await CutoffNotice.get(notice.id)
    assert notice_updated.saiu_por_pagamento is True


@pytest.mark.asyncio
async def test_create_payment_no_invoices(
    test_client: AsyncClient, auth_headers, payer_b, pay_settings
):
    """Pagamento para cliente sem faturas pendentes retorna erro ou overpayment total."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={
            "client_id": str(payer_b.id),
            "valor_total": "25000",
            "recibido_por": "Caixa",
        },
    )
    # Pode retornar 400 (sem divida) ou 201 com overpayment total
    assert response.status_code in (201, 400)


@pytest.mark.asyncio
async def test_create_payment_invalid_client(test_client: AsyncClient, auth_headers, test_db):
    """Client ID invalido retorna 400."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": "id_invalido", "valor_total": "25000"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_payment_client_not_found(test_client: AsyncClient, auth_headers, test_db):
    """Client inexistente retorna 404."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": "507f1f77bcf86cd799439011", "valor_total": "25000"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_payment_response_fields(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Verifica todos os campos obrigatorios na resposta."""
    response = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000", "recibido_por": "Operador"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "payment" in data
    assert "client_name" in data
    assert "client_ci_ruc" in data
    assert "invoices_affected" in data
    assert "total_debt_before" in data
    assert "total_debt_after" in data
    assert "overpayment" in data


# ==================== LISTAR PAGAMENTOS ====================

@pytest.mark.asyncio
async def test_list_payments(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Lista pagamentos recentes."""
    # Cria um pagamento
    await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )

    response = await test_client.get("/payments/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "X-Total-Count" in response.headers


@pytest.mark.asyncio
async def test_list_payments_empty(test_client: AsyncClient, auth_headers, test_db):
    """Lista vazia quando nao ha pagamentos."""
    response = await test_client.get("/payments/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers.get("X-Total-Count") == "0"


@pytest.mark.asyncio
async def test_list_payments_pagination(
    test_client: AsyncClient, auth_headers, payer, pay_settings, test_db
):
    """Verifica paginacao de pagamentos."""
    # Cria 3 faturas e pagamentos
    for mes in range(1, 4):
        inv = Invoice(
            client=payer,
            tipo=InvoiceType.CONSUMO,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=mes,
            ano_referencia=2023,
            fecha_vencimiento=date(2023, mes, 15),
            consumo=15,
            tarifa_base=Decimal("25000"),
            excedente=Decimal("0"),
            valor_total=Decimal("25000"),
            saldo_devedor=Decimal("25000"),
        )
        await inv.insert()
        await test_client.post(
            "/payments/",
            headers=auth_headers,
            json={"client_id": str(payer.id), "valor_total": "25000"},
        )

    r1 = await test_client.get("/payments/", headers=auth_headers, params={"limit": 2})
    assert len(r1.json()) == 2

    r2 = await test_client.get("/payments/", headers=auth_headers, params={"skip": 2, "limit": 2})
    assert len(r2.json()) == 1


@pytest.mark.asyncio
async def test_list_payments_fields(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Verifica campos retornados na listagem (PaymentHistory)."""
    await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )

    response = await test_client.get("/payments/", headers=auth_headers)
    assert response.status_code == 200
    entry = response.json()[0]
    assert "id" in entry
    assert "client_id" in entry
    assert "client_name" in entry
    assert "valor_total" in entry
    assert "fecha_pago" in entry
    assert "invoices_count" in entry


# ==================== HISTORICO POR CLIENTE ====================

@pytest.mark.asyncio
async def test_get_client_payments(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Lista pagamentos de um cliente especifico."""
    await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )

    response = await test_client.get(
        f"/payments/client/{payer.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["client_id"] == str(payer.id)


@pytest.mark.asyncio
async def test_get_client_payments_empty(test_client: AsyncClient, auth_headers, payer_b):
    """Cliente sem pagamentos retorna lista vazia."""
    response = await test_client.get(
        f"/payments/client/{payer_b.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_client_payments_invalid_id(test_client: AsyncClient, auth_headers, test_db):
    """ID invalido retorna 400."""
    response = await test_client.get(
        "/payments/client/id_invalido",
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_client_payments_isolation(
    test_client: AsyncClient, auth_headers, payer, payer_b, invoice_p1, pay_settings, test_db
):
    """Pagamentos de um cliente nao aparecem no historico de outro."""
    await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )

    response = await test_client.get(
        f"/payments/client/{payer_b.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


# ==================== BUSCA POR GRUPO ====================

@pytest.mark.asyncio
async def test_get_payment_by_group(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Busca pagamento pelo grupo_pagamento (para reimpressao de recibo)."""
    create_resp = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )
    assert create_resp.status_code == 201
    grupo = create_resp.json()["payment"]["grupo_pagamento"]

    response = await test_client.get(
        f"/payments/by-group/{grupo}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["payment"]["grupo_pagamento"] == grupo
    assert data["client_name"] == "Cliente Pagador"


@pytest.mark.asyncio
async def test_get_payment_by_group_not_found(test_client: AsyncClient, auth_headers, test_db):
    """Grupo inexistente retorna 404."""
    response = await test_client.get(
        "/payments/by-group/grupo-inexistente-xpto",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ==================== BUSCA POR ID ====================

@pytest.mark.asyncio
async def test_get_payment_by_id(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, pay_settings
):
    """Busca pagamento pelo ID."""
    create_resp = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )
    payment_id = create_resp.json()["payment"]["id"]

    response = await test_client.get(
        f"/payments/{payment_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == payment_id
    assert data["client_id"] == str(payer.id)
    assert Decimal(data["valor_total"]) == Decimal("25000")


@pytest.mark.asyncio
async def test_get_payment_not_found(test_client: AsyncClient, auth_headers, test_db):
    """ID inexistente retorna 404."""
    response = await test_client.get(
        "/payments/507f1f77bcf86cd799439011",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ==================== FLUXO COMPLETO ====================

@pytest.mark.asyncio
async def test_full_payment_flow(
    test_client: AsyncClient, auth_headers, payer, invoice_p1, invoice_p2, pay_settings
):
    """
    Fluxo completo: pagar parcialmente, depois pagar o restante,
    verificar historico, e buscar por grupo.
    """
    # Pagamento 1: quita fatura p1 (25000)
    r1 = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "25000"},
    )
    assert r1.status_code == 201
    assert Decimal(r1.json()["total_debt_after"]) == Decimal("32500")

    # Pagamento 2: quita fatura p2 (32500)
    r2 = await test_client.post(
        "/payments/",
        headers=auth_headers,
        json={"client_id": str(payer.id), "valor_total": "32500"},
    )
    assert r2.status_code == 201
    assert Decimal(r2.json()["total_debt_after"]) == Decimal("0")

    # Historico do cliente
    hist = await test_client.get(f"/payments/client/{payer.id}", headers=auth_headers)
    assert hist.status_code == 200
    assert len(hist.json()) == 2

    # Reimpressao por grupo
    grupo = r1.json()["payment"]["grupo_pagamento"]
    receipt = await test_client.get(f"/payments/by-group/{grupo}", headers=auth_headers)
    assert receipt.status_code == 200
    assert Decimal(receipt.json()["payment"]["valor_total"]) == Decimal("25000")
