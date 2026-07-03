"""
Testes para o servico de geracao de faturas.

Testa:
- Geracao de fatura a partir de leitura
- Calculo de excedente
- Faturas avulsas
- Geracao em lote

NOTA: Sistema usa TARIFA UNICA GLOBAL. Nao ha mais tipos de tarifa.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.reading import Reading
from app.models.invoice import Invoice, InvoiceType, InvoiceItem
from app.models.settings import SystemSettings
from app.services.invoice_generation import InvoiceGenerationService


def test_calculate_excess_within_limit():
    """Testa calculo de excedente dentro do limite."""
    excess = InvoiceGenerationService.calculate_excess(
        consumo=10,
        limite_base=15,
        valor_excedente_m3=Decimal("1500")
    )
    assert excess == Decimal("0")


def test_calculate_excess_at_limit():
    """Testa calculo de excedente no limite exato."""
    excess = InvoiceGenerationService.calculate_excess(
        consumo=15,
        limite_base=15,
        valor_excedente_m3=Decimal("1500")
    )
    assert excess == Decimal("0")


def test_calculate_excess_over_limit():
    """Testa calculo de excedente acima do limite."""
    excess = InvoiceGenerationService.calculate_excess(
        consumo=20,  # 5 m3 acima
        limite_base=15,
        valor_excedente_m3=Decimal("1500")
    )
    assert excess == Decimal("7500")  # 5 * 1500


def test_calculate_excess_high_consumption():
    """Testa calculo de excedente com alto consumo."""
    excess = InvoiceGenerationService.calculate_excess(
        consumo=50,  # 35 m3 acima
        limite_base=15,
        valor_excedente_m3=Decimal("1500")
    )
    assert excess == Decimal("52500")  # 35 * 1500


@pytest.mark.asyncio
async def test_generate_invoice_from_reading(test_db, sample_client, test_settings):
    """Testa geracao de fatura a partir de leitura."""
    # Cria leitura
    reading = Reading(
        client=sample_client,
        valor_leitura=100,
        mes_referencia=5,
        ano_referencia=2024,
        consumo_calculado=18,  # 3 m3 acima do limite
    )
    await reading.insert()

    result = await InvoiceGenerationService.generate_invoice_from_reading(
        reading, test_settings
    )

    assert result.success is True
    assert result.invoice_id is not None

    # Verifica fatura criada
    invoice = await Invoice.get(result.invoice_id)
    assert invoice is not None
    assert invoice.tipo == InvoiceType.CONSUMO
    assert invoice.consumo == 18
    assert invoice.tarifa_base == Decimal("25000")
    assert invoice.excedente == Decimal("4500")  # 3 * 1500
    assert invoice.valor_total == Decimal("29500")
    assert invoice.saldo_devedor == Decimal("29500")


@pytest.mark.asyncio
async def test_generate_invoice_duplicate(test_db, sample_client, sample_reading, test_settings):
    """Testa que nao gera fatura duplicada."""
    # Primeira geracao
    result1 = await InvoiceGenerationService.generate_invoice_from_reading(
        sample_reading, test_settings
    )
    assert result1.success is True

    # Segunda geracao - deve falhar
    result2 = await InvoiceGenerationService.generate_invoice_from_reading(
        sample_reading, test_settings
    )
    assert result2.success is False
    assert "ja existe" in result2.error


@pytest.mark.asyncio
async def test_create_custom_invoice(test_db, sample_client):
    """Testa criacao de fatura avulsa."""
    items = [
        InvoiceItem(
            descripcion="Conexao nova",
            cantidad=1,
            precio_unitario=Decimal("150000"),
        ),
        InvoiceItem(
            descripcion="Material PVC",
            cantidad=3,
            precio_unitario=Decimal("25000"),
        ),
    ]

    result = await InvoiceGenerationService.create_custom_invoice(
        client_id=sample_client.id,
        items=items,
        mes_referencia=6,
        ano_referencia=2024,
    )

    assert result.success is True

    invoice = await Invoice.get(result.invoice_id)
    assert invoice.tipo == InvoiceType.AVULSA
    assert len(invoice.items) == 2
    assert invoice.valor_total == Decimal("225000")  # 150000 + 75000


@pytest.mark.asyncio
async def test_create_custom_invoice_no_items(test_db, sample_client):
    """Testa que fatura avulsa sem itens falha."""
    result = await InvoiceGenerationService.create_custom_invoice(
        client_id=sample_client.id,
        items=[],
        mes_referencia=6,
        ano_referencia=2024,
    )

    assert result.success is False
    assert "pelo menos um item" in result.error


@pytest.mark.asyncio
async def test_generate_batch(test_db, sample_client, test_settings):
    """Testa geracao em lote."""
    # Cria varias leituras
    for i, mes in enumerate([7, 8, 9], start=1):
        reading = Reading(
            client=sample_client,
            valor_leitura=100 + (i * 20),
            mes_referencia=mes,
            ano_referencia=2024,
            consumo_calculado=15 + i,
        )
        await reading.insert()

    # Gera faturas para o mes 7
    result = await InvoiceGenerationService.generate_batch(
        mes=7,
        ano=2024,
    )

    assert result.total_generated == 1
    assert result.total_skipped == 0
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_generate_batch_skip_existing(test_db, sample_client, sample_reading, sample_invoice, test_settings):
    """Testa que geracao em lote pula faturas existentes."""
    # sample_invoice ja existe para mes 1/2024
    # sample_reading existe para o mesmo periodo

    result = await InvoiceGenerationService.generate_batch(
        mes=1,
        ano=2024,
    )

    # Deve pular porque ja existe fatura para a leitura
    assert result.total_generated == 0
    assert result.total_skipped == 1


@pytest.mark.asyncio
async def test_invoice_item_subtotal():
    """Testa calculo de subtotal do item."""
    item = InvoiceItem(
        descripcion="Teste",
        cantidad=5,
        precio_unitario=Decimal("10000"),
    )

    assert item.subtotal == Decimal("50000")


# ---- Testes calculate_due_date ----

def test_calculate_due_date_with_dia_geracao():
    """dia_geracao=10, periodo 3/2024, dias_vencimiento=15 -> 25/03/2024."""
    result = InvoiceGenerationService.calculate_due_date(
        mes_referencia=3,
        ano_referencia=2024,
        dias_vencimiento=15,
        dia_geracao=10,
    )
    assert result == date(2024, 3, 25)


def test_calculate_due_date_fallback_settings():
    """Sem dia_geracao, usa dia_geracao_faturas."""
    result = InvoiceGenerationService.calculate_due_date(
        mes_referencia=6,
        ano_referencia=2024,
        dias_vencimiento=15,
        dia_geracao=None,
        dia_geracao_faturas=5,
    )
    # 2024-06-05 + 15 dias = 2024-06-20
    assert result == date(2024, 6, 20)


def test_calculate_due_date_clamps_month_end():
    """dia_geracao=31 em fevereiro clamp para ultimo dia."""
    result = InvoiceGenerationService.calculate_due_date(
        mes_referencia=2,
        ano_referencia=2024,  # Bissexto
        dias_vencimiento=15,
        dia_geracao=31,
    )
    # 2024-02-29 + 15 dias = 2024-03-15
    assert result == date(2024, 3, 15)


def test_calculate_due_date_clamps_february_non_leap():
    """dia_geracao=30 em fevereiro nao bissexto."""
    result = InvoiceGenerationService.calculate_due_date(
        mes_referencia=2,
        ano_referencia=2025,  # Nao bissexto
        dias_vencimiento=15,
        dia_geracao=30,
    )
    # 2025-02-28 + 15 dias = 2025-03-15
    assert result == date(2025, 3, 15)


# ---- Testes generate_minimum_invoices ----

@pytest_asyncio.fixture
async def three_active_clients(test_db):
    """3 clientes ativos para testes de geracao minima."""
    clients = []
    for i in range(1, 4):
        c = Client(
            nombre_completo=f"Cliente Min {i}",
            ci_ruc=f"MIN-{i:03d}",
            direccion="Calle Test",
            manzana="B",
            lote=str(i),
            numero_medidor=f"MMIN-{i:03d}",
            categoria=ClientCategory.RESIDENCIAL,
            status=ClientStatus.ATIVO,
        )
        await c.insert()
        clients.append(c)
    return clients


@pytest.mark.asyncio
async def test_generate_minimum_invoices_basic(test_db, three_active_clients, test_settings):
    """3 clientes, 1 com leitura -> 2 faturas minimas."""
    # Cria leitura apenas para o primeiro cliente
    reading = Reading(
        client=three_active_clients[0],
        valor_leitura=100,
        mes_referencia=3,
        ano_referencia=2025,
        consumo_calculado=20,
    )
    await reading.insert()

    result = await InvoiceGenerationService.generate_minimum_invoices(
        mes=3,
        ano=2025,
        settings=test_settings,
        dia_geracao=1,
    )

    assert result.total_generated == 2
    assert result.total_skipped == 0

    # Verifica faturas criadas
    invoices = await Invoice.find(
        Invoice.mes_referencia == 3,
        Invoice.ano_referencia == 2025,
    ).to_list()
    assert len(invoices) == 2

    for inv in invoices:
        assert inv.consumo == 0
        assert inv.reading_id is None
        assert inv.valor_total == Decimal("25000")
        assert inv.tarifa_base == Decimal("25000")
        assert inv.excedente == Decimal("0")


@pytest.mark.asyncio
async def test_generate_minimum_invoices_idempotent(test_db, three_active_clients, test_settings):
    """Rodar 2x, segunda vez skipa tudo."""
    result1 = await InvoiceGenerationService.generate_minimum_invoices(
        mes=4,
        ano=2025,
        settings=test_settings,
    )
    assert result1.total_generated == 3

    result2 = await InvoiceGenerationService.generate_minimum_invoices(
        mes=4,
        ano=2025,
        settings=test_settings,
    )
    assert result2.total_generated == 0
    assert result2.total_skipped == 3


@pytest.mark.asyncio
async def test_generate_batch_with_minimum(test_db, three_active_clients, test_settings):
    """Integracao: leituras para alguns + minimo para o resto."""
    # Leitura apenas para o primeiro cliente
    reading = Reading(
        client=three_active_clients[0],
        valor_leitura=120,
        mes_referencia=5,
        ano_referencia=2025,
        consumo_calculado=18,
    )
    await reading.insert()

    result = await InvoiceGenerationService.generate_batch(
        mes=5,
        ano=2025,
        gerar_sem_leitura_valor_minimo=True,
        dia_geracao=1,
    )

    # 1 da leitura + 2 minimas
    assert result.total_generated == 1
    assert result.total_minimum_generated == 2
    assert len(result.errors) == 0

    # Total de faturas criadas
    invoices = await Invoice.find(
        Invoice.mes_referencia == 5,
        Invoice.ano_referencia == 2025,
    ).to_list()
    assert len(invoices) == 3


@pytest.mark.asyncio
async def test_generate_batch_with_dia_geracao(test_db, sample_client, test_settings):
    """Vencimento usa dia_geracao em vez de date.today()."""
    reading = Reading(
        client=sample_client,
        valor_leitura=100,
        mes_referencia=6,
        ano_referencia=2025,
        consumo_calculado=10,
    )
    await reading.insert()

    result = await InvoiceGenerationService.generate_batch(
        mes=6,
        ano=2025,
        dia_geracao=10,
    )

    assert result.total_generated == 1

    invoice = await Invoice.find_one(
        Invoice.mes_referencia == 6,
        Invoice.ano_referencia == 2025,
    )
    # dia_geracao=10, dias_vencimiento=15 -> 2025-06-10 + 15 = 2025-06-25
    assert invoice.fecha_vencimiento == date(2025, 6, 25)


@pytest.mark.asyncio
async def test_generate_batch_idempotent_with_minimum(test_db, three_active_clients, test_settings):
    """Rodar generate_batch 2x com gerar_sem_leitura e tudo skipa."""
    result1 = await InvoiceGenerationService.generate_batch(
        mes=7,
        ano=2025,
        gerar_sem_leitura_valor_minimo=True,
    )
    assert result1.total_minimum_generated == 3

    result2 = await InvoiceGenerationService.generate_batch(
        mes=7,
        ano=2025,
        gerar_sem_leitura_valor_minimo=True,
    )
    assert result2.total_minimum_generated == 0
    assert result2.total_minimum_skipped == 3
