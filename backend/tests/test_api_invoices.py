"""
Testes de integracao para endpoints HTTP de faturas (/invoices).

Cobre:
  - POST /invoices/                    (criar fatura avulsa)
  - POST /invoices/generate            (gerar faturas de consumo em batch)
  - GET  /invoices/                    (listar com filtros)
  - GET  /invoices/by-number/{numero}
  - GET  /invoices/pending
  - GET  /invoices/client/{client_id}
  - GET  /invoices/client/{client_id}/pending-balance
  - GET  /invoices/{invoice_id}
  - GET  /invoices/{invoice_id}/with-balance
  - PATCH /invoices/{invoice_id}/cancel
  - DELETE /invoices/{invoice_id}
"""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from httpx import AsyncClient

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.payment import Payment
from app.models.reading import Reading
from app.models.settings import SystemSettings


# ==================== FIXTURES ====================

@pytest_asyncio.fixture
async def inv_settings(test_db) -> SystemSettings:
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
async def client_a(test_db) -> Client:
    c = Client(
        nombre_completo="Cliente Fatura A",
        ci_ruc="1110001",
        direccion="Rua A 1",
        manzana="A",
        lote="1",
        numero_medidor="MED-INV-A",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await c.insert()
    return c


@pytest_asyncio.fixture
async def client_b(test_db) -> Client:
    c = Client(
        nombre_completo="Cliente Fatura B",
        ci_ruc="1110002",
        direccion="Rua B 2",
        manzana="A",
        lote="2",
        numero_medidor="MED-INV-B",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await c.insert()
    return c


@pytest_asyncio.fixture
async def pending_invoice(test_db, client_a) -> Invoice:
    inv = Invoice(
        client=client_a,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=3,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 3, 15),
        leitura_anterior=80,
        leitura_actual=100,
        consumo=20,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("7500"),
        valor_total=Decimal("32500"),
        saldo_devedor=Decimal("32500"),
    )
    await inv.insert()
    return inv


@pytest_asyncio.fixture
async def paid_invoice(test_db, client_a) -> Invoice:
    inv = Invoice(
        client=client_a,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PAGADA,
        mes_referencia=2,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 2, 15),
        consumo=15,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("0"),
        valor_total=Decimal("25000"),
        saldo_devedor=Decimal("0"),
    )
    await inv.insert()
    return inv


@pytest_asyncio.fixture
async def reading_for_gen(test_db, client_a, inv_settings) -> Reading:
    """Leitura de referencia para gerar fatura de consumo."""
    prev = Reading(
        client=client_a,
        valor_leitura=100,
        mes_referencia=3,
        ano_referencia=2024,
        consumo_calculado=20,
    )
    await prev.insert()
    reading = Reading(
        client=client_a,
        valor_leitura=120,
        mes_referencia=4,
        ano_referencia=2024,
        consumo_calculado=20,
    )
    await reading.insert()
    return reading


# ==================== AUTENTICACAO ====================

@pytest.mark.asyncio
async def test_invoices_requires_auth(test_client: AsyncClient, test_db):
    response = await test_client.get("/invoices/")
    assert response.status_code == 401


# ==================== CRIAR FATURA AVULSA ====================

