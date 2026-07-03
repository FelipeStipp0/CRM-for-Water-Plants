"""
Servico de distribuicao de pagamentos.

Implementa a logica de distribuicao recursiva: um pagamento e aplicado
nas faturas pendentes da mais antiga para a mais recente.

SUBSIDIO/SPONSOR:
Quando um cliente com sponsor paga sua fatura:
1. Cliente paga (Valor Total - Subsidio%)
2. O valor do subsidio vira uma divida do Sponsor (SponsorDebt)
3. Mensalmente, gera-se uma fatura agregada para o Sponsor
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from beanie import PydanticObjectId

from app.models.client import Client
from app.models.invoice import Invoice, InvoiceStatus, Counter
from app.models.payment import Payment, PaymentAllocation, PaymentMethod
from app.models.finance import CashTransaction, TransactionType, TransactionCategory
from app.models.sponsor import SponsorDebt, SponsorDebtStatus
from app.models.settings import SystemSettings


@dataclass
class SubsidyInfo:
    """Informacoes do subsidio aplicado em um pagamento."""
    sponsor_id: PydanticObjectId
    porcentagem: int
    valor_subsidio: Decimal
    valor_cliente_paga: Decimal


@dataclass
class AllocationResult:
    """Resultado da alocacao em uma fatura."""
    invoice_id: PydanticObjectId
    mes_referencia: int
    ano_referencia: int
    valor_original: Decimal
    saldo_anterior: Decimal
    valor_aplicado: Decimal
    saldo_restante: Decimal
    status_final: InvoiceStatus
    # Subsidio transferido para sponsor (se aplicavel)
    subsidio_transferido: Optional[Decimal] = None
    sponsor_debt_id: Optional[PydanticObjectId] = None


@dataclass
class DistributionResult:
    """Resultado completo da distribuicao de pagamento."""
    success: bool
    payment_id: Optional[PydanticObjectId]
    grupo_pagamento: str
    allocations: List[AllocationResult]
    total_applied: Decimal
    overpayment: Decimal
    # Subsidio
    total_subsidio: Decimal = Decimal("0")
    sponsor_debts_created: List[PydanticObjectId] = None
    error: Optional[str] = None
    # Reativacao automatica (quando um cliente CORTADO quita a divida)
    reactivation_notice_id: Optional[PydanticObjectId] = None
    reactivation_qr_token: Optional[str] = None
    reactivation_comprobante: Optional[str] = None

    def __post_init__(self):
        if self.sponsor_debts_created is None:
            self.sponsor_debts_created = []


class PaymentDistributionService:
    """
    Servico para distribuicao inteligente de pagamentos.

    A logica principal:
    1. Busca todas as faturas pendentes do cliente
    2. Ordena da mais antiga para a mais recente
    3. Aplica o valor do pagamento em cada fatura ate esgotar
    4. Registra cada alocacao individual
    5. Atualiza o saldo_devedor de cada fatura afetada
    """

    @staticmethod
    async def get_outstanding_invoices(client_id: PydanticObjectId) -> List[Invoice]:
        """
        Busca faturas com saldo devedor ordenadas por data.

        Returns:
            Lista de faturas ordenadas da mais antiga para a mais recente
        """
        return await Invoice.find(
            {
                "client.$id": client_id,
                "saldo_devedor": {"$gt": 0},
                "status": {"$ne": InvoiceStatus.ANULADA.value},
            }
        ).sort([
            ("ano_referencia", 1),
            ("mes_referencia", 1),
            ("fecha_emision", 1)
        ]).to_list()

    @staticmethod
    async def calculate_total_debt(client_id: PydanticObjectId) -> Decimal:
        """Calcula o total de divida de um cliente."""
        invoices = await PaymentDistributionService.get_outstanding_invoices(client_id)
        return sum(inv.saldo_devedor for inv in invoices)

    @staticmethod
    async def get_subsidy_info(client: Client) -> Optional[SubsidyInfo]:
        """
        Retorna informacoes de subsidio do cliente, se aplicavel.

        Args:
            client: Cliente a verificar

        Returns:
            SubsidyInfo se cliente tem sponsor, None caso contrario
        """
        if not client.sponsor_id:
            return None

        # Busca porcentagem de subsidio
        settings = await SystemSettings.get_instance()
        porcentagem = client.subsidio_porcentagem or settings.subsidio_porcentagem_padrao

        return SubsidyInfo(
            sponsor_id=client.sponsor_id,
            porcentagem=porcentagem,
            valor_subsidio=Decimal("0"),  # Sera calculado no momento do pagamento
            valor_cliente_paga=Decimal("0"),
        )

    @staticmethod
    def distribute_amount(
        amount: Decimal,
        invoices: List[Invoice]
    ) -> tuple[List[AllocationResult], Decimal]:
        """
        Distribui um valor entre as faturas (funcao pura, sem I/O).

        Args:
            amount: Valor a distribuir
            invoices: Faturas ordenadas da mais antiga para mais recente

        Returns:
            Tuple com lista de alocacoes e valor excedente (overpayment)
        """
        allocations: List[AllocationResult] = []
        remaining = amount

        for invoice in invoices:
            if remaining <= 0:
                break

            saldo_anterior = invoice.saldo_devedor
            valor_aplicar = min(remaining, saldo_anterior)

            if valor_aplicar > 0:
                saldo_restante = saldo_anterior - valor_aplicar
                status_final = (
                    InvoiceStatus.PAGADA if saldo_restante <= 0
                    else InvoiceStatus.PARCIAL
                )

                allocations.append(AllocationResult(
                    invoice_id=invoice.id,
                    mes_referencia=invoice.mes_referencia,
                    ano_referencia=invoice.ano_referencia,
                    valor_original=invoice.valor_total,
                    saldo_anterior=saldo_anterior,
                    valor_aplicado=valor_aplicar,
                    saldo_restante=saldo_restante,
                    status_final=status_final,
                ))

                remaining -= valor_aplicar

        return allocations, remaining

    @classmethod
    async def process_payment(
        cls,
        client_id: PydanticObjectId,
        valor_total: Decimal,
        metodo: PaymentMethod = PaymentMethod.EFECTIVO,
        aplicar_subsidio: bool = True,
        recibido_por: Optional[str] = None,
        observacion: Optional[str] = None,
    ) -> DistributionResult:
        """
        Processa um pagamento com distribuicao automatica e subsidio.

        Este e o metodo principal que:
        1. Busca faturas pendentes
        2. Calcula a distribuicao
        3. Persiste o pagamento e alocacoes
        4. Atualiza as faturas
        5. Se cliente tem sponsor: cria SponsorDebt para cada fatura quitada

        LOGICA DE SUBSIDIO:
        - Cliente com sponsor_id paga apenas (100% - subsidio_porcentagem)
        - A diferenca (subsidio) vira divida do Sponsor (SponsorDebt)
        - SponsorDebt e criado para cada fatura totalmente quitada

        Args:
            client_id: ID do cliente
            valor_total: Valor do pagamento (ja com desconto do subsidio)
            metodo: Metodo de pagamento
            recibido_por: Nome de quem recebeu
            observacion: Observacao opcional

        Returns:
            DistributionResult com detalhes da operacao
        """
        grupo = str(uuid4())

        # Valida cliente
        client = await Client.get(client_id)
        if not client:
            return DistributionResult(
                success=False,
                payment_id=None,
                grupo_pagamento=grupo,
                allocations=[],
                total_applied=Decimal("0"),
                overpayment=Decimal("0"),
                error="Cliente nao encontrado"
            )

        # Verifica se cliente tem subsidio (apenas se flag ativa)
        subsidy_info = await cls.get_subsidy_info(client) if aplicar_subsidio else None

        # Busca faturas pendentes
        invoices = await cls.get_outstanding_invoices(client_id)

        if not invoices and valor_total > 0:
            return DistributionResult(
                success=False,
                payment_id=None,
                grupo_pagamento=grupo,
                allocations=[],
                total_applied=Decimal("0"),
                overpayment=valor_total,
                error="Cliente nao possui faturas pendentes"
            )

        # Calcula distribuicao
        allocations, overpayment = cls.distribute_amount(valor_total, invoices)

        if not allocations:
            return DistributionResult(
                success=False,
                payment_id=None,
                grupo_pagamento=grupo,
                allocations=[],
                total_applied=Decimal("0"),
                overpayment=valor_total,
                error="Nenhum valor foi alocado"
            )

        # Cria registro de pagamento
        payment_allocations = [
            PaymentAllocation(
                invoice_id=alloc.invoice_id,
                valor_aplicado=alloc.valor_aplicado,
                mes_referencia=alloc.mes_referencia,
                ano_referencia=alloc.ano_referencia,
            )
            for alloc in allocations
        ]

        # Numero sequencial legivel do recibo (5 digitos na exibicao).
        numero_recibo = await Counter.get_next("receipt_number")

        payment = Payment(
            client=client,
            valor_total=valor_total,
            metodo=metodo,
            grupo_pagamento=grupo,
            numero_recibo=numero_recibo,
            allocations=payment_allocations,
            recibido_por=recibido_por,
            observacion=observacion,
        )
        await payment.insert()

        # Atualiza faturas e cria SponsorDebts se aplicavel
        sponsor_debts_created: List[PydanticObjectId] = []
        total_subsidio = Decimal("0")

        for i, alloc in enumerate(allocations):
            invoice = await Invoice.get(alloc.invoice_id)
            if invoice:
                await invoice.update({
                    "$set": {
                        "saldo_devedor": alloc.saldo_restante,
                        "status": alloc.status_final,
                        "updated_at": datetime.utcnow(),
                    }
                })

                # Se cliente tem sponsor e fatura foi TOTALMENTE quitada, transfere subsidio
                if subsidy_info and alloc.status_final == InvoiceStatus.PAGADA:
                    # Calcula valor do subsidio baseado no valor ORIGINAL da fatura
                    valor_subsidio = (alloc.valor_original * subsidy_info.porcentagem) / Decimal("100")
                    total_subsidio += valor_subsidio

                    # Cria registro de divida do sponsor
                    sponsor_debt = SponsorDebt(
                        sponsor=client.sponsor_id,  # Link para o sponsor
                        client_original=client,
                        invoice_id=invoice.id,
                        mes_referencia=alloc.mes_referencia,
                        ano_referencia=alloc.ano_referencia,
                        valor_subsidio=valor_subsidio,
                        porcentagem_aplicada=subsidy_info.porcentagem,
                        payment_id=payment.id,
                        status=SponsorDebtStatus.PENDENTE,
                    )
                    await sponsor_debt.insert()
                    sponsor_debts_created.append(sponsor_debt.id)

                    # Atualiza allocation com info do subsidio
                    allocations[i] = AllocationResult(
                        invoice_id=alloc.invoice_id,
                        mes_referencia=alloc.mes_referencia,
                        ano_referencia=alloc.ano_referencia,
                        valor_original=alloc.valor_original,
                        saldo_anterior=alloc.saldo_anterior,
                        valor_aplicado=alloc.valor_aplicado,
                        saldo_restante=alloc.saldo_restante,
                        status_final=alloc.status_final,
                        subsidio_transferido=valor_subsidio,
                        sponsor_debt_id=sponsor_debt.id,
                    )

        total_applied = sum(a.valor_aplicado for a in allocations)

        # Cria transacao de entrada no caixa
        transaction = CashTransaction(
            tipo=TransactionType.ENTRADA,
            categoria=TransactionCategory.PAGAMENTO_FATURA,
            valor=valor_total,
            descripcion=f"Pagamento de faturas - {client.nombre_completo}",
            reference_id=payment.id,
            reference_type="payment",
            registrado_por=recibido_por,
        )
        await transaction.insert()

        # Auto-exit do workflow de corte se cliente pagou toda divida (antes do corte)
        from app.services.cutoff_service import CutoffService
        await CutoffService.check_auto_exit_for_client(client_id)

        # Auto-reativacao: se o cliente JA estava CORTADO e quitou a divida,
        # dispara automaticamente a solicitacao de reativacao (espelha o auto-exit).
        reactivation = await CutoffService.check_auto_reactivation_for_client(client_id)

        return DistributionResult(
            success=True,
            payment_id=payment.id,
            grupo_pagamento=grupo,
            allocations=allocations,
            total_applied=total_applied,
            overpayment=overpayment,
            total_subsidio=total_subsidio,
            sponsor_debts_created=sponsor_debts_created,
            reactivation_notice_id=reactivation.cutoff_notice_id if reactivation else None,
            reactivation_qr_token=reactivation.qr_token if reactivation else None,
            reactivation_comprobante=reactivation.comprobante if reactivation else None,
        )
