"""
Testes de sangría e reposición (dinheiro que entra/sai da gaveta sem ser cobro).

Sem isto o efectivo esperado mente assim que alguém leva dinheiro ao banco no
meio do turno, e o cierre acusa uma falta que não existe.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models.finance import (
    CashSessionStatus, TransactionCategory, TransactionType,
)
from app.models.payment import Payment, PaymentMethod
from app.services.caja_service import (
    CajaError, abrir_caja, cerrar_caja, computar_sesion, listar_movimientos,
    registrar_movimiento,
)


async def _pago(client, valor, sesion, metodo=PaymentMethod.EFECTIVO):
    p = Payment(
        client=client, valor_total=Decimal(valor), metodo=metodo,
        grupo_pagamento=f"g-{datetime.now().timestamp()}",
        cash_session_id=sesion.id, fecha_pago=datetime.now(),
    )
    await p.insert()
    return p


@pytest.mark.asyncio
async def test_sangria_baja_el_efectivo_esperado(test_db, sample_client):
    sesion = await abrir_caja("cajera", Decimal("50000"))
    await _pago(sample_client, "100000", sesion)

    r = await computar_sesion(sesion)
    assert r["efectivo_esperado"] == Decimal("150000")

    await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                               Decimal("120000"), "Depósito en el banco", "cajera")

    r = await computar_sesion(sesion)
    assert r["sangrias_cantidad"] == 1
    assert r["sangrias_total"] == Decimal("120000")
    assert r["efectivo_esperado"] == Decimal("30000")


@pytest.mark.asyncio
async def test_reposicion_sube_el_efectivo_esperado(test_db, sample_client):
    sesion = await abrir_caja("cajera", Decimal("10000"))
    await registrar_movimiento(sesion, TransactionCategory.REPOSICION_CAJA,
                               Decimal("25000"), "Cambio traído de tesorería", "cajera")
    r = await computar_sesion(sesion)
    assert r["reposiciones_cantidad"] == 1
    assert r["efectivo_esperado"] == Decimal("35000")


@pytest.mark.asyncio
async def test_no_se_saca_mas_de_lo_que_hay_en_la_gaveta(test_db, sample_client):
    sesion = await abrir_caja("cajera", Decimal("20000"))
    with pytest.raises(CajaError):
        await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                                   Decimal("30000"), "Banco", "cajera")


@pytest.mark.asyncio
async def test_movimiento_exige_monto_y_motivo(test_db):
    sesion = await abrir_caja("cajera", Decimal("20000"))
    with pytest.raises(CajaError):
        await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                                   Decimal("0"), "Banco", "cajera")
    with pytest.raises(CajaError):
        await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                                   Decimal("1000"), "  ", "cajera")
    # Categoria que não é da gaveta não passa por aqui.
    with pytest.raises(CajaError):
        await registrar_movimiento(sesion, TransactionCategory.PAGAMENTO_FATURA,
                                   Decimal("1000"), "Cobro", "cajera")


@pytest.mark.asyncio
async def test_caja_cerrada_no_acepta_movimientos(test_db):
    sesion = await abrir_caja("cajera", Decimal("20000"))
    await cerrar_caja(sesion, Decimal("20000"), "cajera")
    with pytest.raises(CajaError):
        await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                                   Decimal("1000"), "Banco", "cajera")


@pytest.mark.asyncio
async def test_cierre_guarda_sangrias_y_reposiciones(test_db, sample_client):
    sesion = await abrir_caja("cajera", Decimal("0"))
    await _pago(sample_client, "200000", sesion)
    await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                               Decimal("150000"), "Banco", "cajera")
    await registrar_movimiento(sesion, TransactionCategory.REPOSICION_CAJA,
                               Decimal("20000"), "Cambio", "cajera")

    cerrada = await cerrar_caja(sesion, Decimal("70000"), "cajera")
    assert cerrada.status == CashSessionStatus.CERRADA
    assert cerrada.sangrias_total == Decimal("150000")
    assert cerrada.reposiciones_total == Decimal("20000")
    assert cerrada.efectivo_esperado == Decimal("70000")
    assert cerrada.diferencia == Decimal("0")


@pytest.mark.asyncio
async def test_listar_movimientos_del_turno(test_db):
    sesion = await abrir_caja("cajera", Decimal("100000"))
    await registrar_movimiento(sesion, TransactionCategory.SANGRIA_CAJA,
                               Decimal("10000"), "Banco", "cajera")
    await registrar_movimiento(sesion, TransactionCategory.REPOSICION_CAJA,
                               Decimal("5000"), "Cambio", "cajera")
    movs = await listar_movimientos(sesion)
    assert len(movs) == 2
    categorias = {m["categoria"] for m in movs}
    assert categorias == {"SANGRIA_CAJA", "REPOSICION_CAJA"}
    tipos = {m["tipo"] for m in movs}
    assert tipos == {TransactionType.SAIDA.value, TransactionType.ENTRADA.value}
