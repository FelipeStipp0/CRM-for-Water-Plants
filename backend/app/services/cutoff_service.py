"""
Servico de gerenciamento do workflow de corte.

Responsabilidades:
1. Identificar candidatos a corte (inadimplentes)
2. Gerenciar transicoes de estado do workflow
3. Gerar tokens QR para confirmacao por entregadores/tecnicos
4. Auto-exit quando cliente paga divida
5. Processar reativacao (divida + taxa)
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from beanie import PydanticObjectId

from app.models.client import Client, ClientStatus
from app.models.cutoff import CutoffNotice, CutoffStatus, CutoffActionType
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment
from app.models.settings import SystemSettings
from app.models.finance import CashTransaction, TransactionType, TransactionCategory


def _generate_qr_token() -> str:
    """Gera token unico para QR Code (32 chars, URL-safe)."""
    return uuid4().hex


@dataclass
class CutoffCandidate:
    """Cliente candidato a corte."""
    client_id: PydanticObjectId
    nombre_completo: str
    ci_ruc: str
    manzana: str
    lote: str
    divida_total: Decimal
    meses_atraso: int
    oldest_invoice_date: date


@dataclass
class CutoffActionResult:
    """Resultado de uma acao no workflow."""
    success: bool
    cutoff_notice_id: Optional[PydanticObjectId] = None
    message: Optional[str] = None
    error: Optional[str] = None
    qr_token: Optional[str] = None
    action_type: Optional[CutoffActionType] = None
    comprobante: Optional[str] = None
    fecha_pago: Optional[datetime] = None


class CutoffService:
    """Servico de workflow de corte."""

    @staticmethod
    async def _calculate_months_overdue(client_id: PydanticObjectId) -> tuple[int, Optional[date]]:
        """Calcula meses de atraso a partir da fatura mais antiga pendente."""
        oldest_invoice = await Invoice.find(
            {"client.$id": client_id},
            Invoice.saldo_devedor > 0,
            Invoice.status != InvoiceStatus.ANULADA,
        ).sort("fecha_vencimiento").first_or_none()

        if not oldest_invoice:
            return 0, None

        today = date.today()
        venc = oldest_invoice.fecha_vencimiento
        months = (today.year - venc.year) * 12 + (today.month - venc.month)
        return max(0, months), venc

    @staticmethod
    async def _calculate_total_debt(client_id: PydanticObjectId) -> Decimal:
        """Calcula divida total do cliente."""
        invoices = await Invoice.find(
            {"client.$id": client_id},
            Invoice.saldo_devedor > 0,
            Invoice.status != InvoiceStatus.ANULADA,
        ).to_list()
        return sum(inv.saldo_devedor for inv in invoices) if invoices else Decimal("0")

    @staticmethod
    async def _has_active_notice(client_id: PydanticObjectId) -> Optional[CutoffNotice]:
        """Busca aviso ativo (nao saiu por pagamento e nao reativado)."""
        return await CutoffNotice.find_one(
            {"client.$id": client_id},
            CutoffNotice.saiu_por_pagamento == False,
            {"$or": [
                {"fecha_reativacao": None},
                {"fecha_reativacao": {"$exists": False}},
            ]},
        )

    # ==================== CANDIDATOS ====================

    @classmethod
    async def get_cutoff_candidates(cls) -> List[CutoffCandidate]:
        """
        Lista clientes ATIVO com atraso >= meses_atraso_corte,
        excluindo os que ja estao no workflow.
        """
        settings = await SystemSettings.get_instance()

        # Busca clientes ATIVO com divida
        active_clients = await Client.find(
            Client.status == ClientStatus.ATIVO,
        ).to_list()

        candidates = []
        for client in active_clients:
            # Verifica se ja esta no workflow
            existing = await cls._has_active_notice(client.id)
            if existing:
                continue

            meses_atraso, oldest_date = await cls._calculate_months_overdue(client.id)
            if meses_atraso < settings.meses_atraso_corte:
                continue

            divida = await cls._calculate_total_debt(client.id)
            if divida <= 0:
                continue

            candidates.append(CutoffCandidate(
                client_id=client.id,
                nombre_completo=client.nombre_completo,
                ci_ruc=client.ci_ruc,
                manzana=client.manzana,
                lote=client.lote,
                divida_total=divida,
                meses_atraso=meses_atraso,
                oldest_invoice_date=oldest_date,
            ))

        return candidates

    # ==================== WORKFLOW ====================

    @classmethod
    async def add_to_list(cls, client_id: PydanticObjectId) -> CutoffActionResult:
        """Adiciona cliente a lista de corte (-> EM_LISTA)."""
        client = await Client.get(client_id)
        if not client:
            return CutoffActionResult(success=False, error="Cliente nao encontrado")

        if client.status != ClientStatus.ATIVO:
            return CutoffActionResult(success=False, error="Cliente nao esta ATIVO")

        existing = await cls._has_active_notice(client_id)
        if existing:
            return CutoffActionResult(
                success=False,
                error=f"Cliente ja possui aviso ativo (status: {existing.status.value})",
            )

        divida = await cls._calculate_total_debt(client_id)
        if divida <= 0:
            return CutoffActionResult(success=False, error="Cliente nao possui divida")

        meses_atraso, _ = await cls._calculate_months_overdue(client_id)

        notice = CutoffNotice(
            client=client,
            status=CutoffStatus.EM_LISTA,
            divida_original=divida,
            meses_atraso=meses_atraso,
        )
        await notice.insert()

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message=f"Cliente adicionado a lista de corte. Divida: {divida}",
        )

    @classmethod
    async def generate_notice(cls, notice_id: PydanticObjectId) -> CutoffActionResult:
        """Gera aviso de corte + QR token (EM_LISTA -> EM_AVISO)."""
        notice = await CutoffNotice.get(notice_id)
        if not notice:
            return CutoffActionResult(success=False, error="Aviso nao encontrado")

        if notice.status != CutoffStatus.EM_LISTA:
            return CutoffActionResult(
                success=False,
                error=f"Status atual ({notice.status.value}) nao permite gerar aviso",
            )

        token = _generate_qr_token()
        now = datetime.utcnow()

        await notice.update({"$set": {
            "status": CutoffStatus.EM_AVISO.value,
            "qr_token_entrega": token,
            "fecha_aviso_gerado": now,
            "updated_at": now,
        }})

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message="Aviso gerado. Imprima e entregue ao cliente.",
            qr_token=token,
            action_type=CutoffActionType.ENTREGA_AVISO,
        )

    @classmethod
    async def _start_countdown(cls, notice: CutoffNotice, entregue_por: Optional[str] = None, observacion: Optional[str] = None) -> CutoffActionResult:
        """Logica compartilhada para iniciar countdown."""
        settings = await SystemSettings.get_instance()
        now = datetime.utcnow()
        fecha_limite = date.today() + timedelta(days=settings.dias_prazo_aviso)

        update_data = {
            "status": CutoffStatus.EM_CONTAGEM.value,
            "fecha_entrega_aviso": now,
            "fecha_limite_pago": fecha_limite,
            "updated_at": now,
        }
        if entregue_por:
            update_data["aviso_entregue_por"] = entregue_por
        if observacion:
            update_data["observacion_aviso"] = observacion

        await notice.update({"$set": update_data})

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message=f"Countdown iniciado. Prazo ate {fecha_limite.strftime('%d/%m/%Y')}",
        )

    @classmethod
    async def confirm_delivery_by_qr(
        cls,
        qr_token: str,
        nome_responsavel: str,
        observacion: Optional[str] = None,
    ) -> CutoffActionResult:
        """Confirma entrega via QR (EM_AVISO -> EM_CONTAGEM)."""
        notice = await CutoffNotice.find_one(CutoffNotice.qr_token_entrega == qr_token)
        if not notice:
            return CutoffActionResult(success=False, error="Token invalido ou ja utilizado")

        if notice.status != CutoffStatus.EM_AVISO:
            return CutoffActionResult(
                success=False,
                error=f"Acao ja foi realizada (status: {notice.status.value})",
            )

        return await cls._start_countdown(notice, entregue_por=nome_responsavel, observacion=observacion)

    @classmethod
    async def register_delivery_manual(
        cls,
        notice_id: PydanticObjectId,
        entregue_por: Optional[str] = None,
        observacion: Optional[str] = None,
    ) -> CutoffActionResult:
        """Registra entrega manual (EM_AVISO -> EM_CONTAGEM)."""
        notice = await CutoffNotice.get(notice_id)
        if not notice:
            return CutoffActionResult(success=False, error="Aviso nao encontrado")

        if notice.status != CutoffStatus.EM_AVISO:
            return CutoffActionResult(
                success=False,
                error=f"Status atual ({notice.status.value}) nao permite registrar entrega",
            )

        return await cls._start_countdown(notice, entregue_por=entregue_por, observacion=observacion)

    @classmethod
    async def mark_ready_for_cutoff(cls, notice_id: PydanticObjectId) -> CutoffActionResult:
        """Marca como pronto para corte (EM_CONTAGEM -> PRONTO_PARA_CORTE)."""
        notice = await CutoffNotice.get(notice_id)
        if not notice:
            return CutoffActionResult(success=False, error="Aviso nao encontrado")

        if notice.status != CutoffStatus.EM_CONTAGEM:
            return CutoffActionResult(
                success=False,
                error=f"Status atual ({notice.status.value}) nao permite marcar como pronto",
            )

        if notice.fecha_limite_pago and date.today() < notice.fecha_limite_pago:
            return CutoffActionResult(
                success=False,
                error=f"Countdown ativo ate {notice.fecha_limite_pago.strftime('%d/%m/%Y')}",
            )

        now = datetime.utcnow()
        await notice.update({"$set": {
            "status": CutoffStatus.PRONTO_PARA_CORTE.value,
            "updated_at": now,
        }})

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message="Marcado como PRONTO PARA CORTE",
        )

    @classmethod
    async def generate_cutoff_order(cls, notice_id: PydanticObjectId) -> CutoffActionResult:
        """Gera ordem de corte + QR token (para PRONTO_PARA_CORTE)."""
        notice = await CutoffNotice.get(notice_id)
        if not notice:
            return CutoffActionResult(success=False, error="Aviso nao encontrado")

        if notice.status != CutoffStatus.PRONTO_PARA_CORTE:
            return CutoffActionResult(
                success=False,
                error=f"Status atual ({notice.status.value}) nao permite gerar ordem de corte",
            )

        token = _generate_qr_token()
        now = datetime.utcnow()

        await notice.update({"$set": {
            "qr_token_corte": token,
            "updated_at": now,
        }})

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message="Ordem de corte gerada. Imprima e entregue ao tecnico.",
            qr_token=token,
            action_type=CutoffActionType.EXECUCAO_CORTE,
        )

    @classmethod
    async def _execute_cutoff(
        cls, notice: CutoffNotice, cortado_por: Optional[str] = None, observacion: Optional[str] = None,
        foto_url: Optional[str] = None, gps_latitude: Optional[float] = None, gps_longitude: Optional[float] = None,
    ) -> CutoffActionResult:
        """Logica compartilhada para executar corte."""
        client = await notice.client.fetch()
        if not client:
            return CutoffActionResult(success=False, error="Cliente nao encontrado")

        now = datetime.utcnow()

        update_data = {
            "status": CutoffStatus.CORTADO.value,
            "fecha_corte": now,
            "cortado_por": cortado_por,
            "observacion_corte": observacion,
            "updated_at": now,
        }
        if foto_url:
            update_data["foto_instalacao_url"] = foto_url
        if gps_latitude is not None:
            update_data["gps_corte_latitude"] = gps_latitude
        if gps_longitude is not None:
            update_data["gps_corte_longitude"] = gps_longitude

        await notice.update({"$set": update_data})

        await client.update({"$set": {
            "status": ClientStatus.CORTADO.value,
            "updated_at": now,
        }})

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message=f"Corte executado. Cliente marcado como CORTADO.",
        )

    @classmethod
    async def confirm_cutoff_by_qr(
        cls,
        qr_token: str,
        nome_responsavel: str,
        observacion: Optional[str] = None,
        foto_url: Optional[str] = None,
        gps_latitude: Optional[float] = None,
        gps_longitude: Optional[float] = None,
    ) -> CutoffActionResult:
        """Confirma corte via QR (PRONTO_PARA_CORTE -> CORTADO)."""
        notice = await CutoffNotice.find_one(CutoffNotice.qr_token_corte == qr_token)
        if not notice:
            return CutoffActionResult(success=False, error="Token invalido ou ja utilizado")

        if notice.status != CutoffStatus.PRONTO_PARA_CORTE:
            return CutoffActionResult(
                success=False,
                error=f"Acao ja foi realizada (status: {notice.status.value})",
            )

        return await cls._execute_cutoff(
            notice, cortado_por=nome_responsavel, observacion=observacion,
            foto_url=foto_url, gps_latitude=gps_latitude, gps_longitude=gps_longitude,
        )

    @classmethod
    async def execute_cutoff_manual(
        cls,
        notice_id: PydanticObjectId,
        cortado_por: Optional[str] = None,
        observacion: Optional[str] = None,
        foto_url: Optional[str] = None,
        gps_latitude: Optional[float] = None,
        gps_longitude: Optional[float] = None,
    ) -> CutoffActionResult:
        """Executa corte manual (PRONTO_PARA_CORTE -> CORTADO)."""
        notice = await CutoffNotice.get(notice_id)
        if not notice:
            return CutoffActionResult(success=False, error="Aviso nao encontrado")

        if notice.status != CutoffStatus.PRONTO_PARA_CORTE:
            return CutoffActionResult(
                success=False,
                error=f"Status atual ({notice.status.value}) nao permite executar corte",
            )

        return await cls._execute_cutoff(
            notice, cortado_por=cortado_por, observacion=observacion,
            foto_url=foto_url, gps_latitude=gps_latitude, gps_longitude=gps_longitude,
        )

    # ==================== AUTO-EXIT ====================

    @classmethod
    async def check_auto_exit_for_client(cls, client_id: PydanticObjectId) -> bool:
        """
        Verifica se cliente pagou toda divida e deve sair do workflow.
        Chamado automaticamente apos processar pagamento.
        """
        notice = await CutoffNotice.find_one(
            {"client.$id": client_id},
            CutoffNotice.saiu_por_pagamento == False,
            CutoffNotice.status != CutoffStatus.CORTADO,
            {"$or": [
                {"fecha_reativacao": None},
                {"fecha_reativacao": {"$exists": False}},
            ]},
        )

        if not notice:
            return False

        # Verifica se ainda tem divida
        has_debt = await Invoice.find_one(
            {"client.$id": client_id},
            Invoice.saldo_devedor > 0,
            Invoice.status != InvoiceStatus.ANULADA,
        )

        if has_debt:
            return False

        now = datetime.utcnow()
        await notice.update({"$set": {
            "saiu_por_pagamento": True,
            "fecha_saida": now,
            "updated_at": now,
        }})

        return True

    @classmethod
    async def check_auto_reactivation_for_client(
        cls, client_id: PydanticObjectId,
    ) -> Optional[CutoffActionResult]:
        """
        Espelha check_auto_exit, mas para o caso PÓS-corte: quando um cliente
        CORTADO quita toda a dívida, dispara automaticamente a solicitação de
        reativação (registra a taxa, gera o QR e o comprobante = numero_recibo do
        pagamento). Chamado automaticamente após processar um pagamento.

        Retorna o CutoffActionResult da reativação, ou None se não se aplica.
        """
        client = await Client.get(client_id)
        if not client or client.status != ClientStatus.CORTADO:
            return None

        notice = await CutoffNotice.find_one(
            {"client.$id": client_id},
            CutoffNotice.status == CutoffStatus.CORTADO,
            CutoffNotice.reativacao_solicitada == False,
        )
        if not notice:
            return None

        # Só dispara quando não há mais dívida pendente.
        has_debt = await Invoice.find_one(
            {"client.$id": client_id},
            Invoice.saldo_devedor > 0,
            Invoice.status != InvoiceStatus.ANULADA,
        )
        if has_debt:
            return None

        settings = await SystemSettings.get_instance()
        now = datetime.utcnow()

        # Registra a taxa de reativação no caixa (mesma lógica do fluxo manual).
        transaction = CashTransaction(
            tipo=TransactionType.ENTRADA,
            categoria=TransactionCategory.TAXA_REATIVACAO,
            valor=settings.taxa_reativacao,
            descripcion=f"Taxa de reativacao - {client.nombre_completo}",
            reference_id=notice.id,
            reference_type="cutoff_notice",
            fecha=now,
        )
        await transaction.insert()

        token = _generate_qr_token()
        await notice.update({"$set": {
            "reativacao_solicitada": True,
            "fecha_solicitud_reativacao": now,
            "taxa_reativacao_paga": True,
            "qr_token_reativacao": token,
            "updated_at": now,
        }})

        # Comprobante = numero do recibo do pagamento que quitou a dívida.
        latest_payment = await Payment.find(
            {"client.$id": client_id}
        ).sort("-fecha_pago").first_or_none()
        comprobante = (
            latest_payment.numero_recibo_fmt
            if latest_payment and latest_payment.numero_recibo is not None
            else None
        )
        fecha_pago = latest_payment.fecha_pago if latest_payment else now

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message="Reativacao solicitada automaticamente apos pagamento.",
            qr_token=token,
            action_type=CutoffActionType.CONFIRMACAO_REATIVACAO,
            comprobante=comprobante,
            fecha_pago=fecha_pago,
        )

    # ==================== REATIVACAO ====================

    @classmethod
    async def request_reactivation(
        cls,
        client_id: PydanticObjectId,
        valor_pago: Decimal,
        registrado_por: Optional[str] = None,
    ) -> CutoffActionResult:
        """
        Solicita reativacao: paga divida + taxa_reativacao.
        Registra CashTransaction e gera QR token para tecnico.
        """
        settings = await SystemSettings.get_instance()

        client = await Client.get(client_id)
        if not client:
            return CutoffActionResult(success=False, error="Cliente nao encontrado")

        if client.status != ClientStatus.CORTADO:
            return CutoffActionResult(success=False, error="Cliente nao esta CORTADO")

        notice = await CutoffNotice.find_one(
            {"client.$id": client_id},
            CutoffNotice.status == CutoffStatus.CORTADO,
            CutoffNotice.reativacao_solicitada == False,
        )
        if not notice:
            return CutoffActionResult(
                success=False,
                error="Nao encontrado registro de corte ativo para este cliente",
            )

        divida_atual = await cls._calculate_total_debt(client_id)
        valor_esperado = divida_atual + settings.taxa_reativacao

        if valor_pago < valor_esperado:
            return CutoffActionResult(
                success=False,
                error=f"Valor insuficiente. Esperado: {valor_esperado} (Divida: {divida_atual} + Taxa: {settings.taxa_reativacao})",
            )

        # Registra taxa no caixa
        now = datetime.utcnow()
        transaction = CashTransaction(
            tipo=TransactionType.ENTRADA,
            categoria=TransactionCategory.TAXA_REATIVACAO,
            valor=settings.taxa_reativacao,
            descripcion=f"Taxa de reativacao - {client.nombre_completo}",
            reference_id=notice.id,
            reference_type="cutoff_notice",
            registrado_por=registrado_por,
            fecha=now,
        )
        await transaction.insert()

        token = _generate_qr_token()

        await notice.update({"$set": {
            "reativacao_solicitada": True,
            "fecha_solicitud_reativacao": now,
            "taxa_reativacao_paga": True,
            "qr_token_reativacao": token,
            "updated_at": now,
        }})

        # Comprobante = numero do recibo do pagamento que quitou a divida do corte
        # (o ultimo pagamento do cliente). Formatado com 5 digitos ("00001").
        latest_payment = await Payment.find(
            {"client.$id": client_id}
        ).sort("-fecha_pago").first_or_none()
        comprobante = (
            latest_payment.numero_recibo_fmt
            if latest_payment and latest_payment.numero_recibo is not None
            else None
        )
        fecha_pago = latest_payment.fecha_pago if latest_payment else now

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message=f"Reativacao solicitada. Taxa {settings.taxa_reativacao} registrada. Aguarda tecnico.",
            qr_token=token,
            action_type=CutoffActionType.CONFIRMACAO_REATIVACAO,
            comprobante=comprobante,
            fecha_pago=fecha_pago,
        )

    @classmethod
    async def _confirm_reactivation(
        cls, notice: CutoffNotice, confirmado_por: Optional[str] = None,
        foto_url: Optional[str] = None, gps_latitude: Optional[float] = None, gps_longitude: Optional[float] = None,
    ) -> CutoffActionResult:
        """Logica compartilhada de confirmacao de reativacao."""
        if notice.status != CutoffStatus.CORTADO:
            return CutoffActionResult(success=False, error="Cliente nao esta CORTADO")

        if not notice.reativacao_solicitada or not notice.taxa_reativacao_paga:
            return CutoffActionResult(
                success=False,
                error="Reativacao nao foi solicitada ou taxa nao foi paga",
            )

        client = await notice.client.fetch()
        if not client:
            return CutoffActionResult(success=False, error="Cliente nao encontrado")

        now = datetime.utcnow()

        update_data = {
            "fecha_reativacao": now,
            "reativacao_confirmada_por": confirmado_por,
            "updated_at": now,
        }
        if foto_url:
            update_data["foto_reativacao_url"] = foto_url
        if gps_latitude is not None:
            update_data["gps_reativacao_latitude"] = gps_latitude
        if gps_longitude is not None:
            update_data["gps_reativacao_longitude"] = gps_longitude

        await notice.update({"$set": update_data})

        await client.update({"$set": {
            "status": ClientStatus.ATIVO.value,
            "updated_at": now,
        }})

        return CutoffActionResult(
            success=True,
            cutoff_notice_id=notice.id,
            message=f"Reativacao confirmada. Cliente restaurado para ATIVO.",
        )

    @classmethod
    async def confirm_reactivation_by_qr(
        cls,
        qr_token: str,
        nome_responsavel: str,
        foto_url: Optional[str] = None,
        gps_latitude: Optional[float] = None,
        gps_longitude: Optional[float] = None,
    ) -> CutoffActionResult:
        """Confirma reativacao via QR."""
        notice = await CutoffNotice.find_one(CutoffNotice.qr_token_reativacao == qr_token)
        if not notice:
            return CutoffActionResult(success=False, error="Token invalido ou ja utilizado")

        if notice.fecha_reativacao is not None:
            return CutoffActionResult(success=False, error="Reativacao ja foi confirmada")

        return await cls._confirm_reactivation(
            notice, confirmado_por=nome_responsavel,
            foto_url=foto_url, gps_latitude=gps_latitude, gps_longitude=gps_longitude,
        )

    @classmethod
    async def confirm_reactivation_manual(
        cls,
        notice_id: PydanticObjectId,
        confirmado_por: Optional[str] = None,
        foto_url: Optional[str] = None,
        gps_latitude: Optional[float] = None,
        gps_longitude: Optional[float] = None,
    ) -> CutoffActionResult:
        """Confirma reativacao manual."""
        notice = await CutoffNotice.get(notice_id)
        if not notice:
            return CutoffActionResult(success=False, error="Aviso nao encontrado")

        if notice.fecha_reativacao is not None:
            return CutoffActionResult(success=False, error="Reativacao ja foi confirmada")

        return await cls._confirm_reactivation(
            notice, confirmado_por=confirmado_por,
            foto_url=foto_url, gps_latitude=gps_latitude, gps_longitude=gps_longitude,
        )

    # ==================== BATCH ====================

    @classmethod
    async def process_expired_countdowns(cls) -> int:
        """
        Marca countdowns expirados como PRONTO_PARA_CORTE.
        Retorna quantidade de avisos marcados.
        """
        today = date.today()

        expired = await CutoffNotice.find(
            CutoffNotice.status == CutoffStatus.EM_CONTAGEM,
            CutoffNotice.saiu_por_pagamento == False,
            CutoffNotice.fecha_limite_pago <= today,
        ).to_list()

        count = 0
        for notice in expired:
            result = await cls.mark_ready_for_cutoff(notice.id)
            if result.success:
                count += 1

        return count

    # ==================== QR INFO ====================

    @classmethod
    async def get_qr_info(cls, token: str) -> Optional[dict]:
        """Retorna informacoes do aviso pelo token QR (para tela de confirmacao)."""
        # Tenta cada tipo de token
        for field_name, action_type in [
            ("qr_token_entrega", CutoffActionType.ENTREGA_AVISO),
            ("qr_token_corte", CutoffActionType.EXECUCAO_CORTE),
            ("qr_token_reativacao", CutoffActionType.CONFIRMACAO_REATIVACAO),
        ]:
            notice = await CutoffNotice.find_one({field_name: token})
            if notice:
                client = await notice.client.fetch()
                if not client:
                    return None

                # Verifica se acao ja foi realizada
                already_done = False
                if action_type == CutoffActionType.ENTREGA_AVISO and notice.status != CutoffStatus.EM_AVISO:
                    already_done = True
                elif action_type == CutoffActionType.EXECUCAO_CORTE and notice.status != CutoffStatus.PRONTO_PARA_CORTE:
                    already_done = True
                elif action_type == CutoffActionType.CONFIRMACAO_REATIVACAO and notice.fecha_reativacao is not None:
                    already_done = True

                return {
                    "notice_id": str(notice.id),
                    "action_type": action_type.value,
                    "already_done": already_done,
                    "client_nombre": client.nombre_completo,
                    "client_ci_ruc": client.ci_ruc,
                    "client_direccion": client.direccion,
                    "client_manzana": client.manzana,
                    "client_lote": client.lote,
                    "status": notice.status.value,
                    "divida_original": str(notice.divida_original),
                }

        return None
