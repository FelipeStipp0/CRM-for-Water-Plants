"""
Servico de gestao de Sponsors (Subsidios).

Responsabilidades:
1. Gerar faturas agregadas mensais para sponsors
2. Processar pagamentos de faturas de sponsor
3. Consultar dividas pendentes por sponsor
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from beanie import PydanticObjectId

from app.models.client import Client
from app.models.sponsor import SponsorDebt, SponsorDebtStatus, SponsorInvoice
from app.models.finance import CashTransaction, TransactionType, TransactionCategory


@dataclass
class SponsorDebtSummary:
    """Resumo de dividas de um sponsor."""
    sponsor_id: PydanticObjectId
    sponsor_name: str
    total_pendente: Decimal
    total_faturado: Decimal
    total_pago: Decimal
    count_debts: int


@dataclass
class AggregatedInvoiceResult:
    """Resultado da geracao de fatura agregada."""
    success: bool
    invoice_id: Optional[PydanticObjectId] = None
    debts_included: int = 0
    valor_total: Decimal = Decimal("0")
    error: Optional[str] = None


class SponsorService:
    """
    Servico para gestao de sponsors e suas dividas de subsidio.

    Fluxo mensal:
    1. Coletar todas as SponsorDebts PENDENTES do mes/ano
    2. Criar SponsorInvoice agregando todas
    3. Marcar debts como FATURADO
    4. Sponsor paga a SponsorInvoice
    """

    @staticmethod
    async def get_sponsor_clients(sponsor_id: PydanticObjectId) -> List[Client]:
        """
        Retorna todos os clientes que tem este sponsor.

        Args:
            sponsor_id: ID do sponsor

        Returns:
            Lista de clientes subsidiados por este sponsor
        """
        return await Client.find(
            Client.sponsor_id == sponsor_id
        ).to_list()

    @staticmethod
    async def get_pending_debts(
        sponsor_id: PydanticObjectId,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
    ) -> List[SponsorDebt]:
        """
        Busca dividas pendentes de um sponsor.

        Args:
            sponsor_id: ID do sponsor
            mes: Filtrar por mes (opcional)
            ano: Filtrar por ano (opcional)

        Returns:
            Lista de SponsorDebts pendentes
        """
        query = {
            "sponsor.$id": sponsor_id,
            "status": SponsorDebtStatus.PENDENTE.value,
        }

        if mes is not None:
            query["mes_referencia"] = mes
        if ano is not None:
            query["ano_referencia"] = ano

        return await SponsorDebt.find(query).to_list()

    @staticmethod
    async def get_sponsor_summary(sponsor_id: PydanticObjectId) -> SponsorDebtSummary:
        """
        Retorna resumo financeiro do sponsor.

        Args:
            sponsor_id: ID do sponsor

        Returns:
            SponsorDebtSummary com totais
        """
        sponsor = await Client.get(sponsor_id)
        if not sponsor:
            raise ValueError("Sponsor nao encontrado")

        all_debts = await SponsorDebt.find(
            {"sponsor.$id": sponsor_id}
        ).to_list()

        total_pendente = sum(
            d.valor_subsidio for d in all_debts
            if d.status == SponsorDebtStatus.PENDENTE
        )
        total_faturado = sum(
            d.valor_subsidio for d in all_debts
            if d.status == SponsorDebtStatus.FATURADO
        )
        total_pago = sum(
            d.valor_subsidio for d in all_debts
            if d.status == SponsorDebtStatus.PAGO
        )

        return SponsorDebtSummary(
            sponsor_id=sponsor_id,
            sponsor_name=sponsor.nombre_completo,
            total_pendente=total_pendente,
            total_faturado=total_faturado,
            total_pago=total_pago,
            count_debts=len(all_debts),
        )

    @classmethod
    async def generate_aggregated_invoice(
        cls,
        sponsor_id: PydanticObjectId,
        mes_referencia: int,
        ano_referencia: int,
    ) -> AggregatedInvoiceResult:
        """
        Gera fatura agregada para um sponsor.

        Consolida todas as dividas PENDENTES em uma unica fatura.

        Args:
            sponsor_id: ID do sponsor
            mes_referencia: Mes de referencia
            ano_referencia: Ano de referencia

        Returns:
            AggregatedInvoiceResult com detalhes
        """
        # Verifica sponsor existe
        sponsor = await Client.get(sponsor_id)
        if not sponsor:
            return AggregatedInvoiceResult(
                success=False,
                error="Sponsor nao encontrado"
            )

        # Verifica se ja existe fatura para o periodo
        existing = await SponsorInvoice.find_one(
            {"sponsor.$id": sponsor_id},
            SponsorInvoice.mes_referencia == mes_referencia,
            SponsorInvoice.ano_referencia == ano_referencia,
        )
        if existing:
            return AggregatedInvoiceResult(
                success=False,
                error=f"Fatura agregada ja existe para {mes_referencia}/{ano_referencia}"
            )

        # Busca dividas pendentes
        pending_debts = await cls.get_pending_debts(sponsor_id)

        if not pending_debts:
            return AggregatedInvoiceResult(
                success=False,
                error="Nenhuma divida pendente para este sponsor"
            )

        # Calcula total
        valor_total = sum(d.valor_subsidio for d in pending_debts)
        debt_ids = [d.id for d in pending_debts]

        # Cria fatura agregada
        invoice = SponsorInvoice(
            sponsor=sponsor,
            mes_referencia=mes_referencia,
            ano_referencia=ano_referencia,
            debts_included=debt_ids,
            valor_total=valor_total,
            saldo_devedor=valor_total,
            status="PENDENTE",
        )
        await invoice.insert()

        # Atualiza status das dividas para FATURADO
        for debt in pending_debts:
            await debt.update({
                "$set": {
                    "status": SponsorDebtStatus.FATURADO,
                    "fatura_agregada_id": invoice.id,
                }
            })

        return AggregatedInvoiceResult(
            success=True,
            invoice_id=invoice.id,
            debts_included=len(debt_ids),
            valor_total=valor_total,
        )

    @classmethod
    async def pay_sponsor_invoice(
        cls,
        invoice_id: PydanticObjectId,
        valor: Decimal,
        recibido_por: Optional[str] = None,
    ) -> dict:
        """
        Processa pagamento de fatura de sponsor.

        Args:
            invoice_id: ID da SponsorInvoice
            valor: Valor do pagamento
            recibido_por: Nome de quem recebeu

        Returns:
            Dict com resultado
        """
        invoice = await SponsorInvoice.get(invoice_id)
        if not invoice:
            return {"success": False, "error": "Fatura nao encontrada"}

        if invoice.status == "PAGADA":
            return {"success": False, "error": "Fatura ja esta paga"}

        # Aplica pagamento
        novo_saldo = invoice.saldo_devedor - valor
        if novo_saldo < 0:
            novo_saldo = Decimal("0")

        novo_status = "PAGADA" if novo_saldo <= 0 else "PENDENTE"

        await invoice.update({
            "$set": {
                "saldo_devedor": novo_saldo,
                "status": novo_status,
                "fecha_pago": datetime.utcnow() if novo_status == "PAGADA" else None,
            }
        })

        # Se quitado, marca todas as debts como PAGO
        if novo_status == "PAGADA":
            for debt_id in invoice.debts_included:
                debt = await SponsorDebt.get(debt_id)
                if debt:
                    await debt.update({"$set": {"status": SponsorDebtStatus.PAGO}})

        # Registra entrada no caixa
        # Busca sponsor para nome
        sponsor = await invoice.sponsor.fetch() if hasattr(invoice.sponsor, 'fetch') else invoice.sponsor
        sponsor_name = sponsor.nombre_completo if sponsor else "Sponsor"

        transaction = CashTransaction(
            tipo=TransactionType.ENTRADA,
            categoria=TransactionCategory.PAGAMENTO_FATURA,
            valor=valor,
            descripcion=f"Pagamento fatura agregada - {sponsor_name}",
            reference_id=invoice_id,
            reference_type="sponsor_invoice",
            registrado_por=recibido_por,
        )
        await transaction.insert()

        return {
            "success": True,
            "novo_saldo": novo_saldo,
            "status": novo_status,
        }

    @staticmethod
    async def list_sponsor_invoices(
        sponsor_id: PydanticObjectId,
        status: Optional[str] = None,
    ) -> List[SponsorInvoice]:
        """
        Lista faturas agregadas de um sponsor.

        Args:
            sponsor_id: ID do sponsor
            status: Filtrar por status (opcional)

        Returns:
            Lista de SponsorInvoices
        """
        query = {"sponsor.$id": sponsor_id}
        if status:
            query["status"] = status

        return await SponsorInvoice.find(query).sort([
            ("ano_referencia", -1),
            ("mes_referencia", -1),
        ]).to_list()
