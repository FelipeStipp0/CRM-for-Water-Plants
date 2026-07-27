"""
Testes da sessao de caja: numeracao sequencial por ordem de apertura, uma caja
aberta por operador, agregacao escopada ao turno (nao ao dia), estorno saindo da
gaveta de quem estorna e a diferencia no cierre.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models.payment import Payment, PaymentMethod
from app.models.finance import (
    CashTransaction, TransactionType, TransactionCategory,
    CashSession, CashSessionStatus,
)
from app.services.caja_service import (
    CajaError, abrir_caja, cerrar_caja, computar_sesion, get_caja_abierta,
    sesion_activa_id,
)

_seq = 0


async def _mk_pago(client, valor, metodo, operador, sesion=None, anulada=False):
    global _seq
    _seq += 1
    p = Payment(
        client=client, valor_total=Decimal(valor), metodo=metodo,
        grupo_pagamento=f"g{_seq}", recibido_por=operador, anulada=anulada,
        cash_session_id=sesion.id if sesion else None,
        fecha_pago=datetime.now(),
    )
    await p.insert()
    return p


async def _mk_estorno(pago, operador, sesion):
    est = CashTransaction(
        tipo=TransactionType.SAIDA, categoria=TransactionCategory.ESTORNO_PAGAMENTO,
        valor=pago.valor_total, descripcion="estorno", registrado_por=operador,
        reference_id=pago.id, reference_type="payment_estorno",
        cash_session_id=sesion.id,
    )
    await est.insert()
    pago.anulada = True
    await pago.save()
    return est


@pytest.mark.asyncio
async def test_numeracion_sigue_orden_de_apertura(test_db):
    a = await abrir_caja("rosa", Decimal("50000"))
    await cerrar_caja(a, Decimal("50000"), "rosa")
    b = await abrir_caja("carlos", Decimal("0"))
    c = await abrir_caja("rosa", Decimal("20000"))

    assert (a.numero, b.numero, c.numero) == (1, 2, 3)
    assert a.numero_fmt == "01"
    assert c.status == CashSessionStatus.ABIERTA


@pytest.mark.asyncio
async def test_una_caja_abierta_por_operador(test_db):
    await abrir_caja("rosa", Decimal("10000"))
    with pytest.raises(CajaError):
        await abrir_caja("rosa", Decimal("10000"))

    # Outro operador pode abrir a sua em paralelo.
    otra = await abrir_caja("carlos", Decimal("10000"))
    assert otra.numero == 2
    assert (await get_caja_abierta("rosa")).numero == 1


@pytest.mark.asyncio
async def test_agrega_solo_los_pagos_del_turno(test_db, sample_client):
    rosa = await abrir_caja("rosa", Decimal("50000"))
    carlos = await abrir_caja("carlos", Decimal("0"))

    await _mk_pago(sample_client, "100000", PaymentMethod.EFECTIVO, "rosa", rosa)
    await _mk_pago(sample_client, "30000", PaymentMethod.TRANSFERENCIA, "rosa", rosa)
    await _mk_pago(sample_client, "40000", PaymentMethod.EFECTIVO, "rosa", rosa, anulada=True)
    await _mk_pago(sample_client, "70000", PaymentMethod.EFECTIVO, "carlos", carlos)
    # Pagamento fora do Modo Caja (sem sessao) nao entra em nenhum cierre.
    await _mk_pago(sample_client, "999000", PaymentMethod.EFECTIVO, "admin", None)

    r = await computar_sesion(rosa)
    assert r["cantidad_pagos"] == 2                      # o anulado nao conta
    assert r["ingresos_efectivo"] == Decimal("100000")
    assert r["ingresos_transferencia"] == Decimal("30000")
    assert r["ingresos_total"] == Decimal("130000")
    assert r["efectivo_esperado"] == Decimal("150000")   # 50.000 inicial + 100.000

    assert (await computar_sesion(carlos))["efectivo_esperado"] == Decimal("70000")


@pytest.mark.asyncio
async def test_estorno_sale_de_la_gaveta_de_quien_estorna(test_db, sample_client):
    rosa = await abrir_caja("rosa", Decimal("0"))
    en_efectivo = await _mk_pago(sample_client, "100000", PaymentMethod.EFECTIVO, "rosa", rosa)
    await _mk_pago(sample_client, "80000", PaymentMethod.EFECTIVO, "rosa", rosa)
    por_transferencia = await _mk_pago(
        sample_client, "60000", PaymentMethod.TRANSFERENCIA, "rosa", rosa)

    await _mk_estorno(en_efectivo, "rosa", rosa)
    await _mk_estorno(por_transferencia, "rosa", rosa)

    r = await computar_sesion(rosa)
    assert r["estornos_cantidad"] == 2
    assert r["estornos_total"] == Decimal("160000")
    assert r["estornos_efectivo"] == Decimal("100000")   # a transferencia nao sai da gaveta
    assert r["estornos_efectivo_previos"] == Decimal("0")  # ambos sao deste mesmo turno
    assert r["ingresos_efectivo"] == Decimal("80000")    # o estornado ja saiu dos ingressos
    # Sem contagem dupla: o de 100k nao entrou nos ingressos, logo nao se desconta.
    assert r["efectivo_esperado"] == Decimal("80000")


@pytest.mark.asyncio
async def test_estorno_de_turno_anterior_pesa_en_el_turno_actual(test_db, sample_client):
    ayer = await abrir_caja("rosa", Decimal("0"))
    pago = await _mk_pago(sample_client, "100000", PaymentMethod.EFECTIVO, "rosa", ayer)
    await cerrar_caja(ayer, Decimal("100000"), "rosa")

    hoy = await abrir_caja("rosa", Decimal("100000"))
    await _mk_estorno(pago, "rosa", hoy)

    r = await computar_sesion(hoy)
    assert r["cantidad_pagos"] == 0
    assert r["estornos_efectivo"] == Decimal("100000")
    assert r["estornos_efectivo_previos"] == Decimal("100000")
    assert r["efectivo_esperado"] == Decimal("0")        # devolveu os 100.000 do fondo

    # O turno fechado nao muda retroativamente.
    ayer_db = await CashSession.get(ayer.id)
    assert ayer_db.efectivo_esperado == Decimal("100000")
    assert ayer_db.diferencia == Decimal("0")


@pytest.mark.asyncio
async def test_cierre_graba_diferencia_y_bloquea_recierre(test_db, sample_client):
    rosa = await abrir_caja("rosa", Decimal("50000"))
    await _mk_pago(sample_client, "100000", PaymentMethod.EFECTIVO, "rosa", rosa)

    cerrada = await cerrar_caja(
        rosa, Decimal("145000"), "rosa", observaciones="falta plata")

    assert cerrada.status == CashSessionStatus.CERRADA
    assert cerrada.efectivo_esperado == Decimal("150000")
    assert cerrada.efectivo_fisico == Decimal("145000")
    assert cerrada.diferencia == Decimal("-5000")
    assert cerrada.cerrado_por == "rosa"
    assert cerrada.fecha_cierre is not None
    assert cerrada.cantidad_pagos == 1

    with pytest.raises(CajaError):
        await cerrar_caja(cerrada, Decimal("145000"), "rosa")

    # Fechada deixa de ser a caja aberta do operador.
    assert await get_caja_abierta("rosa") is None


@pytest.mark.asyncio
async def test_process_payment_carimba_pago_y_movimiento(
    test_settings, sample_client, multiple_invoices
):
    """O pagamento cobrado no turno entra no cierre — junto do movimento de caixa."""
    from app.services.payment_distribution import PaymentDistributionService

    inv1, _, _ = multiple_invoices
    rosa = await abrir_caja("rosa", Decimal("0"))

    res = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=Decimal("25000"),
        invoice_ids=[inv1.id],
        recibido_por="Rosa Benítez",      # nome de exibicao != username
        cash_session_id=rosa.id,
    )
    assert res.success

    pago = await Payment.find_one(Payment.cash_session_id == rosa.id)
    assert pago is not None and pago.recibido_por == "Rosa Benítez"

    mov = await CashTransaction.find_one(
        CashTransaction.cash_session_id == rosa.id,
        CashTransaction.categoria == TransactionCategory.PAGAMENTO_FATURA,
    )
    assert mov is not None and mov.valor == Decimal("25000")

    r = await computar_sesion(rosa)
    assert r["cantidad_pagos"] == 1
    assert r["efectivo_esperado"] == Decimal("25000")


@pytest.mark.asyncio
async def test_sesion_activa_id_para_carimbar(test_db):
    assert await sesion_activa_id(None) is None
    assert await sesion_activa_id("rosa") is None       # sem caja aberta

    rosa = await abrir_caja("rosa", Decimal("0"))
    assert await sesion_activa_id("rosa") == rosa.id

    await cerrar_caja(rosa, Decimal("0"), "rosa")
    assert await sesion_activa_id("rosa") is None
