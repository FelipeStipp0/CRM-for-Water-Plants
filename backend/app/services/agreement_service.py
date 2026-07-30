"""
Acordo de pagamento (parcelamento) — regras de negócio.

Fluxo do balcão:

1. O cajero escolhe as faturas em aberto que entram no acordo e diz em quantas
   parcelas. Pode receber uma **entrada** no ato (que é um cobro normal, com
   recibo) — ela reduz o total antes de dividir.
2. As faturas escolhidas viram **ANULADA com saldo zerado** e ficam guardadas no
   acordo. O cliente sai da dívida e do fluxo de corte na hora.
3. A dívida passa a viver em **parcelas agendadas**. A geração mensal soma a
   parcela do mês na fatura de consumo daquele mês (`Invoice.cuota_valor`), com
   IVA e afetação próprios — escolhidos pelo cajero ao fechar o acordo.
4. Parcela vencida entra no corte como qualquer dívida: quem vence é a própria
   fatura do mês, que já cai no fluxo existente.
5. Ao quitar 100%, o acordo vira QUITADO e devolve as faturas antigas para a caja
   imprimir junto do recibo da última parcela.

Regras fixas: total do acordo = soma exata dos saldos (sem juros, multa ou
ajuste); número de parcelas livre; **um acordo ATIVO por cliente** — dívida nova
durante o acordo refaz o acordo, juntando saldo remanescente + dívida nova.

⚠️ `get_outstanding_invoices` busca por `saldo_devedor > 0`, **não** por status:
anular sem zerar o saldo devedor deixaria a fatura anulada ainda recebendo
pagamento. Por isso `_anular_facturas` zera o saldo *e* muda o status.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Sequence

from beanie import PydanticObjectId

from app.models.agreement import (
    AgreementCuota,
    AgreementInvoiceSnapshot,
    AgreementStatus,
    CuotaStatus,
    PaymentAgreement,
)
from app.models.client import Client
from app.models.invoice import Counter, Invoice, InvoiceItem, InvoiceStatus, InvoiceType
from app.models.payment import PaymentMethod
from app.models.settings import SystemSettings
from app.services.audit import registrar_audit


class AgreementError(Exception):
    """Regra de negócio impede a operação (vira 400 no router)."""


# --------------------------------------------------------------------- helpers
def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _add_month(mes: int, ano: int, n: int) -> tuple[int, int]:
    idx = ano * 12 + (mes - 1) + n
    return idx % 12 + 1, idx // 12


def dividir_parcelas(total: Decimal, n: int) -> List[Decimal]:
    """
    Divide o total em `n` parcelas inteiras (Guarani não tem centavos).

    As primeiras ficam arredondadas para baixo e a **última absorve a sobra**,
    para que a soma bata exatamente com o total — o acordo não pode virar um
    desconto involuntário nem cobrar 1 Gs. a mais.
    """
    if n < 1:
        raise AgreementError("El número de cuotas debe ser al menos 1.")
    total = _dec(total).quantize(Decimal("1"))
    base = (total // n).quantize(Decimal("1"))
    parcelas = [base] * (n - 1)
    parcelas.append(total - base * (n - 1))
    return parcelas


async def acuerdo_activo(client_id: PydanticObjectId) -> Optional[PaymentAgreement]:
    """Acordo ATIVO do cliente (no máximo um)."""
    return await PaymentAgreement.find_one(
        {"client.$id": client_id},
        PaymentAgreement.status == AgreementStatus.ACTIVO,
    )


def acuerdo_to_dict(ac: PaymentAgreement) -> dict:
    return {
        "id": str(ac.id),
        "numero": ac.numero,
        "numero_fmt": ac.numero_fmt,
        "status": ac.status.value,
        "total_deuda": ac.total_deuda,
        "entrada": ac.entrada,
        "total_parcelado": ac.total_parcelado,
        "n_parcelas": ac.n_parcelas,
        "cuota_iva_tasa": ac.cuota_iva_tasa,
        "cuota_iva_afectacion": ac.cuota_iva_afectacion,
        "saldo_pendiente": ac.saldo_pendiente,
        "parcelas": [
            {
                "numero": c.numero, "mes": c.mes, "ano": c.ano, "valor": c.valor,
                "status": c.status.value,
                "invoice_id": str(c.invoice_id) if c.invoice_id else None,
            }
            for c in ac.parcelas
        ],
        "facturas_anuladas": [
            {
                "invoice_id": str(f.invoice_id), "numero_factura": f.numero_factura,
                "tipo": f.tipo, "mes_referencia": f.mes_referencia,
                "ano_referencia": f.ano_referencia, "valor_total": f.valor_total,
                "saldo_incorporado": f.saldo_incorporado,
            }
            for f in ac.facturas_anuladas
        ],
        "creado_por": ac.creado_por,
        "created_at": ac.created_at,
        "closed_at": ac.closed_at,
        "replaces_id": str(ac.replaces_id) if ac.replaces_id else None,
        "replaced_by_id": str(ac.replaced_by_id) if ac.replaced_by_id else None,
    }


async def acuerdo_activo_dict(client_id: PydanticObjectId) -> Optional[dict]:
    ac = await acuerdo_activo(client_id)
    return acuerdo_to_dict(ac) if ac else None


# ------------------------------------------------------------------- criação
async def _facturas_en_abierto(client_id: PydanticObjectId) -> List[Invoice]:
    from app.services.payment_distribution import PaymentDistributionService

    return await PaymentDistributionService.get_outstanding_invoices(client_id)


async def _anular_facturas(
    facturas: Sequence[Invoice], acuerdo_id: PydanticObjectId,
) -> List[AgreementInvoiceSnapshot]:
    """Zera o saldo e marca ANULADA, guardando o retrato de cada fatura."""
    snaps: List[AgreementInvoiceSnapshot] = []
    for inv in facturas:
        snaps.append(AgreementInvoiceSnapshot(
            invoice_id=inv.id,
            numero_factura=inv.numero_factura,
            tipo=inv.tipo.value if hasattr(inv.tipo, "value") else str(inv.tipo),
            mes_referencia=inv.mes_referencia,
            ano_referencia=inv.ano_referencia,
            valor_total=inv.valor_total,
            saldo_incorporado=inv.saldo_devedor,
        ))
        await inv.update({"$set": {
            "saldo_devedor": Decimal("0"),
            "status": InvoiceStatus.ANULADA.value,
            "anulada_por_acuerdo_id": acuerdo_id,
            "updated_at": datetime.utcnow(),
        }})
    return snaps


async def _crear_factura_cuota(
    client: Client, acuerdo: PaymentAgreement, cuota: AgreementCuota,
    settings: SystemSettings,
) -> Invoice:
    """
    Fatura AVULSA da primeira parcela quando o acordo começa no mês corrente.

    O mês corrente já foi faturado (e a fatura de consumo dele acabou de ser
    anulada pelo acordo), então não há onde somar a cuota: ela vira uma fatura
    própria, com o IVA da cuota — não o das configurações.
    """
    from app.services.invoice_generation import InvoiceGenerationService

    numero_factura = await Counter.get_next("invoice_number")
    invoice = Invoice(
        client=client,
        tipo=InvoiceType.AVULSA,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=cuota.mes,
        ano_referencia=cuota.ano,
        fecha_vencimiento=InvoiceGenerationService.calculate_due_date(
            mes_referencia=cuota.mes, ano_referencia=cuota.ano,
            dias_vencimiento=settings.dias_vencimiento,
            dia_geracao_faturas=settings.dia_geracao_faturas,
        ),
        items=[InvoiceItem(
            descripcion=(f"Cuota {cuota.numero}/{acuerdo.n_parcelas} — "
                         f"Acuerdo Nº {acuerdo.numero_fmt}"),
            cantidad=1,
            precio_unitario=cuota.valor,
            iva_tasa=acuerdo.cuota_iva_tasa,
            iva_afectacion=acuerdo.cuota_iva_afectacion,
        )],
        valor_total=cuota.valor,
        saldo_devedor=cuota.valor,
        numero_factura=numero_factura,
        cuota_valor=cuota.valor,
        cuota_iva_tasa=acuerdo.cuota_iva_tasa,
        cuota_iva_afectacion=acuerdo.cuota_iva_afectacion,
        cuota_numero=cuota.numero,
        agreement_id=acuerdo.id,
    )
    await invoice.insert()
    return invoice


async def crear_acuerdo(
    client_id: PydanticObjectId,
    invoice_ids: Optional[List[PydanticObjectId]],
    n_parcelas: int,
    usuario: str,
    entrada: Decimal = Decimal("0"),
    metodo: PaymentMethod = PaymentMethod.EFECTIVO,
    primera_en_mes_corriente: bool = False,
    cuota_iva_tasa: int = 10,
    cuota_iva_afectacion: int = 1,
    aplicar_subsidio: Optional[bool] = None,
    recibido_por: Optional[str] = None,
    observacion: Optional[str] = None,
) -> dict:
    """
    Fecha um acordo. Devolve {"acuerdo": dict, "entrada_payment": dict|None}.

    Se o cliente já tem um acordo ATIVO, este refaz o acordo: consolida **tudo**
    o que está em aberto (não só o que foi marcado) mais as parcelas ainda não
    faturadas do acordo antigo, que fica REFEITO.
    """
    client = await Client.get(client_id)
    if not client:
        raise AgreementError("Cliente no encontrado.")
    if n_parcelas < 1:
        raise AgreementError("El número de cuotas debe ser al menos 1.")

    settings = await SystemSettings.get_instance()
    anterior = await acuerdo_activo(client_id)

    abiertas = await _facturas_en_abierto(client_id)
    if anterior:
        # Refazer: junta saldo remanescente + dívida nova. Escolher um subconjunto
        # deixaria duas dívidas do mesmo cliente vivas em paralelo.
        facturas = abiertas
    elif invoice_ids:
        wanted = set(invoice_ids)
        facturas = [inv for inv in abiertas if inv.id in wanted]
        if len(facturas) != len(wanted):
            raise AgreementError(
                "Alguna de las facturas seleccionadas ya no está en abierto. "
                "Cerrá y volvé a abrir el acuerdo.")
    else:
        facturas = abiertas

    if not facturas and not anterior:
        raise AgreementError("El cliente no tiene deuda para parcelar.")

    total_facturas = sum((inv.saldo_devedor for inv in facturas), Decimal("0"))

    # Parcelas do acordo antigo que nunca chegaram a ser faturadas: o dinheiro
    # ainda é devido, mas não existe fatura para ele.
    pendientes_antiguas = Decimal("0")
    if anterior:
        pendientes_antiguas = sum(
            (c.valor for c in anterior.parcelas if c.status == CuotaStatus.PENDIENTE),
            Decimal("0"),
        )

    total_deuda = (total_facturas + pendientes_antiguas).quantize(Decimal("1"))
    if total_deuda <= 0:
        raise AgreementError("El cliente no tiene deuda para parcelar.")

    entrada = _dec(entrada).quantize(Decimal("1"))
    if entrada < 0:
        raise AgreementError("La entrada no puede ser negativa.")
    if entrada >= total_deuda:
        raise AgreementError(
            "La entrada cubre toda la deuda: cobrala como pago normal, sin acuerdo.")

    # A entrada é um cobro de verdade (com recibo), aplicado nas faturas do acordo
    # da mais antiga para a mais nova — antes de anular qualquer coisa.
    entrada_payment = None
    if entrada > 0:
        if not facturas:
            raise AgreementError(
                "No hay facturas donde aplicar la entrada. Cerrá el acuerdo sin entrada.")
        from app.services.payment_distribution import PaymentDistributionService

        subsidio = client.has_sponsor if aplicar_subsidio is None else aplicar_subsidio
        result = await PaymentDistributionService.process_payment(
            client_id=client_id,
            valor_total=entrada,
            metodo=metodo,
            aplicar_subsidio=bool(subsidio),
            recibido_por=recibido_por or usuario,
            observacion=f"Entrada del acuerdo de pago — {usuario}",
            invoice_ids=[inv.id for inv in facturas],
        )
        if not result.success:
            raise AgreementError(result.error or "No se pudo registrar la entrada.")
        entrada_payment = result
        # Relê as faturas: os saldos mudaram e é isso que vai ser anulado.
        vivas = {inv.id for inv in facturas}
        facturas = [inv for inv in await _facturas_en_abierto(client_id) if inv.id in vivas]

    total_parcelado = (
        sum((inv.saldo_devedor for inv in facturas), Decimal("0")) + pendientes_antiguas
    ).quantize(Decimal("1"))
    if total_parcelado <= 0:
        raise AgreementError("Después de la entrada no queda saldo para parcelar.")

    numero = await Counter.get_next("agreement")
    acuerdo = PaymentAgreement(
        numero=numero,
        client=client,
        status=AgreementStatus.ACTIVO,
        total_deuda=total_deuda,
        entrada=entrada,
        total_parcelado=total_parcelado,
        n_parcelas=n_parcelas,
        cuota_iva_tasa=int(cuota_iva_tasa),
        cuota_iva_afectacion=int(cuota_iva_afectacion),
        entrada_payment_id=entrada_payment.payment_id if entrada_payment else None,
        replaces_id=anterior.id if anterior else None,
        creado_por=usuario,
        observacion=observacion,
    )
    await acuerdo.insert()

    # Anula as faturas antigas (saldo zerado + status ANULADA + vínculo).
    snaps = await _anular_facturas(facturas, acuerdo.id)

    # Refazer: as parcelas antigas ainda não pagas morrem aqui, e o retrato das
    # faturas que o acordo anterior tinha anulado é carregado para o novo — é o
    # que se imprime quando a dívida inteira finalmente acabar.
    if anterior:
        anuladas_ids = {s.invoice_id for s in snaps}
        for c in anterior.parcelas:
            if c.status in (CuotaStatus.PENDIENTE, CuotaStatus.FACTURADA) and (
                    c.status == CuotaStatus.PENDIENTE or c.invoice_id in anuladas_ids):
                c.status = CuotaStatus.CANCELADA
        anterior.status = AgreementStatus.REFEITO
        anterior.replaced_by_id = acuerdo.id
        anterior.closed_at = datetime.utcnow()
        anterior.updated_at = datetime.utcnow()
        await anterior.save()
        ya = {s.invoice_id for s in snaps}
        for s in anterior.facturas_anuladas:
            if s.invoice_id not in ya:
                snaps.append(s)

    acuerdo.facturas_anuladas = snaps

    # Cronograma. A primeira parcela pode começar neste mês (como AVULSA, porque
    # o mês corrente já foi faturado) ou no mês seguinte — escolha do cajero.
    hoy = date.today()
    valores = dividir_parcelas(total_parcelado, n_parcelas)
    mes, ano = (hoy.month, hoy.year) if primera_en_mes_corriente else _add_month(
        hoy.month, hoy.year, 1)
    parcelas: List[AgreementCuota] = []
    for i, valor in enumerate(valores):
        parcelas.append(AgreementCuota(numero=i + 1, mes=mes, ano=ano, valor=valor))
        mes, ano = _add_month(mes, ano, 1)
    acuerdo.parcelas = parcelas
    await acuerdo.save()

    if primera_en_mes_corriente:
        inv = await _crear_factura_cuota(client, acuerdo, parcelas[0], settings)
        parcelas[0].status = CuotaStatus.FACTURADA
        parcelas[0].invoice_id = inv.id
        parcelas[0].facturada_at = datetime.utcnow()
        acuerdo.parcelas = parcelas
        await acuerdo.save()

    await registrar_audit(
        action="agreement.crear",
        entity_type="agreement",
        entity_id=str(acuerdo.id),
        entity_label=f"Acuerdo {acuerdo.numero_fmt} — {client.nombre_completo}",
        usuario=usuario,
        motivo=observacion,
        before={"acuerdo_anterior": str(anterior.id) if anterior else None,
                "facturas": [str(s.invoice_id) for s in snaps]},
        after={"total_deuda": str(total_deuda), "entrada": str(entrada),
               "total_parcelado": str(total_parcelado), "n_parcelas": n_parcelas},
    )

    return {
        "acuerdo": acuerdo_to_dict(acuerdo),
        "entrada_payment_id": (str(entrada_payment.payment_id)
                               if entrada_payment else None),
        # O grupo é a chave da reimpressão do recibo (`/payments/by-group`): a caja
        # imprime o recibo da entrada junto do comprobante do acordo.
        "entrada_grupo": entrada_payment.grupo_pagamento if entrada_payment else None,
    }


# ----------------------------------------------------- cuota na geração mensal
async def cuota_para_periodo(
    client_id: PydanticObjectId, mes: int, ano: int,
) -> Optional[tuple[PaymentAgreement, AgreementCuota]]:
    """Parcela agendada (ainda não faturada) do cliente para aquele mês, se houver."""
    ac = await acuerdo_activo(client_id)
    if not ac:
        return None
    for c in ac.parcelas:
        if c.mes == mes and c.ano == ano and c.status == CuotaStatus.PENDIENTE:
            return ac, c
    return None


async def cuotas_del_periodo(
    mes: int, ano: int,
) -> dict[PydanticObjectId, tuple[PaymentAgreement, AgreementCuota]]:
    """
    Todas as parcelas agendadas para um mês, por cliente — para a geração em lote.

    Uma consulta em vez de uma por cliente: a geração mensal roda para a junta
    inteira e a maioria dos clientes não tem acordo nenhum.
    """
    acuerdos = await PaymentAgreement.find(
        PaymentAgreement.status == AgreementStatus.ACTIVO,
    ).to_list()
    mapa: dict[PydanticObjectId, tuple[PaymentAgreement, AgreementCuota]] = {}
    for ac in acuerdos:
        cid = ac.client.ref.id if hasattr(ac.client, "ref") else ac.client.id
        for c in ac.parcelas:
            if c.mes == mes and c.ano == ano and c.status == CuotaStatus.PENDIENTE:
                mapa[cid] = (ac, c)
                break
    return mapa


async def marcar_cuota_facturada(
    acuerdo: PaymentAgreement, cuota: AgreementCuota, invoice_id: PydanticObjectId,
) -> None:
    for c in acuerdo.parcelas:
        if c.numero == cuota.numero:
            c.status = CuotaStatus.FACTURADA
            c.invoice_id = invoice_id
            c.facturada_at = datetime.utcnow()
    acuerdo.updated_at = datetime.utcnow()
    await acuerdo.save()


# --------------------------------------------------------------- quitação
async def on_invoices_paid(
    client_id: PydanticObjectId, invoice_ids: Sequence[PydanticObjectId],
) -> Optional[dict]:
    """
    Marca as parcelas cujas faturas foram quitadas e fecha o acordo se acabou.

    Devolve o acordo (com as faturas antigas) **apenas quando ele acabou de ser
    quitado** — é o gatilho para a caja imprimir as faturas antigas junto do
    recibo da última parcela.
    """
    ac = await acuerdo_activo(client_id)
    if not ac:
        return None

    pagadas = set(invoice_ids)
    mudou = False
    for c in ac.parcelas:
        if c.status != CuotaStatus.FACTURADA or c.invoice_id not in pagadas:
            continue
        inv = await Invoice.get(c.invoice_id)
        if inv and inv.saldo_devedor <= 0:
            c.status = CuotaStatus.PAGADA
            c.pagada_at = datetime.utcnow()
            mudou = True

    if not mudou:
        return None

    quitado = all(c.status in (CuotaStatus.PAGADA, CuotaStatus.CANCELADA)
                  for c in ac.parcelas)
    if quitado:
        ac.status = AgreementStatus.QUITADO
        ac.closed_at = datetime.utcnow()
    ac.updated_at = datetime.utcnow()
    await ac.save()

    return acuerdo_to_dict(ac) if quitado else None
