"""
Testes do workflow de corte.
"""

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.cutoff import CutoffNotice, CutoffStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.finance import CashTransaction, TransactionCategory
from app.models.settings import SystemSettings
from app.services.cutoff_service import CutoffService


# ==================== FIXTURES ====================

@pytest_asyncio.fixture
async def settings(test_db) -> SystemSettings:
    """Configuracoes com parametros de corte."""
    s = SystemSettings(
        nombre_junta="Junta Test",
        tarifa_base=Decimal("25000"),
        consumo_minimo=15,
        valor_excedente_m3=Decimal("1500"),
        meses_atraso_corte=3,
        dias_prazo_aviso=15,
        taxa_reativacao=Decimal("50000"),
        dias_vencimiento=15,
    )
    await s.insert()
    return s


@pytest_asyncio.fixture
async def debtor_client(test_db) -> Client:
    """Cliente com dividas antigas (>3 meses)."""
    client = Client(
        nombre_completo="Carlos Devedor",
        ci_ruc="9876543",
        direccion="Calle Deuda 456",
        manzana="B",
        lote="5",
        numero_medidor="MED-DEBT-001",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await client.insert()
    return client


@pytest_asyncio.fixture
async def old_invoices(test_db, debtor_client) -> list[Invoice]:
    """Faturas com mais de 3 meses de atraso."""
    invoices = []
    # Faturas de 6, 5, 4 meses atras
    today = date.today()
    for i in range(3):
        months_ago = 6 - i
        ref_date = today - timedelta(days=months_ago * 30)
        invoice = Invoice(
            client=debtor_client,
            tipo=InvoiceType.CONSUMO,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=ref_date.month,
            ano_referencia=ref_date.year,
            fecha_vencimiento=ref_date,
            consumo=20,
            tarifa_base=Decimal("25000"),
            excedente=Decimal("7500"),
            valor_total=Decimal("32500"),
            saldo_devedor=Decimal("32500"),
        )
        await invoice.insert()
        invoices.append(invoice)
    return invoices


@pytest_asyncio.fixture
async def cutoff_notice_em_lista(test_db, debtor_client, old_invoices, settings) -> CutoffNotice:
    """CutoffNotice no estado EM_LISTA."""
    notice = CutoffNotice(
        client=debtor_client,
        status=CutoffStatus.EM_LISTA,
        divida_original=Decimal("97500"),
        meses_atraso=4,
    )
    await notice.insert()
    return notice


@pytest_asyncio.fixture
async def cutoff_notice_em_aviso(test_db, debtor_client, old_invoices, settings) -> CutoffNotice:
    """CutoffNotice no estado EM_AVISO com QR token."""
    notice = CutoffNotice(
        client=debtor_client,
        status=CutoffStatus.EM_AVISO,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        qr_token_entrega="test_token_entrega_abc123",
        fecha_aviso_gerado=datetime.utcnow(),
    )
    await notice.insert()
    return notice


@pytest_asyncio.fixture
async def cutoff_notice_em_contagem(test_db, debtor_client, old_invoices, settings) -> CutoffNotice:
    """CutoffNotice no estado EM_CONTAGEM com prazo expirado."""
    notice = CutoffNotice(
        client=debtor_client,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_aviso_gerado=datetime.utcnow() - timedelta(days=20),
        fecha_entrega_aviso=datetime.utcnow() - timedelta(days=16),
        aviso_entregue_por="Entregador Teste",
        fecha_limite_pago=date.today() - timedelta(days=1),  # Expirado
    )
    await notice.insert()
    return notice


@pytest_asyncio.fixture
async def cutoff_notice_pronto(test_db, debtor_client, old_invoices, settings) -> CutoffNotice:
    """CutoffNotice no estado PRONTO_PARA_CORTE."""
    notice = CutoffNotice(
        client=debtor_client,
        status=CutoffStatus.PRONTO_PARA_CORTE,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_aviso_gerado=datetime.utcnow() - timedelta(days=30),
        fecha_entrega_aviso=datetime.utcnow() - timedelta(days=25),
        fecha_limite_pago=date.today() - timedelta(days=10),
    )
    await notice.insert()
    return notice


# ==================== TESTES DE CANDIDATOS ====================

@pytest.mark.asyncio
async def test_get_cutoff_candidates(test_db, debtor_client, old_invoices, settings):
    """Testa identificacao de candidatos a corte."""
    candidates = await CutoffService.get_cutoff_candidates()
    assert len(candidates) >= 1
    found = [c for c in candidates if c.client_id == debtor_client.id]
    assert len(found) == 1
    assert found[0].nombre_completo == "Carlos Devedor"
    assert found[0].divida_total == Decimal("97500")


@pytest.mark.asyncio
async def test_candidate_excluded_if_already_in_workflow(
    test_db, debtor_client, old_invoices, settings, cutoff_notice_em_lista
):
    """Cliente ja no workflow nao aparece como candidato."""
    candidates = await CutoffService.get_cutoff_candidates()
    found = [c for c in candidates if c.client_id == debtor_client.id]
    assert len(found) == 0


# ==================== TESTES DE ADICAO A LISTA ====================

@pytest.mark.asyncio
async def test_add_to_list(test_db, debtor_client, old_invoices, settings):
    """Testa adicao de cliente a lista de corte."""
    result = await CutoffService.add_to_list(debtor_client.id)
    assert result.success is True
    assert result.cutoff_notice_id is not None

    notice = await CutoffNotice.get(result.cutoff_notice_id)
    assert notice.status == CutoffStatus.EM_LISTA
    assert notice.divida_original == Decimal("97500")


@pytest.mark.asyncio
async def test_add_to_list_duplicate_rejected(test_db, debtor_client, old_invoices, settings):
    """Nao permite duplicata no workflow."""
    result1 = await CutoffService.add_to_list(debtor_client.id)
    assert result1.success is True

    result2 = await CutoffService.add_to_list(debtor_client.id)
    assert result2.success is False
    assert "ja possui aviso ativo" in result2.error


@pytest.mark.asyncio
async def test_add_to_list_no_debt(test_db, settings):
    """Cliente sem divida nao pode entrar no workflow."""
    client = Client(
        nombre_completo="Sem Divida",
        ci_ruc="1111111",
        direccion="Calle OK",
        manzana="A",
        lote="1",
        numero_medidor="MED-OK-001",
        status=ClientStatus.ATIVO,
    )
    await client.insert()

    result = await CutoffService.add_to_list(client.id)
    assert result.success is False
    assert "nao possui divida" in result.error


# ==================== TESTES DE TRANSICAO: GENERATE ====================

@pytest.mark.asyncio
async def test_generate_notice(test_db, cutoff_notice_em_lista):
    """Testa geracao de aviso (EM_LISTA -> EM_AVISO)."""
    result = await CutoffService.generate_notice(cutoff_notice_em_lista.id)
    assert result.success is True
    assert result.qr_token is not None
    assert len(result.qr_token) == 32

    notice = await CutoffNotice.get(cutoff_notice_em_lista.id)
    assert notice.status == CutoffStatus.EM_AVISO
    assert notice.qr_token_entrega == result.qr_token
    assert notice.fecha_aviso_gerado is not None


@pytest.mark.asyncio
async def test_generate_notice_wrong_status(test_db, cutoff_notice_em_aviso):
    """Nao pode gerar aviso se nao esta EM_LISTA."""
    result = await CutoffService.generate_notice(cutoff_notice_em_aviso.id)
    assert result.success is False


# ==================== TESTES DE ENTREGA (COUNTDOWN) ====================

@pytest.mark.asyncio
async def test_register_delivery_manual(test_db, cutoff_notice_em_aviso, settings):
    """Testa registro de entrega manual (EM_AVISO -> EM_CONTAGEM)."""
    result = await CutoffService.register_delivery_manual(
        cutoff_notice_em_aviso.id,
        entregue_por="Joao Entregador",
    )
    assert result.success is True

    notice = await CutoffNotice.get(cutoff_notice_em_aviso.id)
    assert notice.status == CutoffStatus.EM_CONTAGEM
    assert notice.aviso_entregue_por == "Joao Entregador"
    assert notice.fecha_limite_pago == date.today() + timedelta(days=15)


@pytest.mark.asyncio
async def test_confirm_delivery_by_qr(test_db, cutoff_notice_em_aviso, settings):
    """Testa confirmacao de entrega via QR."""
    result = await CutoffService.confirm_delivery_by_qr(
        "test_token_entrega_abc123",
        "Pedro Entregador",
        "Entregue em maos",
    )
    assert result.success is True

    notice = await CutoffNotice.get(cutoff_notice_em_aviso.id)
    assert notice.status == CutoffStatus.EM_CONTAGEM
    assert notice.aviso_entregue_por == "Pedro Entregador"


@pytest.mark.asyncio
async def test_confirm_delivery_invalid_token(test_db):
    """Token QR invalido retorna erro."""
    result = await CutoffService.confirm_delivery_by_qr(
        "token_inexistente",
        "Alguem",
    )
    assert result.success is False
    assert "Token invalido" in result.error


# ==================== TESTES DE MARK READY ====================

@pytest.mark.asyncio
async def test_mark_ready_for_cutoff(test_db, cutoff_notice_em_contagem):
    """Testa marcacao como pronto (EM_CONTAGEM -> PRONTO_PARA_CORTE)."""
    result = await CutoffService.mark_ready_for_cutoff(cutoff_notice_em_contagem.id)
    assert result.success is True

    notice = await CutoffNotice.get(cutoff_notice_em_contagem.id)
    assert notice.status == CutoffStatus.PRONTO_PARA_CORTE


@pytest.mark.asyncio
async def test_mark_ready_countdown_not_expired(test_db, debtor_client, old_invoices, settings):
    """Nao pode marcar pronto se countdown nao expirou."""
    notice = CutoffNotice(
        client=debtor_client,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() + timedelta(days=5),  # Ainda ativo
    )
    await notice.insert()

    result = await CutoffService.mark_ready_for_cutoff(notice.id)
    assert result.success is False
    assert "Countdown ativo" in result.error


# ==================== TESTES DE CORTE ====================

@pytest.mark.asyncio
async def test_generate_cutoff_order(test_db, cutoff_notice_pronto):
    """Testa geracao de ordem de corte + QR token."""
    result = await CutoffService.generate_cutoff_order(cutoff_notice_pronto.id)
    assert result.success is True
    assert result.qr_token is not None
    assert len(result.qr_token) == 32

    notice = await CutoffNotice.get(cutoff_notice_pronto.id)
    assert notice.qr_token_corte == result.qr_token


@pytest.mark.asyncio
async def test_execute_cutoff_manual(test_db, cutoff_notice_pronto, debtor_client):
    """Testa execucao de corte manual (PRONTO -> CORTADO)."""
    result = await CutoffService.execute_cutoff_manual(
        cutoff_notice_pronto.id,
        cortado_por="Tecnico Jose",
        observacion="Corte realizado",
    )
    assert result.success is True

    notice = await CutoffNotice.get(cutoff_notice_pronto.id)
    assert notice.status == CutoffStatus.CORTADO
    assert notice.cortado_por == "Tecnico Jose"
    assert notice.fecha_corte is not None

    client = await Client.get(debtor_client.id)
    assert client.status == ClientStatus.CORTADO


@pytest.mark.asyncio
async def test_confirm_cutoff_by_qr(test_db, cutoff_notice_pronto, debtor_client):
    """Testa confirmacao de corte via QR."""
    # Primeiro gera o token
    gen_result = await CutoffService.generate_cutoff_order(cutoff_notice_pronto.id)
    assert gen_result.success is True

    result = await CutoffService.confirm_cutoff_by_qr(
        gen_result.qr_token,
        "Tecnico QR",
        "Cortado via scan",
    )
    assert result.success is True

    client = await Client.get(debtor_client.id)
    assert client.status == ClientStatus.CORTADO


# ==================== TESTES DE AUTO-EXIT ====================

@pytest.mark.asyncio
async def test_auto_exit_on_full_payment(test_db, debtor_client, old_invoices, settings):
    """Testa saida automatica quando cliente paga toda divida."""
    # Adiciona ao workflow
    add_result = await CutoffService.add_to_list(debtor_client.id)
    assert add_result.success is True

    # Simula pagamento de todas faturas
    for inv in old_invoices:
        await inv.update({"$set": {
            "saldo_devedor": Decimal("0"),
            "status": InvoiceStatus.PAGADA.value,
        }})

    # Verifica auto-exit
    exited = await CutoffService.check_auto_exit_for_client(debtor_client.id)
    assert exited is True

    notice = await CutoffNotice.get(add_result.cutoff_notice_id)
    assert notice.saiu_por_pagamento is True
    assert notice.fecha_saida is not None


@pytest.mark.asyncio
async def test_no_auto_exit_if_still_has_debt(test_db, debtor_client, old_invoices, settings):
    """Nao sai se ainda tem divida."""
    add_result = await CutoffService.add_to_list(debtor_client.id)
    assert add_result.success is True

    # Paga apenas 1 fatura
    await old_invoices[0].update({"$set": {
        "saldo_devedor": Decimal("0"),
        "status": InvoiceStatus.PAGADA.value,
    }})

    exited = await CutoffService.check_auto_exit_for_client(debtor_client.id)
    assert exited is False


@pytest.mark.asyncio
async def test_no_auto_exit_if_cortado(test_db, cutoff_notice_pronto, debtor_client, old_invoices):
    """Nao faz auto-exit se ja CORTADO."""
    # Executa corte
    await CutoffService.execute_cutoff_manual(cutoff_notice_pronto.id, cortado_por="Teste")

    # Paga tudo
    for inv in old_invoices:
        await inv.update({"$set": {
            "saldo_devedor": Decimal("0"),
            "status": InvoiceStatus.PAGADA.value,
        }})

    # CORTADO nao sai por auto-exit (precisa reativacao)
    exited = await CutoffService.check_auto_exit_for_client(debtor_client.id)
    assert exited is False


# ==================== TESTES DE REATIVACAO ====================

@pytest.mark.asyncio
async def test_request_reactivation(test_db, cutoff_notice_pronto, debtor_client, old_invoices, settings):
    """Testa solicitacao de reativacao."""
    # Executa corte primeiro
    await CutoffService.execute_cutoff_manual(cutoff_notice_pronto.id, cortado_por="Teste")

    # Divida: 97500 + taxa: 50000 = 147500
    result = await CutoffService.request_reactivation(
        debtor_client.id,
        valor_pago=Decimal("147500"),
        registrado_por="Operador Teste",
    )
    assert result.success is True
    assert result.qr_token is not None

    # Verifica CashTransaction criada
    tx = await CashTransaction.find_one(
        CashTransaction.categoria == TransactionCategory.TAXA_REATIVACAO
    )
    assert tx is not None
    assert tx.valor == Decimal("50000")

    notice = await CutoffNotice.get(cutoff_notice_pronto.id)
    assert notice.reativacao_solicitada is True
    assert notice.taxa_reativacao_paga is True
    assert notice.qr_token_reativacao is not None


@pytest.mark.asyncio
async def test_request_reactivation_insufficient_value(
    test_db, cutoff_notice_pronto, debtor_client, old_invoices, settings
):
    """Reativacao falha se valor insuficiente."""
    await CutoffService.execute_cutoff_manual(cutoff_notice_pronto.id, cortado_por="Teste")

    result = await CutoffService.request_reactivation(
        debtor_client.id,
        valor_pago=Decimal("50000"),  # Insuficiente
    )
    assert result.success is False
    assert "Valor insuficiente" in result.error


@pytest.mark.asyncio
async def test_confirm_reactivation_manual(
    test_db, cutoff_notice_pronto, debtor_client, old_invoices, settings
):
    """Testa confirmacao de reativacao manual."""
    await CutoffService.execute_cutoff_manual(cutoff_notice_pronto.id, cortado_por="Teste")
    await CutoffService.request_reactivation(
        debtor_client.id, valor_pago=Decimal("147500"), registrado_por="Op",
    )

    result = await CutoffService.confirm_reactivation_manual(
        cutoff_notice_pronto.id, confirmado_por="Tecnico Maria",
    )
    assert result.success is True

    client = await Client.get(debtor_client.id)
    assert client.status == ClientStatus.ATIVO

    notice = await CutoffNotice.get(cutoff_notice_pronto.id)
    assert notice.fecha_reativacao is not None
    assert notice.reativacao_confirmada_por == "Tecnico Maria"


@pytest.mark.asyncio
async def test_confirm_reactivation_by_qr(
    test_db, cutoff_notice_pronto, debtor_client, old_invoices, settings
):
    """Testa confirmacao de reativacao via QR."""
    await CutoffService.execute_cutoff_manual(cutoff_notice_pronto.id, cortado_por="Teste")
    req_result = await CutoffService.request_reactivation(
        debtor_client.id, valor_pago=Decimal("147500"), registrado_por="Op",
    )

    result = await CutoffService.confirm_reactivation_by_qr(
        req_result.qr_token, "Tecnico QR",
    )
    assert result.success is True

    client = await Client.get(debtor_client.id)
    assert client.status == ClientStatus.ATIVO


# ==================== TESTES BATCH ====================

@pytest.mark.asyncio
async def test_process_expired_countdowns(test_db, cutoff_notice_em_contagem, settings):
    """Testa processamento batch de countdowns expirados."""
    count = await CutoffService.process_expired_countdowns()
    assert count == 1

    notice = await CutoffNotice.get(cutoff_notice_em_contagem.id)
    assert notice.status == CutoffStatus.PRONTO_PARA_CORTE


# ==================== TESTES QR INFO ====================

@pytest.mark.asyncio
async def test_get_qr_info(test_db, cutoff_notice_em_aviso):
    """Testa busca de info por QR token."""
    info = await CutoffService.get_qr_info("test_token_entrega_abc123")
    assert info is not None
    assert info["action_type"] == "ENTREGA_AVISO"
    assert info["client_nombre"] == "Carlos Devedor"
    assert info["already_done"] is False


@pytest.mark.asyncio
async def test_get_qr_info_invalid_token(test_db):
    """Token invalido retorna None."""
    info = await CutoffService.get_qr_info("token_nao_existe")
    assert info is None