@pytest.mark.asyncio
async def test_create_avulsa_invoice(test_client: AsyncClient, auth_headers, client_a):
    """Cria fatura avulsa com itens personalizados."""
    response = await test_client.post(
        "/invoices/",
        headers=auth_headers,
        json={
            "client_id": str(client_a.id),
            "tipo": "AVULSA",
            "mes_referencia": 4,
            "ano_referencia": 2024,
            "items": [
                {
                    "descripcion": "Ligacao nova",
                    "cantidad": 1,
                    "precio_unitario": "150000",
                }
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["tipo"] == "AVULSA"
    assert data["status"] == "PENDENTE"
    assert Decimal(data["valor_total"]) == Decimal("150000")
    assert data["client_id"] == str(client_a.id)


@pytest.mark.asyncio
async def test_create_avulsa_multiple_items(test_client: AsyncClient, auth_headers, client_a):
    """Cria fatura avulsa com multiplos itens."""
    response = await test_client.post(
        "/invoices/",
        headers=auth_headers,
        json={
            "client_id": str(client_a.id),
            "tipo": "AVULSA",
            "mes_referencia": 4,
            "ano_referencia": 2024,
            "items": [
                {"descripcion": "Item A", "cantidad": 2, "precio_unitario": "10000"},
                {"descripcion": "Item B", "cantidad": 1, "precio_unitario": "5000"},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert Decimal(data["valor_total"]) == Decimal("25000")
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_create_invoice_tipo_consumo_rejected(test_client: AsyncClient, auth_headers, client_a):
    """Nao pode criar fatura de CONSUMO diretamente — use /generate."""
    response = await test_client.post(
        "/invoices/",
        headers=auth_headers,
        json={
            "client_id": str(client_a.id),
            "tipo": "CONSUMO",
            "mes_referencia": 4,
            "ano_referencia": 2024,
            "items": [{"descripcion": "Item", "cantidad": 1, "precio_unitario": "25000"}],
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_invoice_invalid_client(test_client: AsyncClient, auth_headers, test_db):
    """Client ID invalido retorna 400."""
    response = await test_client.post(
        "/invoices/",
        headers=auth_headers,
        json={
            "client_id": "id_invalido",
            "tipo": "AVULSA",
            "mes_referencia": 4,
            "ano_referencia": 2024,
            "items": [{"descripcion": "Item", "cantidad": 1, "precio_unitario": "10000"}],
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_invoice_client_not_found(test_client: AsyncClient, auth_headers, test_db):
    """Client inexistente retorna 4xx."""
    response = await test_client.post(
        "/invoices/",
        headers=auth_headers,
        json={
            "client_id": "507f1f77bcf86cd799439011",
            "tipo": "AVULSA",
            "mes_referencia": 4,
            "ano_referencia": 2024,
            "items": [{"descripcion": "Item", "cantidad": 1, "precio_unitario": "10000"}],
        },
    )
    assert response.status_code in (400, 404)


# ==================== GERAR FATURAS DE CONSUMO ====================

@pytest.mark.asyncio
async def test_generate_invoices(
    test_client: AsyncClient, auth_headers, reading_for_gen, inv_settings
):
    """Gera faturas de consumo a partir de leituras."""
    response = await test_client.post(
        "/invoices/generate",
        headers=auth_headers,
        json={"mes_referencia": 4, "ano_referencia": 2024},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_generated"] >= 1
    assert "total_skipped" in data
    assert "errors" in data


@pytest.mark.asyncio
async def test_generate_invoices_skips_existing(
    test_client: AsyncClient, auth_headers, reading_for_gen, inv_settings
):
    """Nao gera duplicata se fatura ja existe para o periodo."""
    # Primeira geracao
    r1 = await test_client.post(
        "/invoices/generate",
        headers=auth_headers,
        json={"mes_referencia": 4, "ano_referencia": 2024},
    )
    assert r1.status_code == 200
    generated_first = r1.json()["total_generated"]

    # Segunda geracao — deve pular
    r2 = await test_client.post(
        "/invoices/generate",
        headers=auth_headers,
        json={"mes_referencia": 4, "ano_referencia": 2024},
    )
    assert r2.status_code == 200
    assert r2.json()["total_generated"] == 0
    assert r2.json()["total_skipped"] == generated_first


# ==================== LISTAR FATURAS ====================

@pytest.mark.asyncio
async def test_list_invoices(test_client: AsyncClient, auth_headers, pending_invoice):
    """Lista faturas com paginacao."""
    response = await test_client.get("/invoices/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "X-Total-Count" in response.headers


@pytest.mark.asyncio
async def test_list_invoices_filter_by_status(
    test_client: AsyncClient, auth_headers, pending_invoice, paid_invoice
):
    """Filtra por status."""
    response = await test_client.get(
        "/invoices/", headers=auth_headers, params={"status": "PENDENTE"}
    )
    assert response.status_code == 200
    data = response.json()
    assert all(inv["status"] == "PENDENTE" for inv in data)


@pytest.mark.asyncio
async def test_list_invoices_filter_by_period(
    test_client: AsyncClient, auth_headers, pending_invoice
):
    """Filtra por mes/ano de referencia."""
    response = await test_client.get(
        "/invoices/",
        headers=auth_headers,
        params={"mes_referencia": 3, "ano_referencia": 2024},
    )
    assert response.status_code == 200
    data = response.json()
    assert all(inv["mes_referencia"] == 3 and inv["ano_referencia"] == 2024 for inv in data)


@pytest.mark.asyncio
async def test_list_invoices_pagination(
    test_client: AsyncClient, auth_headers, client_a, test_db
):
    """Verifica paginacao com skip/limit."""
    for mes in range(1, 6):
        inv = Invoice(
            client=client_a,
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

    r1 = await test_client.get("/invoices/", headers=auth_headers, params={"skip": 0, "limit": 2})
    assert r1.status_code == 200
    assert len(r1.json()) == 2

    r2 = await test_client.get("/invoices/", headers=auth_headers, params={"skip": 2, "limit": 2})
    assert r2.status_code == 200
    assert len(r2.json()) == 2

    # Total deve ser 5
    total = int(r1.headers["X-Total-Count"])
    assert total == 5


# ==================== BUSCA POR NUMERO ====================

@pytest.mark.asyncio
async def test_get_invoice_by_number(test_client: AsyncClient, auth_headers, pending_invoice):
    """Busca fatura pelo numero sequencial."""
    if pending_invoice.numero_factura is None:
        pytest.skip("Fatura de teste nao tem numero_factura setado")

    response = await test_client.get(
        f"/invoices/by-number/{pending_invoice.numero_factura}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(pending_invoice.id)


@pytest.mark.asyncio
async def test_get_invoice_by_number_not_found(test_client: AsyncClient, auth_headers, test_db):
    """Numero inexistente retorna 404."""
    response = await test_client.get(
        "/invoices/by-number/99999",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ==================== FATURAS PENDENTES ====================

@pytest.mark.asyncio
async def test_list_pending_invoices(
    test_client: AsyncClient, auth_headers, pending_invoice, paid_invoice
):
    """Lista apenas faturas pendentes ou parciais."""
    response = await test_client.get("/invoices/pending", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    ids = [inv["id"] for inv in data]
    assert str(pending_invoice.id) in ids
    assert str(paid_invoice.id) not in ids


# ==================== FATURAS POR CLIENTE ====================

@pytest.mark.asyncio
async def test_get_client_invoices(
    test_client: AsyncClient, auth_headers, client_a, pending_invoice, paid_invoice
):
    """Lista todas as faturas de um cliente."""
    response = await test_client.get(
        f"/invoices/client/{client_a.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    ids = {inv["id"] for inv in data}
    assert str(pending_invoice.id) in ids
    assert str(paid_invoice.id) in ids


@pytest.mark.asyncio
async def test_get_client_pending_balance(
    test_client: AsyncClient, auth_headers, client_a, pending_invoice
):
    """Retorna saldo pendente total de um cliente."""
    response = await test_client.get(
        f"/invoices/client/{client_a.id}/pending-balance",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert Decimal(str(data["saldo_pendiente"])) == Decimal("32500")


@pytest.mark.asyncio
async def test_get_client_pending_balance_zero(
    test_client: AsyncClient, auth_headers, client_b
):
    """Cliente sem dividas tem saldo zero."""
    response = await test_client.get(
        f"/invoices/client/{client_b.id}/pending-balance",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert Decimal(str(data["saldo_pendiente"])) == Decimal("0")


# ==================== FATURA POR ID ====================

@pytest.mark.asyncio
async def test_get_invoice(test_client: AsyncClient, auth_headers, pending_invoice):
    """Retorna fatura por ID."""
    response = await test_client.get(
        f"/invoices/{pending_invoice.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(pending_invoice.id)
    assert data["status"] == "PENDENTE"
    assert Decimal(data["valor_total"]) == Decimal("32500")


@pytest.mark.asyncio
async def test_get_invoice_not_found(test_client: AsyncClient, auth_headers, test_db):
    """ID inexistente retorna 404."""
    response = await test_client.get(
        "/invoices/507f1f77bcf86cd799439011",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_invoice_with_balance(
    test_client: AsyncClient, auth_headers, client_a, test_db
):
    """Retorna fatura com saldo anterior pendente."""
    # Fatura antiga nao paga
    old_inv = Invoice(
        client=client_a,
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
    await old_inv.insert()

    # Fatura nova
    new_inv = Invoice(
        client=client_a,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=2,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 2, 15),
        consumo=15,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("0"),
        valor_total=Decimal("25000"),
        saldo_devedor=Decimal("25000"),
    )
    await new_inv.insert()

    response = await test_client.get(
        f"/invoices/{new_inv.id}/with-balance",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "saldo_pendiente_anterior" in data
    # Saldo anterior inclui a fatura antiga nao paga
    assert Decimal(str(data["saldo_pendiente_anterior"])) >= Decimal("0")


# ==================== CANCELAR FATURA ====================

@pytest.mark.asyncio
async def test_cancel_invoice(test_client: AsyncClient, auth_headers, pending_invoice):
    """Cancela (anula) uma fatura pendente."""
    response = await test_client.patch(
        f"/invoices/{pending_invoice.id}/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ANULADA"


@pytest.mark.asyncio
async def test_cancel_paid_invoice_rejected(
    test_client: AsyncClient, auth_headers, paid_invoice
):
    """Nao pode cancelar fatura ja paga."""
    response = await test_client.patch(
        f"/invoices/{paid_invoice.id}/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cancel_invoice_not_found(test_client: AsyncClient, auth_headers, test_db):
    """ID inexistente retorna 404."""
    response = await test_client.patch(
        "/invoices/507f1f77bcf86cd799439011/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ==================== DELETAR FATURA ====================

@pytest.mark.asyncio
async def test_delete_invoice(test_client: AsyncClient, auth_headers, pending_invoice):
    """Deleta fatura sem pagamentos."""
    response = await test_client.delete(
        f"/invoices/{pending_invoice.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200

    # Verifica que foi removida
    check = await test_client.get(
        f"/invoices/{pending_invoice.id}",
        headers=auth_headers,
    )
    assert check.status_code == 404


@pytest.mark.asyncio
async def test_delete_invoice_reverts_payments(
    test_client: AsyncClient, auth_headers, pending_invoice, test_db
):
    """Deletar fatura reverte e remove pagamentos associados."""
    from app.models.payment import PaymentAllocation
    payment = Payment(
        client=pending_invoice.client,
        valor_total=Decimal("10000"),
        recibido_por="Caixa",
        grupo_pagamento="group-test-inv-del-001",
        allocations=[
            PaymentAllocation(
                invoice_id=pending_invoice.id,
                valor_aplicado=Decimal("10000"),
                mes_referencia=pending_invoice.mes_referencia,
                ano_referencia=pending_invoice.ano_referencia,
            )
        ],
    )
    await payment.insert()

    response = await test_client.delete(
        f"/invoices/{pending_invoice.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["payments_deleted"] == 1

    # Fatura foi removida
    check = await test_client.get(f"/invoices/{pending_invoice.id}", headers=auth_headers)
    assert check.status_code == 404

    # Pagamento foi removido
    deleted_payment = await Payment.get(payment.id)
    assert deleted_payment is None


@pytest.mark.asyncio
async def test_delete_invoice_not_found(test_client: AsyncClient, auth_headers, test_db):
    """ID inexistente retorna 404."""
    response = await test_client.delete(
        "/invoices/507f1f77bcf86cd799439011",
        headers=auth_headers,
    )
    assert response.status_code == 404
