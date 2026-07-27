"""
Testes das funcionalidades do Modo Caja (backend):
- Pagamento DIRECIONADO (invoice_ids): paga só as faturas marcadas.
- ADIANTAMENTO (prepay_periods): gera fatura mínima futura e quita na mesma transação.
- Geração de mês adiantado idempotente.
- Caminho histórico (sem seleção) preservado: distribui da mais antiga → recente.
- SettingsResponse expõe o IVA da água (usado pela factura legal).
"""

from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.payment_distribution import PaymentDistributionService
from app.services.invoice_generation import InvoiceGenerationService


@pytest.mark.asyncio
async def test_pagamento_direcionado_paga_so_a_marcada(
    test_settings, sample_client, multiple_invoices
):
    """invoice_ids=[fatura do meio] → só ela é quitada; as outras ficam intactas."""
    inv1, inv2, inv3 = multiple_invoices  # mes 1/2/3 — 25000/30000/28000

    res = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=Decimal("30000"),
        invoice_ids=[inv2.id],
    )

    assert res.success
    assert {str(a.invoice_id) for a in res.allocations} == {str(inv2.id)}

    inv1r = await Invoice.get(inv1.id)
    inv2r = await Invoice.get(inv2.id)
    inv3r = await Invoice.get(inv3.id)
    assert inv2r.status == InvoiceStatus.PAGADA and inv2r.saldo_devedor == Decimal("0")
    assert inv1r.status == InvoiceStatus.PENDENTE and inv1r.saldo_devedor == Decimal("25000")
    assert inv3r.status == InvoiceStatus.PENDENTE and inv3r.saldo_devedor == Decimal("28000")


@pytest.mark.asyncio
async def test_adiantamento_gera_e_quita_mes_futuro(test_settings, sample_client):
    """prepay_periods gera fatura mínima (tarifa_base, consumo=0) já paga."""
    tarifa = test_settings.tarifa_base

    res = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=tarifa,
        prepay_periods=[(8, 2026)],
    )

    assert res.success
    inv = await Invoice.find_one(
        {"client.$id": sample_client.id},
        Invoice.mes_referencia == 8,
        Invoice.ano_referencia == 2026,
    )
    assert inv is not None
    assert inv.status == InvoiceStatus.PAGADA
    assert inv.valor_total == tarifa
    assert inv.consumo == 0


@pytest.mark.asyncio
async def test_direcionado_mais_adiantamento(test_settings, sample_client, sample_invoice):
    """Paga uma pendente marcada + adianta um mês futuro, tudo numa transação."""
    tarifa = test_settings.tarifa_base
    total = sample_invoice.saldo_devedor + tarifa

    res = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=total,
        invoice_ids=[sample_invoice.id],
        prepay_periods=[(8, 2026)],
    )

    assert res.success
    inv1 = await Invoice.get(sample_invoice.id)
    fut = await Invoice.find_one(
        {"client.$id": sample_client.id},
        Invoice.mes_referencia == 8,
        Invoice.ano_referencia == 2026,
    )
    assert inv1.status == InvoiceStatus.PAGADA
    assert fut is not None and fut.status == InvoiceStatus.PAGADA


@pytest.mark.asyncio
async def test_generate_prepaid_month_idempotente(test_settings, sample_client):
    """Gerar o mesmo mês adiantado duas vezes não duplica a fatura."""
    a = await InvoiceGenerationService.generate_prepaid_month(sample_client, 9, 2026, test_settings)
    b = await InvoiceGenerationService.generate_prepaid_month(sample_client, 9, 2026, test_settings)

    assert a.id == b.id
    assert a.valor_total == test_settings.tarifa_base
    assert a.consumo == 0
    count = await Invoice.find(
        {"client.$id": sample_client.id},
        Invoice.mes_referencia == 9,
        Invoice.ano_referencia == 2026,
    ).count()
    assert count == 1


@pytest.mark.asyncio
async def test_caminho_historico_mais_antiga_primeiro(
    test_settings, sample_client, multiple_invoices
):
    """Sem invoice_ids/prepay → distribui da mais antiga → recente (comportamento antigo)."""
    inv1, inv2, inv3 = multiple_invoices  # 25000 / 30000 / 28000

    res = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=Decimal("40000"),  # quita mes1 e paga 15000 do mes2
    )

    assert res.success
    inv1r = await Invoice.get(inv1.id)
    inv2r = await Invoice.get(inv2.id)
    inv3r = await Invoice.get(inv3.id)
    assert inv1r.status == InvoiceStatus.PAGADA
    assert inv2r.status == InvoiceStatus.PARCIAL and inv2r.saldo_devedor == Decimal("15000")
    assert inv3r.status == InvoiceStatus.PENDENTE and inv3r.saldo_devedor == Decimal("28000")


@pytest.mark.asyncio
async def test_settings_response_expoe_iva_agua(test_settings):
    """A factura legal lê o IVA da água do settings — precisa sair no response."""
    from app.routers.settings import settings_to_response

    resp = settings_to_response(test_settings)
    assert resp.iva_tasa_agua == test_settings.iva_tasa_agua
    assert resp.iva_afectacion_agua == test_settings.iva_afectacion_agua
