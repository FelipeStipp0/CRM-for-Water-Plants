"""
Sessao de caja (turno): apertura -> cobranca -> cierre.

O operador ABRE a caja informando o monto inicial (fondo de cambio). A partir
dai todo Payment cobrado por ele fica carimbado com o id da sessao, e no CIERRE
o sistema agrega exatamente esses pagamentos — nao a janela do dia. Isso e o que
permite dois cajeros no mesmo dia, ou dois turnos do mesmo cajero, sem misturar.

Numeracao: `Counter("cash_session")` da o `numero` sequencial na ordem de
apertura ("Caja 07"). Global e monotonico — nunca reinicia.

Efectivo esperado na gaveta = monto_inicial + ingresos en efectivo − estornos
en efectivo. Pagamentos ANULADOS nao entram nos ingressos (o estorno ja os
tirou); o estorno pesa na sessao em que foi FEITO, que e de onde o dinheiro saiu.
Estorno de pagamento por transferencia/cheque nao mexe na gaveta.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from beanie import PydanticObjectId

from app.models.invoice import Counter
from app.models.payment import Payment, PaymentMethod
from app.models.finance import (
    CashTransaction,
    TransactionCategory,
    CashSession,
    CashSessionStatus,
)


class CajaError(Exception):
    """Erro de regra da sessao de caja (vira 4xx no router)."""


async def get_caja_abierta(operador: str) -> Optional[CashSession]:
    """Sessao ABIERTA do operador, se houver (no maximo uma)."""
    return await CashSession.find_one(
        CashSession.operador == operador,
        CashSession.status == CashSessionStatus.ABIERTA,
    )


async def abrir_caja(
    operador: str, monto_inicial: Decimal, abierto_por: Optional[str] = None,
) -> CashSession:
    """Abre um turno para o operador. Falha se ele ja tiver uma caja aberta."""
    ya = await get_caja_abierta(operador)
    if ya:
        raise CajaError(f"El operador ya tiene la Caja {ya.numero_fmt} abierta")

    numero = await Counter.get_next("cash_session")
    sesion = CashSession(
        numero=numero,
        status=CashSessionStatus.ABIERTA,
        operador=operador,
        monto_inicial=Decimal(str(monto_inicial or 0)),
        abierto_por=abierto_por or operador,
    )
    await sesion.insert()
    return sesion


async def computar_sesion(sesion: CashSession) -> dict:
    """Resumo do turno (sem gravar): ingressos por metodo, estornos e esperado."""
    pagos = await Payment.find(
        Payment.cash_session_id == sesion.id,
        Payment.anulada != True,  # noqa: E712  (Mongo $ne True: pega False e ausente)
    ).to_list()

    por_metodo = {
        PaymentMethod.EFECTIVO.value: Decimal("0"),
        PaymentMethod.TRANSFERENCIA.value: Decimal("0"),
        PaymentMethod.CHEQUE.value: Decimal("0"),
    }
    for p in pagos:
        m = p.metodo.value if hasattr(p.metodo, "value") else str(p.metodo)
        por_metodo[m] = por_metodo.get(m, Decimal("0")) + p.valor_total

    # Estornos LANCADOS neste turno (podem ser de pagamentos de turnos anteriores).
    estornos = await CashTransaction.find(
        CashTransaction.cash_session_id == sesion.id,
        CashTransaction.categoria == TransactionCategory.ESTORNO_PAGAMENTO,
    ).to_list()

    estornos_total = Decimal("0")
    estornos_efectivo = Decimal("0")
    estornos_efectivo_previos = Decimal("0")
    for e in estornos:
        estornos_total += e.valor
        if not e.reference_id:
            continue
        orig = await Payment.get(e.reference_id)
        # So devolve dinheiro da gaveta se o pagamento anulado era em efectivo.
        if not orig or orig.metodo != PaymentMethod.EFECTIVO:
            continue
        estornos_efectivo += e.valor
        # Anular um pagamento DESTE turno ja o tira dos ingressos: descontar de
        # novo contaria duas vezes. So pesa na gaveta o estorno de dinheiro que
        # entrou antes deste turno (ou fora do Modo Caja).
        if orig.cash_session_id != sesion.id:
            estornos_efectivo_previos += e.valor

    ingresos_efectivo = por_metodo[PaymentMethod.EFECTIVO.value]
    ingresos_total = sum(por_metodo.values(), Decimal("0"))
    esperado = sesion.monto_inicial + ingresos_efectivo - estornos_efectivo_previos

    return {
        "id": str(sesion.id),
        "numero": sesion.numero,
        "numero_fmt": sesion.numero_fmt,
        "status": sesion.status.value,
        "operador": sesion.operador,
        "abierto_por": sesion.abierto_por,
        "fecha_apertura": sesion.fecha_apertura,
        "monto_inicial": sesion.monto_inicial,
        "cantidad_pagos": len(pagos),
        "ingresos_efectivo": ingresos_efectivo,
        "ingresos_transferencia": por_metodo[PaymentMethod.TRANSFERENCIA.value],
        "ingresos_cheque": por_metodo[PaymentMethod.CHEQUE.value],
        "ingresos_total": ingresos_total,
        "estornos_cantidad": len(estornos),
        "estornos_total": estornos_total,
        "estornos_efectivo": estornos_efectivo,
        "estornos_efectivo_previos": estornos_efectivo_previos,
        "efectivo_esperado": esperado,
    }


async def cerrar_caja(
    sesion: CashSession, efectivo_fisico: Decimal, cerrado_por: str,
    observaciones: Optional[str] = None,
) -> CashSession:
    """Fecha o turno gravando o contado, o esperado e a diferencia."""
    if sesion.status != CashSessionStatus.ABIERTA:
        raise CajaError(f"La Caja {sesion.numero_fmt} ya fue cerrada")

    r = await computar_sesion(sesion)
    esperado = Decimal(str(r["efectivo_esperado"]))
    fisico = Decimal(str(efectivo_fisico or 0))

    sesion.status = CashSessionStatus.CERRADA
    sesion.fecha_cierre = datetime.utcnow()
    sesion.cerrado_por = cerrado_por
    sesion.cantidad_pagos = r["cantidad_pagos"]
    sesion.ingresos_efectivo = r["ingresos_efectivo"]
    sesion.ingresos_transferencia = r["ingresos_transferencia"]
    sesion.ingresos_cheque = r["ingresos_cheque"]
    sesion.ingresos_total = r["ingresos_total"]
    sesion.estornos_cantidad = r["estornos_cantidad"]
    sesion.estornos_total = r["estornos_total"]
    sesion.estornos_efectivo = r["estornos_efectivo"]
    sesion.estornos_efectivo_previos = r["estornos_efectivo_previos"]
    sesion.efectivo_esperado = esperado
    sesion.efectivo_fisico = fisico
    sesion.diferencia = fisico - esperado
    sesion.observaciones = observaciones
    await sesion.save()
    return sesion


async def sesion_activa_id(operador: Optional[str]) -> Optional[PydanticObjectId]:
    """
    Id da caja aberta do operador — para carimbar pagamentos/estornos.

    Devolve None sem operador ou sem caja aberta (lancamento fora do Modo Caja,
    que simplesmente nao entra em nenhum cierre).
    """
    if not operador:
        return None
    sesion = await get_caja_abierta(operador)
    return sesion.id if sesion else None
