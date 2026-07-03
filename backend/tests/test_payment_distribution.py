"""
Testes para o servico de distribuicao de pagamentos.

Testa a logica core de distribuicao recursiva:
- Pagamento unico quitando uma fatura
- Pagamento parcial
- Pagamento quitando multiplas faturas
- Overpayment (pagamento maior que divida)
"""

from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.payment_distribution import PaymentDistributionService


@pytest.mark.asyncio
async def test_distribute_amount_single_invoice(sample_invoice):
    """Testa distribuicao para uma unica fatura."""
    invoices = [sample_invoice]
    amount = Decimal("32500")  # Valor exato

    allocations, overpayment = PaymentDistributionService.distribute_amount(
        amount, invoices
    )

    assert len(allocations) == 1
    assert allocations[0].valor_aplicado == Decimal("32500")
    assert allocations[0].saldo_restante == Decimal("0")
    assert allocations[0].status_final == InvoiceStatus.PAGADA
    assert overpayment == Decimal("0")


@pytest.mark.asyncio
async def test_distribute_amount_partial_payment(sample_invoice):
    """Testa pagamento parcial de uma fatura."""
    invoices = [sample_invoice]
    amount = Decimal("20000")  # Menos que o total

    allocations, overpayment = PaymentDistributionService.distribute_amount(
        amount, invoices
    )

    assert len(allocations) == 1
    assert allocations[0].valor_aplicado == Decimal("20000")
    assert allocations[0].saldo_restante == Decimal("12500")
    assert allocations[0].status_final == InvoiceStatus.PARCIAL
    assert overpayment == Decimal("0")


@pytest.mark.asyncio
async def test_distribute_amount_multiple_invoices(multiple_invoices):
    """Testa distribuicao entre multiplas faturas."""
    # Total: 25000 + 30000 + 28000 = 83000
    amount = Decimal("60000")  # Quita as duas primeiras parcialmente

    allocations, overpayment = PaymentDistributionService.distribute_amount(
        amount, multiple_invoices
    )

    assert len(allocations) == 3  # Afeta as 3 faturas

    # Primeira fatura (25000) - quitada
    assert allocations[0].valor_aplicado == Decimal("25000")
    assert allocations[0].status_final == InvoiceStatus.PAGADA

    # Segunda fatura (30000) - quitada
    assert allocations[1].valor_aplicado == Decimal("30000")
    assert allocations[1].status_final == InvoiceStatus.PAGADA

    # Terceira fatura (28000) - parcial com 5000
    assert allocations[2].valor_aplicado == Decimal("5000")
    assert allocations[2].saldo_restante == Decimal("23000")
    assert allocations[2].status_final == InvoiceStatus.PARCIAL

    assert overpayment == Decimal("0")


@pytest.mark.asyncio
async def test_distribute_amount_overpayment(sample_invoice):
    """Testa pagamento maior que a divida."""
    invoices = [sample_invoice]
    amount = Decimal("50000")  # Mais que o total (32500)

    allocations, overpayment = PaymentDistributionService.distribute_amount(
        amount, invoices
    )

    assert len(allocations) == 1
    assert allocations[0].valor_aplicado == Decimal("32500")
    assert allocations[0].status_final == InvoiceStatus.PAGADA
    assert overpayment == Decimal("17500")  # 50000 - 32500


@pytest.mark.asyncio
async def test_distribute_amount_exact_total(multiple_invoices):
    """Testa pagamento exato do total."""
    total = sum(inv.saldo_devedor for inv in multiple_invoices)  # 83000

    allocations, overpayment = PaymentDistributionService.distribute_amount(
        total, multiple_invoices
    )

    assert len(allocations) == 3
    assert all(a.status_final == InvoiceStatus.PAGADA for a in allocations)
    assert overpayment == Decimal("0")


@pytest.mark.asyncio
async def test_process_payment_success(test_db, sample_client, sample_invoice):
    """Testa processamento completo de pagamento."""
    result = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=Decimal("32500"),
        recibido_por="Test User",
    )

    assert result.success is True
    assert result.payment_id is not None
    assert len(result.allocations) == 1
    assert result.total_applied == Decimal("32500")
    assert result.overpayment == Decimal("0")

    # Verifica que a fatura foi atualizada
    updated_invoice = await Invoice.get(sample_invoice.id)
    assert updated_invoice.status == InvoiceStatus.PAGADA
    assert updated_invoice.saldo_devedor == Decimal("0")


@pytest.mark.asyncio
async def test_process_payment_no_debt(test_db, sample_client):
    """Testa pagamento quando nao ha divida."""
    result = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=Decimal("10000"),
    )

    assert result.success is False
    assert "nao possui faturas pendentes" in result.error


@pytest.mark.asyncio
async def test_process_payment_invalid_client(test_db):
    """Testa pagamento com cliente invalido."""
    from beanie import PydanticObjectId

    fake_id = PydanticObjectId()

    result = await PaymentDistributionService.process_payment(
        client_id=fake_id,
        valor_total=Decimal("10000"),
    )

    assert result.success is False
    assert "nao encontrado" in result.error


@pytest.mark.asyncio
async def test_calculate_total_debt(test_db, sample_client, multiple_invoices):
    """Testa calculo de divida total."""
    total = await PaymentDistributionService.calculate_total_debt(sample_client.id)

    expected = sum(inv.saldo_devedor for inv in multiple_invoices)
    assert total == expected


@pytest.mark.asyncio
async def test_get_outstanding_invoices_order(test_db, sample_client, multiple_invoices):
    """Testa que faturas sao retornadas na ordem correta."""
    invoices = await PaymentDistributionService.get_outstanding_invoices(
        sample_client.id
    )

    # Deve estar ordenado por mes (mais antiga primeiro)
    assert len(invoices) == 3
    assert invoices[0].mes_referencia == 1
    assert invoices[1].mes_referencia == 2
    assert invoices[2].mes_referencia == 3
