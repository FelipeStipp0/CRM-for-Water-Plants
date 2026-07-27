"""
Estorno (anulação) de pagamento.

Reverte um pagamento preservando o registro (não apaga):
- restaura o saldo/estado das faturas que ele quitou;
- reverte os subsídios PENDENTES gerados por ele (bloqueia se já foram
  faturados/pagos ao padrino — não dá pra reverter limpo);
- lança um ESTORNO no caixa (SAÍDA compensatória) em vez de apagar a ENTRADA,
  mantendo a integridade do cierre de caja;
- marca o pagamento como anulado (quem/quando/motivo);
- registra na trilha de auditoria.

Se houver factura electrónica EMITIDA para este pagamento, a anulação **solicita
a cancelación fiscal** (SIFEN): o backend não fala com o portal — quem tem a
sessão é o coordenador —, então o pedido entra na fila e o resultado diz em que
pé está. O estorno interno não fica esperando por isso.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from beanie import PydanticObjectId

from app.models.payment import Payment
from app.models.invoice import Invoice, InvoiceStatus
from app.models.finance import CashTransaction, TransactionType, TransactionCategory
from app.models.sponsor import SponsorDebt, SponsorDebtStatus
from app.services.audit import registrar_audit


class PaymentNotFound(Exception):
    pass


class PaymentReversalError(Exception):
    """Regra de negócio impede o estorno (ex.: subsídio já faturado)."""


async def anular_payment(payment_id: PydanticObjectId, motivo: str, usuario: str) -> dict:
    payment = await Payment.get(payment_id)
    if not payment:
        raise PaymentNotFound("Pago no encontrado")
    if payment.anulada:
        raise PaymentReversalError("Este pago ya fue anulado.")
    if not (motivo or "").strip():
        raise PaymentReversalError("Indicá el motivo de la anulación.")

    # Subsídios: só dá para reverter os que ainda estão PENDENTES.
    sponsor_debts = await SponsorDebt.find(SponsorDebt.payment_id == payment.id).to_list()
    for sd in sponsor_debts:
        if sd.status != SponsorDebtStatus.PENDENTE:
            raise PaymentReversalError(
                "El subsidio de este pago ya fue facturado o pagado al padrino; "
                "no se puede anular automáticamente."
            )

    before = {
        "valor_total": str(payment.valor_total),
        "numero_recibo": payment.numero_recibo,
        "allocations": [
            {"invoice_id": str(a.invoice_id), "valor_aplicado": str(a.valor_aplicado)}
            for a in payment.allocations
        ],
    }

    # 1. Restaura as faturas quitadas por este pagamento.
    invoices_restored = 0
    for alloc in payment.allocations:
        inv = await Invoice.get(alloc.invoice_id)
        if not inv or inv.status == InvoiceStatus.ANULADA:
            continue
        new_saldo = inv.saldo_devedor + alloc.valor_aplicado
        new_status = (
            InvoiceStatus.PENDENTE if new_saldo >= inv.valor_total else InvoiceStatus.PARCIAL
        )
        await inv.update({"$set": {
            "saldo_devedor": new_saldo,
            "status": new_status.value,
            "updated_at": datetime.utcnow(),
        }})
        invoices_restored += 1

    # 2. Reverte os subsídios pendentes.
    for sd in sponsor_debts:
        await sd.delete()

    # 3. Estorno no caixa (SAÍDA compensatória — preserva a ENTRADA original).
    # Carimba a caja de QUEM ESTORNA (o dinheiro sai da gaveta aberta agora),
    # não a do pagamento original — que pode ser de outro turno já fechado.
    from app.services.caja_service import sesion_activa_id
    estorno = CashTransaction(
        tipo=TransactionType.SAIDA,
        categoria=TransactionCategory.ESTORNO_PAGAMENTO,
        valor=payment.valor_total,
        descripcion=f"Estorno recibo {payment.numero_recibo_fmt} — {motivo}",
        reference_id=payment.id,
        reference_type="payment_estorno",
        registrado_por=usuario,
        cash_session_id=await sesion_activa_id(usuario),
    )
    await estorno.insert()

    # 4. Marca o pagamento (não apaga).
    payment.anulada = True
    payment.anulada_por = usuario
    payment.anulada_at = datetime.utcnow()
    payment.motivo_anulacion = motivo
    await payment.save()

    # 5. Factura electrónica: pede a cancelación fiscal do DTE, se houver.
    sifen = await _solicitar_cancelacion_fiscal(payment, motivo, usuario)

    # 6. Auditoria.
    await registrar_audit(
        action="payment.anular",
        entity_type="payment",
        entity_id=str(payment.id),
        entity_label=f"Recibo {payment.numero_recibo_fmt}",
        usuario=usuario,
        motivo=motivo,
        before=before,
        after={"anulada": True, "estorno_cash_id": str(estorno.id),
               "sifen": sifen},
    )

    return {
        "payment_id": str(payment.id),
        "numero_recibo": payment.numero_recibo,
        "invoices_restored": invoices_restored,
        "sponsor_debts_reverted": len(sponsor_debts),
        "estorno_cash_id": str(estorno.id),
        "sifen": sifen,
    }


async def _solicitar_cancelacion_fiscal(payment: Payment, motivo: str, usuario: str) -> Optional[dict]:
    """
    Coloca o DTE deste pagamento na fila de cancelación. `None` quando não há
    factura electrónica envolvida (o caso comum: recibo do sistema).

    Falhar aqui NÃO desfaz o estorno — o dinheiro já voltou e as faturas já foram
    restauradas. O erro vai no retorno para a UI avisar que a cancelación fiscal
    precisa de atenção.
    """
    from app.models.sifen import SifenEmission, EmissionStatus
    from app.services.sifen.queue import solicitar_cancelacion

    emission = await SifenEmission.find_one(
        SifenEmission.payment_id == payment.id,
        SifenEmission.status == EmissionStatus.EMITIDA,
    )
    if not emission:
        return None

    try:
        emission = await solicitar_cancelacion(
            emission, f"Anulación de pago: {motivo}", usuario)
    except Exception as e:  # noqa: BLE001
        return {"emission_id": str(emission.id), "cdc": emission.cdc,
                "cancelacion": "error", "error": str(e)}

    return {
        "emission_id": str(emission.id),
        "cdc": emission.cdc,
        "numero_documento": emission.numero_documento,
        "cancelacion": "solicitada",
    }
