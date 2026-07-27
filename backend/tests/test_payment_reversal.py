"""
Testes do estorno (anulação) de pagamento + auditoria.

- Restaura o saldo/estado das faturas quitadas (total e parcial/múltiplas).
- Lança um ESTORNO no caixa (SAÍDA) sem apagar a ENTRADA original.
- Marca o pagamento como anulado (não apaga) e grava na trilha de auditoria.
- Bloqueia anulação dupla e quando o subsídio já foi faturado ao padrino.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.payment import Payment
from app.models.finance import CashTransaction, TransactionType, TransactionCategory
from app.models.sponsor import SponsorDebt, SponsorDebtStatus
from app.models.audit import AuditLog
from app.services.payment_distribution import PaymentDistributionService
from app.services.payment_reversal import anular_payment, PaymentReversalError, PaymentNotFound


async def _pay(client_id, valor, **kw):
    res = await PaymentDistributionService.process_payment(
        client_id=client_id, valor_total=Decimal(valor), **kw)
    assert res.success
    return res


@pytest.mark.asyncio
async def test_anular_restaura_fatura(test_settings, sample_client, sample_invoice):
    res = await _pay(sample_client.id, "32500")
    inv = await Invoice.get(sample_invoice.id)
    assert inv.status == InvoiceStatus.PAGADA and inv.saldo_devedor == Decimal("0")

    result = await anular_payment(res.payment_id, "cobro duplicado", "cajero1")
    assert result["invoices_restored"] == 1

    inv2 = await Invoice.get(sample_invoice.id)
    assert inv2.status == InvoiceStatus.PENDENTE and inv2.saldo_devedor == Decimal("32500")

    p = await Payment.get(res.payment_id)
    assert p.anulada is True
    assert p.anulada_por == "cajero1"
    assert p.motivo_anulacion == "cobro duplicado"
    assert p.anulada_at is not None


@pytest.mark.asyncio
async def test_anular_lanca_estorno_no_caixa(test_settings, sample_client, sample_invoice):
    res = await _pay(sample_client.id, "32500")

    entradas = await CashTransaction.find(
        CashTransaction.reference_id == res.payment_id,
        CashTransaction.tipo == TransactionType.ENTRADA,
    ).to_list()
    assert len(entradas) == 1  # a ENTRADA original permanece

    await anular_payment(res.payment_id, "error de caja", "cajero1")

    estornos = await CashTransaction.find(
        CashTransaction.categoria == TransactionCategory.ESTORNO_PAGAMENTO,
    ).to_list()
    assert len(estornos) == 1
    assert estornos[0].tipo == TransactionType.SAIDA
    assert estornos[0].valor == Decimal("32500")


@pytest.mark.asyncio
async def test_anular_restaura_multiplas_faturas(test_settings, sample_client, multiple_invoices):
    inv1, inv2, inv3 = multiple_invoices  # 25000 / 30000 / 28000
    res = await _pay(sample_client.id, "40000")  # quita mes1, paga 15000 do mes2

    result = await anular_payment(res.payment_id, "x", "u")
    assert result["invoices_restored"] == 2

    r1 = await Invoice.get(inv1.id)
    r2 = await Invoice.get(inv2.id)
    r3 = await Invoice.get(inv3.id)
    assert r1.status == InvoiceStatus.PENDENTE and r1.saldo_devedor == Decimal("25000")
    assert r2.status == InvoiceStatus.PENDENTE and r2.saldo_devedor == Decimal("30000")
    assert r3.status == InvoiceStatus.PENDENTE and r3.saldo_devedor == Decimal("28000")


@pytest.mark.asyncio
async def test_anular_duas_vezes_falha(test_settings, sample_client, sample_invoice):
    res = await _pay(sample_client.id, "32500")
    await anular_payment(res.payment_id, "primera", "u")
    with pytest.raises(PaymentReversalError):
        await anular_payment(res.payment_id, "segunda", "u")


@pytest.mark.asyncio
async def test_anular_sem_motivo_falha(test_settings, sample_client, sample_invoice):
    res = await _pay(sample_client.id, "32500")
    with pytest.raises(PaymentReversalError):
        await anular_payment(res.payment_id, "  ", "u")


@pytest.mark.asyncio
async def test_anular_pago_inexistente(test_settings):
    from beanie import PydanticObjectId
    with pytest.raises(PaymentNotFound):
        await anular_payment(PydanticObjectId(), "x", "u")


@pytest.mark.asyncio
async def test_anular_registra_auditoria(test_settings, sample_client, sample_invoice):
    res = await _pay(sample_client.id, "32500")
    await anular_payment(res.payment_id, "cobro duplicado", "cajero1")

    logs = await AuditLog.find(AuditLog.action == "payment.anular").to_list()
    assert len(logs) == 1
    log = logs[0]
    assert log.usuario == "cajero1"
    assert log.motivo == "cobro duplicado"
    assert log.entity_id == str(res.payment_id)
    assert log.before is not None and log.after.get("anulada") is True


@pytest.mark.asyncio
async def test_anular_bloqueado_se_subsidio_faturado(test_settings):
    """Se o subsídio já virou dívida FATURADA ao padrino, não dá pra anular limpo."""
    sponsor = Client(
        nombre_completo="Municipio", ci_ruc="9000001", direccion="Av. Central 1",
        categoria=ClientCategory.RESIDENCIAL, status=ClientStatus.ATIVO, is_sponsor=True,
    )
    await sponsor.insert()
    client = Client(
        nombre_completo="Cliente Subsidiado", ci_ruc="8000001", direccion="Calle 2",
        categoria=ClientCategory.RESIDENCIAL, status=ClientStatus.ATIVO,
        sponsor_id=sponsor.id, subsidio_porcentagem=50, has_sponsor=True,
    )
    await client.insert()
    inv = Invoice(
        client=client, tipo=InvoiceType.CONSUMO, status=InvoiceStatus.PENDENTE,
        mes_referencia=1, ano_referencia=2024, fecha_vencimiento=date(2024, 1, 15),
        consumo=10, tarifa_base=Decimal("25000"), excedente=Decimal("0"),
        valor_total=Decimal("25000"), saldo_devedor=Decimal("25000"),
    )
    await inv.insert()

    res = await _pay(client.id, "25000", aplicar_subsidio=True)
    sds = await SponsorDebt.find(SponsorDebt.payment_id == res.payment_id).to_list()
    assert len(sds) == 1

    sds[0].status = SponsorDebtStatus.FATURADO
    await sds[0].save()

    with pytest.raises(PaymentReversalError):
        await anular_payment(res.payment_id, "x", "u")


# --- factura electrónica: o estorno pede a cancelación fiscal ---------------

async def _emision_emitida(payment_id, rid="req-rev"):
    from app.models.sifen import SifenEmission, EmissionStatus
    job = SifenEmission(
        client_request_id=rid, created_by="cajero1", status=EmissionStatus.EMITIDA,
        doc="7184730", tipo_id=1, cdc="01CDCREV", numero_documento="0000121",
        items=[], condicion={}, payment_id=payment_id,
    )
    await job.insert()
    return job


@pytest.mark.asyncio
async def test_anular_solicita_cancelacion_fiscal(test_settings, sample_client, sample_invoice):
    from app.models.sifen import SifenEmission, EmissionStatus

    res = await _pay(sample_client.id, "32500")
    emision = await _emision_emitida(res.payment_id)

    result = await anular_payment(res.payment_id, "error de monto", "cajero1")

    assert result["sifen"]["cancelacion"] == "solicitada"
    assert result["sifen"]["cdc"] == "01CDCREV"

    j = await SifenEmission.get(emision.id)
    assert j.cancel_solicitada is True
    assert "error de monto" in (j.cancel_motivo or "")
    # o DTE segue EMITIDA: quem cancela no SET é o coordenador, depois
    assert j.status == EmissionStatus.EMITIDA
    assert j.cancelada_at is None


@pytest.mark.asyncio
async def test_anular_sin_factura_electronica_no_pide_nada(test_settings, sample_client, sample_invoice):
    res = await _pay(sample_client.id, "32500")
    result = await anular_payment(res.payment_id, "cobro duplicado", "cajero1")
    assert result["sifen"] is None
