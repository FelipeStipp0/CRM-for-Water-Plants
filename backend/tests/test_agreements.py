"""
Testes do acordo de pagamento (parcelamento no balcão).

O que precisa ficar de pé:
- total do acordo = soma exata dos saldos, sem juros nem ajuste;
- a última parcela absorve a sobra da divisão (soma bate com o total);
- as faturas antigas ficam ANULADA **com saldo zero** — senão continuariam
  recebendo pagamento (`get_outstanding_invoices` filtra por saldo, não status);
- o cliente sai da dívida e do corte na hora;
- a parcela do mês entra na fatura daquele mês, com IVA e afetação próprios;
- entrada é um cobro de verdade e reduz o total antes de dividir;
- um acordo ativo por cliente: dívida nova refaz o acordo;
- quitar a última parcela fecha o acordo e devolve as faturas antigas.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.agreement import AgreementStatus, CuotaStatus, PaymentAgreement
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.payment import PaymentMethod
from app.services.agreement_service import (
    AgreementError, acuerdo_activo, crear_acuerdo, dividir_parcelas,
)
from app.services.invoice_generation import InvoiceGenerationService
from app.services.payment_distribution import PaymentDistributionService


async def _mk_factura(client: Client, mes: int, ano: int, valor: str,
                      tipo: InvoiceType = InvoiceType.CONSUMO) -> Invoice:
    inv = Invoice(
        client=client, tipo=tipo, status=InvoiceStatus.PENDENTE,
        mes_referencia=mes, ano_referencia=ano,
        fecha_vencimiento=date(ano, mes, 15),
        valor_total=Decimal(valor), saldo_devedor=Decimal(valor),
        fecha_emision=datetime(ano, mes, 1),
    )
    await inv.insert()
    return inv


# ------------------------------------------------------------------ divisão
def test_dividir_ultima_absorve_sobra():
    parcelas = dividir_parcelas(Decimal("100000"), 3)
    assert parcelas == [Decimal("33333"), Decimal("33333"), Decimal("33334")]
    assert sum(parcelas) == Decimal("100000")


def test_dividir_exato():
    assert dividir_parcelas(Decimal("90000"), 3) == [Decimal("30000")] * 3


def test_dividir_uma_parcela():
    assert dividir_parcelas(Decimal("77777"), 1) == [Decimal("77777")]


# ------------------------------------------------------------------ criação
@pytest.mark.asyncio
async def test_crear_acuerdo_anula_facturas_y_agenda_cuotas(
        test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "30000")
    await _mk_factura(sample_client, 2, 2026, "30000")
    await _mk_factura(sample_client, 3, 2026, "40000")

    r = await crear_acuerdo(
        client_id=sample_client.id, invoice_ids=None, n_parcelas=4,
        usuario="cajera",
    )
    acuerdo = r["acuerdo"]

    assert acuerdo["total_deuda"] == Decimal("100000")
    assert acuerdo["total_parcelado"] == Decimal("100000")
    assert len(acuerdo["parcelas"]) == 4
    assert sum(Decimal(str(p["valor"])) for p in acuerdo["parcelas"]) == Decimal("100000")
    assert len(acuerdo["facturas_anuladas"]) == 3

    # Faturas antigas: ANULADA e com saldo ZERO — o saldo é o que a consulta de
    # dívida olha, então zerar é o que impede a cobrança dupla.
    for inv in await Invoice.find({"client.$id": sample_client.id}).to_list():
        assert inv.status == InvoiceStatus.ANULADA
        assert inv.saldo_devedor == Decimal("0")
        assert inv.anulada_por_acuerdo_id is not None

    # E o cliente sai da dívida na hora.
    deuda = await PaymentDistributionService.calculate_total_debt(sample_client.id)
    assert deuda == 0


@pytest.mark.asyncio
async def test_crear_acuerdo_con_entrada_reduce_el_total(
        test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "50000")
    await _mk_factura(sample_client, 2, 2026, "50000")

    r = await crear_acuerdo(
        client_id=sample_client.id, invoice_ids=None, n_parcelas=2,
        usuario="cajera", entrada=Decimal("40000"),
        metodo=PaymentMethod.EFECTIVO,
    )
    acuerdo = r["acuerdo"]

    assert acuerdo["total_deuda"] == Decimal("100000")
    assert acuerdo["entrada"] == Decimal("40000")
    assert acuerdo["total_parcelado"] == Decimal("60000")
    assert sum(Decimal(str(p["valor"])) for p in acuerdo["parcelas"]) == Decimal("60000")
    # A entrada é um cobro de verdade: tem recibo (grupo) para imprimir.
    assert r["entrada_payment_id"] and r["entrada_grupo"]


@pytest.mark.asyncio
async def test_entrada_que_cubre_todo_no_arma_acuerdo(
        test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "50000")
    with pytest.raises(AgreementError):
        await crear_acuerdo(
            client_id=sample_client.id, invoice_ids=None, n_parcelas=3,
            usuario="cajera", entrada=Decimal("50000"))


@pytest.mark.asyncio
async def test_sin_deuda_no_hay_acuerdo(test_db, test_settings, sample_client):
    with pytest.raises(AgreementError):
        await crear_acuerdo(client_id=sample_client.id, invoice_ids=None,
                            n_parcelas=3, usuario="cajera")


@pytest.mark.asyncio
async def test_primera_cuota_en_mes_corriente_crea_factura_avulsa(
        test_db, test_settings, sample_client):
    hoy = date.today()
    await _mk_factura(sample_client, hoy.month, hoy.year, "60000")

    r = await crear_acuerdo(
        client_id=sample_client.id, invoice_ids=None, n_parcelas=3,
        usuario="cajera", primera_en_mes_corriente=True,
        cuota_iva_tasa=5, cuota_iva_afectacion=3,
    )
    parcelas = r["acuerdo"]["parcelas"]
    assert parcelas[0]["status"] == CuotaStatus.FACTURADA.value
    assert parcelas[0]["invoice_id"]

    inv = await Invoice.get(parcelas[0]["invoice_id"])
    assert inv.tipo == InvoiceType.AVULSA
    assert inv.saldo_devedor == Decimal(str(parcelas[0]["valor"]))
    # IVA da cuota é o escolhido no acordo, não o das configurações.
    assert inv.cuota_iva_tasa == 5
    assert inv.cuota_iva_afectacion == 3
    assert inv.cuota_numero == 1


# --------------------------------------------------------- cuota na geração
@pytest.mark.asyncio
async def test_cuota_entra_en_la_factura_del_mes(test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "90000")
    r = await crear_acuerdo(
        client_id=sample_client.id, invoice_ids=None, n_parcelas=3,
        usuario="cajera", cuota_iva_tasa=10, cuota_iva_afectacion=1,
    )
    primera = r["acuerdo"]["parcelas"][0]
    mes, ano, valor = primera["mes"], primera["ano"], Decimal(str(primera["valor"]))

    # A geração mínima do mês da parcela soma a cuota na fatura daquele mês.
    res = await InvoiceGenerationService.generate_minimum_invoices(
        mes=mes, ano=ano, settings=test_settings)
    assert res.total_generated == 1

    inv = await Invoice.find_one(
        {"client.$id": sample_client.id},
        Invoice.mes_referencia == mes,
        Invoice.ano_referencia == ano,
        Invoice.tipo == InvoiceType.CONSUMO,
    )
    assert inv.valor_total == test_settings.tarifa_base + valor
    assert inv.saldo_devedor == test_settings.tarifa_base + valor
    assert inv.cuota_valor == valor
    assert inv.cuota_numero == 1

    acuerdo = await acuerdo_activo(sample_client.id)
    assert acuerdo.parcelas[0].status == CuotaStatus.FACTURADA
    assert acuerdo.parcelas[0].invoice_id == inv.id


@pytest.mark.asyncio
async def test_adelantar_mes_con_cuota_cobra_la_cuota(
        test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "60000")
    r = await crear_acuerdo(client_id=sample_client.id, invoice_ids=None,
                            n_parcelas=2, usuario="cajera")
    primera = r["acuerdo"]["parcelas"][0]

    inv = await InvoiceGenerationService.generate_prepaid_month(
        sample_client, primera["mes"], primera["ano"], test_settings)
    assert inv.cuota_valor == Decimal(str(primera["valor"]))
    assert inv.valor_total == test_settings.tarifa_base + inv.cuota_valor


# ------------------------------------------------------------------ refazer
@pytest.mark.asyncio
async def test_deuda_nueva_rehace_el_acuerdo(test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "60000")
    primero = (await crear_acuerdo(client_id=sample_client.id, invoice_ids=None,
                                   n_parcelas=3, usuario="cajera"))["acuerdo"]

    # Dívida nova enquanto o acordo corre.
    await _mk_factura(sample_client, 6, 2026, "30000")

    segundo = (await crear_acuerdo(client_id=sample_client.id, invoice_ids=None,
                                   n_parcelas=3, usuario="cajera"))["acuerdo"]

    viejo = await PaymentAgreement.get(primero["id"])
    assert viejo.status == AgreementStatus.REFEITO
    assert str(viejo.replaced_by_id) == segundo["id"]
    assert all(c.status == CuotaStatus.CANCELADA for c in viejo.parcelas)

    # Saldo remanescente + dívida nova, uma vez só (60000 do acordo velho, que
    # nunca foi faturado, + 30000 novos).
    assert segundo["total_parcelado"] == Decimal("90000")
    assert segundo["replaces_id"] == primero["id"]
    # Um acordo ATIVO por cliente.
    activos = await PaymentAgreement.find(
        {"client.$id": sample_client.id},
        PaymentAgreement.status == AgreementStatus.ACTIVO,
    ).to_list()
    assert len(activos) == 1

    # O retrato das faturas antigas viaja para o acordo novo: é o que se imprime
    # quando a dívida inteira acabar.
    ids = {f["invoice_id"] for f in segundo["facturas_anuladas"]}
    assert len(ids) == 2


# ------------------------------------------------------------------ quitação
@pytest.mark.asyncio
async def test_pagar_la_ultima_cuota_cierra_el_acuerdo(
        test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "40000")
    r = await crear_acuerdo(client_id=sample_client.id, invoice_ids=None,
                            n_parcelas=2, usuario="cajera")
    acuerdo_id = r["acuerdo"]["id"]

    # Fatura cada parcela e paga na hora.
    quitado = None
    for parcela in r["acuerdo"]["parcelas"]:
        inv = await InvoiceGenerationService.generate_prepaid_month(
            sample_client, parcela["mes"], parcela["ano"], test_settings)
        pago = await PaymentDistributionService.process_payment(
            client_id=sample_client.id, valor_total=inv.saldo_devedor,
            metodo=PaymentMethod.EFECTIVO, aplicar_subsidio=False,
            invoice_ids=[inv.id],
        )
        assert pago.success
        quitado = pago.acuerdo_quitado

    acuerdo = await PaymentAgreement.get(acuerdo_id)
    assert acuerdo.status == AgreementStatus.QUITADO
    assert all(c.status == CuotaStatus.PAGADA for c in acuerdo.parcelas)
    # O último pagamento devolve o acordo (com as faturas antigas) para a caja
    # imprimir junto do recibo.
    assert quitado is not None
    assert quitado["numero_fmt"] == acuerdo.numero_fmt
    assert len(quitado["facturas_anuladas"]) == 1


@pytest.mark.asyncio
async def test_pago_intermedio_no_cierra_el_acuerdo(
        test_db, test_settings, sample_client):
    await _mk_factura(sample_client, 1, 2026, "40000")
    r = await crear_acuerdo(client_id=sample_client.id, invoice_ids=None,
                            n_parcelas=2, usuario="cajera")
    primera = r["acuerdo"]["parcelas"][0]
    inv = await InvoiceGenerationService.generate_prepaid_month(
        sample_client, primera["mes"], primera["ano"], test_settings)
    pago = await PaymentDistributionService.process_payment(
        client_id=sample_client.id, valor_total=inv.saldo_devedor,
        metodo=PaymentMethod.EFECTIVO, aplicar_subsidio=False,
        invoice_ids=[inv.id],
    )
    assert pago.acuerdo_quitado is None
    acuerdo = await PaymentAgreement.get(r["acuerdo"]["id"])
    assert acuerdo.status == AgreementStatus.ACTIVO
    assert acuerdo.parcelas[0].status == CuotaStatus.PAGADA
    assert acuerdo.parcelas[1].status == CuotaStatus.PENDIENTE
