"""
Servico de geracao de faturas.

Implementa a logica de criacao de faturas a partir de leituras,
incluindo calculo de tarifas e excedentes.
"""

import calendar
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Optional

from beanie import PydanticObjectId

from app.models.client import Client, ClientStatus
from app.models.reading import Reading
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType, InvoiceItem, Counter
from app.models.settings import SystemSettings


@dataclass
class InvoiceGenerationResult:
    """Resultado da geracao de uma fatura."""
    success: bool
    invoice_id: Optional[PydanticObjectId] = None
    client_id: Optional[PydanticObjectId] = None
    error: Optional[str] = None


@dataclass
class BatchGenerationResult:
    """Resultado da geracao em lote."""
    total_generated: int
    total_skipped: int
    errors: List[str]


@dataclass
class ExtendedBatchGenerationResult:
    """Resultado estendido da geracao em lote."""
    total_generated: int = 0
    total_skipped: int = 0
    total_minimum_generated: int = 0
    total_minimum_skipped: int = 0
    errors: List[str] = field(default_factory=list)


class InvoiceGenerationService:
    """
    Servico para geracao de faturas de consumo.

    Responsabilidades:
    1. Calcular valor baseado em leitura e TARIFA UNICA GLOBAL
    2. Aplicar excedente quando consumo > limite base
    3. Gerar faturas independentes (apenas valor do mes)

    NOTA: O sistema usa tarifa unica. Subsidios sao aplicados no PAGAMENTO.
    """

    @staticmethod
    def calculate_excess(
        consumo: int,
        limite_base: int,
        valor_excedente_m3: Decimal
    ) -> Decimal:
        """Calcula valor do excedente de consumo."""
        if consumo <= limite_base:
            return Decimal("0")
        excess_m3 = consumo - limite_base
        return Decimal(excess_m3) * valor_excedente_m3

    @staticmethod
    def calculate_due_date(
        mes_referencia: int,
        ano_referencia: int,
        dias_vencimiento: int,
        dia_geracao: Optional[int] = None,
        dia_geracao_faturas: int = 1,
    ) -> date:
        """
        Calcula data de vencimento baseada no periodo de referencia.

        Se dia_geracao fornecido, usa como referencia de emissao.
        Senao, usa dia_geracao_faturas de SystemSettings.
        Vencimento = date(ano, mes, dia_ref) + timedelta(days=dias_vencimiento)
        """
        dia_ref = dia_geracao if dia_geracao is not None else dia_geracao_faturas
        max_day = calendar.monthrange(ano_referencia, mes_referencia)[1]
        dia_ref = min(dia_ref, max_day)
        fecha_emision_ref = date(ano_referencia, mes_referencia, dia_ref)
        return fecha_emision_ref + timedelta(days=dias_vencimiento)

    @classmethod
    async def generate_invoice_from_reading(
        cls,
        reading: Reading,
        settings: Optional[SystemSettings] = None,
        dia_geracao: Optional[int] = None,
    ) -> InvoiceGenerationResult:
        """
        Gera uma fatura a partir de uma leitura.

        Args:
            reading: Leitura com consumo calculado
            settings: Configuracoes do sistema (busca automaticamente se None)
            dia_geracao: Dia de geracao para calculo de vencimento (None = usa settings)

        Returns:
            InvoiceGenerationResult com status da operacao
        """
        if settings is None:
            settings = await SystemSettings.get_instance()

        # Busca cliente (pode ser Link ou objeto ja carregado)
        if hasattr(reading.client, 'fetch'):
            client = await reading.client.fetch()
        else:
            client = reading.client
        if not client:
            return InvoiceGenerationResult(
                success=False,
                error="Cliente da leitura nao encontrado"
            )

        # Verifica se ja existe fatura para o periodo
        existing = await Invoice.find_one(
            {"client.$id": client.id},
            Invoice.mes_referencia == reading.mes_referencia,
            Invoice.ano_referencia == reading.ano_referencia,
            Invoice.tipo == InvoiceType.CONSUMO,
        )
        if existing:
            return InvoiceGenerationResult(
                success=False,
                client_id=client.id,
                error=f"Fatura ja existe para {reading.mes_referencia}/{reading.ano_referencia}"
            )

        # Busca leitura anterior para dados da fatura
        prev_reading = await Reading.find(
            {"client.$id": client.id},
            {"$or": [
                {"ano_referencia": {"$lt": reading.ano_referencia}},
                {"$and": [
                    {"ano_referencia": reading.ano_referencia},
                    {"mes_referencia": {"$lt": reading.mes_referencia}}
                ]}
            ]}
        ).sort([("ano_referencia", -1), ("mes_referencia", -1)]).first_or_none()

        leitura_anterior = prev_reading.valor_leitura if prev_reading else 0
        consumo = reading.consumo_calculado or 0

        # Calcula valores - TARIFA UNICA GLOBAL
        tarifa_base = settings.tarifa_base
        excedente = cls.calculate_excess(
            consumo,
            settings.consumo_minimo,
            settings.valor_excedente_m3
        )
        valor_total = tarifa_base + excedente

        # Verifica valor minimo
        if valor_total < settings.valor_minimo_emissao:
            return InvoiceGenerationResult(
                success=False,
                client_id=client.id,
                error=f"Valor {valor_total} abaixo do minimo de emissao"
            )

        # Calcula vencimento usando dia_geracao
        fecha_vencimiento = cls.calculate_due_date(
            mes_referencia=reading.mes_referencia,
            ano_referencia=reading.ano_referencia,
            dias_vencimiento=settings.dias_vencimiento,
            dia_geracao=dia_geracao,
            dia_geracao_faturas=settings.dia_geracao_faturas,
        )

        # Gera numero sequencial
        numero_factura = await Counter.get_next("invoice_number")

        # Cria fatura
        invoice = Invoice(
            client=client,
            tipo=InvoiceType.CONSUMO,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=reading.mes_referencia,
            ano_referencia=reading.ano_referencia,
            fecha_vencimiento=fecha_vencimiento,
            leitura_anterior=leitura_anterior,
            leitura_actual=reading.valor_leitura,
            consumo=consumo,
            tarifa_base=tarifa_base,
            excedente=excedente,
            valor_total=valor_total,
            saldo_devedor=valor_total,
            reading_id=reading.id,
            numero_factura=numero_factura,
        )
        await invoice.insert()

        return InvoiceGenerationResult(
            success=True,
            invoice_id=invoice.id,
            client_id=client.id,
        )

    @classmethod
    async def generate_minimum_invoices(
        cls,
        mes: int,
        ano: int,
        settings: SystemSettings,
        dia_geracao: Optional[int] = None,
        client_ids: Optional[List[PydanticObjectId]] = None,
    ) -> BatchGenerationResult:
        """
        Gera faturas de valor minimo (tarifa_base) para clientes ativos
        que NAO possuem leitura no periodo.

        Estas faturas tem consumo=0, sem leitura associada.
        """
        results = BatchGenerationResult(
            total_generated=0,
            total_skipped=0,
            errors=[],
        )

        # 1. Busca clientes ativos
        client_query = Client.find(Client.status == ClientStatus.ATIVO)
        if client_ids:
            client_query = client_query.find({"_id": {"$in": client_ids}})
        all_clients = await client_query.to_list()

        # 2. Busca client_ids que ja tem leitura no periodo
        readings = await Reading.find(
            Reading.mes_referencia == mes,
            Reading.ano_referencia == ano,
        ).to_list()
        clients_with_reading = set()
        for r in readings:
            cid = r.client.ref.id if hasattr(r.client, 'ref') else r.client.id
            clients_with_reading.add(cid)

        # 3. Calcula vencimento
        fecha_vencimiento = cls.calculate_due_date(
            mes_referencia=mes,
            ano_referencia=ano,
            dias_vencimiento=settings.dias_vencimiento,
            dia_geracao=dia_geracao,
            dia_geracao_faturas=settings.dia_geracao_faturas,
        )

        valor_total = settings.tarifa_base

        # Verifica valor minimo de emissao
        if valor_total < settings.valor_minimo_emissao:
            return results

        for client in all_clients:
            if client.id in clients_with_reading:
                continue

            # Idempotencia: pula se fatura ja existe
            existing = await Invoice.find_one(
                {"client.$id": client.id},
                Invoice.mes_referencia == mes,
                Invoice.ano_referencia == ano,
                Invoice.tipo == InvoiceType.CONSUMO,
            )
            if existing:
                results.total_skipped += 1
                continue

            try:
                numero_factura = await Counter.get_next("invoice_number")

                invoice = Invoice(
                    client=client,
                    tipo=InvoiceType.CONSUMO,
                    status=InvoiceStatus.PENDENTE,
                    mes_referencia=mes,
                    ano_referencia=ano,
                    fecha_vencimiento=fecha_vencimiento,
                    leitura_anterior=None,
                    leitura_actual=None,
                    consumo=0,
                    tarifa_base=settings.tarifa_base,
                    excedente=Decimal("0"),
                    valor_total=valor_total,
                    saldo_devedor=valor_total,
                    reading_id=None,
                    numero_factura=numero_factura,
                )
                await invoice.insert()
                results.total_generated += 1
            except Exception as e:
                results.errors.append(
                    f"Erro fatura minima {client.nombre_completo}: {str(e)}"
                )

        return results

    @classmethod
    async def generate_batch(
        cls,
        mes: int,
        ano: int,
        client_ids: Optional[List[PydanticObjectId]] = None,
        gerar_sem_leitura_valor_minimo: bool = False,
        dia_geracao: Optional[int] = None,
    ) -> ExtendedBatchGenerationResult:
        """
        Gera faturas em lote para um periodo.

        Fase 1: Gera faturas para todas as leituras do periodo.
        Fase 2: Se gerar_sem_leitura_valor_minimo=True, gera faturas
                 de tarifa_base para clientes ativos sem leitura.

        Args:
            mes: Mes de referencia
            ano: Ano de referencia
            client_ids: Lista de IDs de clientes (None = todos)
            gerar_sem_leitura_valor_minimo: Gerar faturas minimas sem leitura
            dia_geracao: Dia de geracao para calculo de vencimento

        Returns:
            ExtendedBatchGenerationResult com estatisticas
        """
        settings = await SystemSettings.get_instance()
        results = ExtendedBatchGenerationResult()

        # Fase 1: Gera faturas a partir de leituras
        readings = await Reading.find(
            Reading.mes_referencia == mes,
            Reading.ano_referencia == ano,
        ).to_list()

        for reading in readings:
            r_client_id = reading.client.ref.id if hasattr(reading.client, 'ref') else reading.client.id
            if client_ids and r_client_id not in client_ids:
                continue

            result = await cls.generate_invoice_from_reading(
                reading, settings, dia_geracao=dia_geracao
            )

            if result.success:
                results.total_generated += 1
            elif "ja existe" in (result.error or ""):
                results.total_skipped += 1
            else:
                results.errors.append(result.error or "Erro desconhecido")

        # Fase 2: Gera faturas minimas para clientes sem leitura
        if gerar_sem_leitura_valor_minimo:
            min_results = await cls.generate_minimum_invoices(
                mes=mes,
                ano=ano,
                settings=settings,
                dia_geracao=dia_geracao,
                client_ids=client_ids,
            )
            results.total_minimum_generated = min_results.total_generated
            results.total_minimum_skipped = min_results.total_skipped
            results.errors.extend(min_results.errors)

        return results

    @classmethod
    async def create_custom_invoice(
        cls,
        client_id: PydanticObjectId,
        items: List[InvoiceItem],
        mes_referencia: int,
        ano_referencia: int,
        fecha_vencimiento: Optional[date] = None,
    ) -> InvoiceGenerationResult:
        """
        Cria uma fatura avulsa com itens personalizados.

        Args:
            client_id: ID do cliente
            items: Lista de itens da fatura
            mes_referencia: Mes de referencia
            ano_referencia: Ano de referencia
            fecha_vencimiento: Data de vencimento (opcional)

        Returns:
            InvoiceGenerationResult com status
        """
        client = await Client.get(client_id)
        if not client:
            return InvoiceGenerationResult(
                success=False,
                error="Cliente nao encontrado"
            )

        if not items:
            return InvoiceGenerationResult(
                success=False,
                client_id=client_id,
                error="Fatura deve ter pelo menos um item"
            )

        settings = await SystemSettings.get_instance()

        # Calcula total
        valor_total = sum(item.subtotal for item in items)

        # Define vencimento
        if fecha_vencimiento is None:
            fecha_vencimiento = date.today() + timedelta(days=settings.dias_vencimiento)

        # Gera numero sequencial
        numero_factura = await Counter.get_next("invoice_number")

        invoice = Invoice(
            client=client,
            tipo=InvoiceType.AVULSA,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=mes_referencia,
            ano_referencia=ano_referencia,
            fecha_vencimiento=fecha_vencimiento,
            items=items,
            valor_total=valor_total,
            saldo_devedor=valor_total,
            numero_factura=numero_factura,
        )
        await invoice.insert()

        return InvoiceGenerationResult(
            success=True,
            invoice_id=invoice.id,
            client_id=client_id,
        )
