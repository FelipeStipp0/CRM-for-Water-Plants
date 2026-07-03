"""
Testes das regras de negócio temporais do sistema de corte.

Valida as perguntas reais do dia a dia:
- Depois de X meses de atraso, o cliente vira candidato?
- Se pagar antes do corte, sai do workflow automaticamente?
- O countdown de aviso funciona corretamente?
- O parametro meses_atraso_corte é respeitado quando alterado?
- Cliente INATIVO ou ja CORTADO nao aparece como candidato?
- Fatura ANULADA nao conta para o atraso?
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta
from decimal import Decimal

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.cutoff import CutoffNotice, CutoffStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.settings import SystemSettings
from app.services.cutoff_service import CutoffService


# ==================== HELPERS ====================

def invoice_vencida_ha(client, meses: int, **kwargs) -> Invoice:
    """Cria fatura com vencimento exatamente N meses atras."""
    today = date.today()
    ano = today.year
    mes = today.month - meses
    while mes <= 0:
        mes += 12
        ano -= 1
    venc = date(ano, mes, today.day if today.day <= 28 else 28)
    return Invoice(
        client=client,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=venc.month,
        ano_referencia=venc.year,
        fecha_vencimiento=venc,
        consumo=20,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("7500"),
        valor_total=Decimal("32500"),
        saldo_devedor=kwargs.get("saldo_devedor", Decimal("32500")),
    )


async def make_settings(meses_atraso=3, dias_aviso=15, taxa_reativacao=Decimal("50000")) -> SystemSettings:
    s = SystemSettings(
        nombre_junta="Junta Test",
        tarifa_base=Decimal("25000"),
        consumo_minimo=15,
        valor_excedente_m3=Decimal("1500"),
        meses_atraso_corte=meses_atraso,
        dias_prazo_aviso=dias_aviso,
        taxa_reativacao=taxa_reativacao,
        dias_vencimiento=15,
    )
    await s.insert()
    return s


async def make_client(ci="9000001", manzana="A", lote="1", status=ClientStatus.ATIVO) -> Client:
    c = Client(
        nombre_completo=f"Cliente {ci}",
        ci_ruc=ci,
        direccion="Rua Teste",
        manzana=manzana,
        lote=lote,
        numero_medidor=f"MED-{ci}",
        categoria=ClientCategory.RESIDENCIAL,
        status=status,
    )
    await c.insert()
    return c


# ==================== REGRA: X MESES DE ATRASO ====================

@pytest.mark.asyncio
async def test_cliente_com_exato_limiar_vira_candidato(test_db):
    """Cliente com fatura vencida ha exatamente meses_atraso_corte meses vira candidato."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100001")

    inv = invoice_vencida_ha(client, meses=3)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id in ids


@pytest.mark.asyncio
async def test_cliente_abaixo_do_limiar_nao_e_candidato(test_db):
    """Cliente com fatura vencida ha menos de meses_atraso_corte nao e candidato."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100002")

    inv = invoice_vencida_ha(client, meses=2)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_cliente_bem_acima_do_limiar_e_candidato(test_db):
    """Cliente com 6 meses de atraso (limiar=3) e candidato."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100003")

    inv = invoice_vencida_ha(client, meses=6)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id in ids


@pytest.mark.asyncio
async def test_meses_atraso_configuravel_2_meses(test_db):
    """Com limiar de 2 meses, cliente com 2 meses vira candidato."""
    await make_settings(meses_atraso=2)
    client = await make_client("9100004")

    inv = invoice_vencida_ha(client, meses=2)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id in ids


@pytest.mark.asyncio
async def test_meses_atraso_configuravel_2_meses_abaixo(test_db):
    """Com limiar de 2 meses, cliente com 1 mes nao e candidato."""
    await make_settings(meses_atraso=2)
    client = await make_client("9100005")

    inv = invoice_vencida_ha(client, meses=1)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_limiar_calculado_pela_fatura_mais_antiga(test_db):
    """O atraso e calculado a partir da fatura MAIS ANTIGA, nao da mais recente."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100006")

    # Fatura antiga (4 meses) e fatura recente (1 mes)
    antiga = invoice_vencida_ha(client, meses=4)
    await antiga.insert()
    recente = invoice_vencida_ha(client, meses=1)
    await recente.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    found = [c for c in candidates if c.client_id == client.id]
    assert len(found) == 1
    assert found[0].meses_atraso >= 4


@pytest.mark.asyncio
async def test_cliente_sem_faturas_nao_e_candidato(test_db):
    """Cliente sem nenhuma fatura pendente nao e candidato."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100007")

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_cliente_com_divida_zerada_nao_e_candidato(test_db):
    """Cliente com fatura antiga mas saldo zerado nao e candidato."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100008")

    inv = invoice_vencida_ha(client, meses=5, saldo_devedor=Decimal("0"))
    inv.status = InvoiceStatus.PAGADA
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_fatura_anulada_nao_conta_para_atraso(test_db):
    """Fatura ANULADA nao conta para o calculo de atraso."""
    await make_settings(meses_atraso=3)
    client = await make_client("9100009")

    # Fatura antiga anulada — nao deve contar
    inv_anulada = invoice_vencida_ha(client, meses=5)
    inv_anulada.status = InvoiceStatus.ANULADA
    inv_anulada.saldo_devedor = Decimal("0")
    await inv_anulada.insert()

    # Fatura recente valida mas abaixo do limiar
    inv_recente = invoice_vencida_ha(client, meses=1)
    await inv_recente.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


# ==================== REGRA: STATUS DO CLIENTE ====================

@pytest.mark.asyncio
async def test_cliente_inativo_nao_e_candidato(test_db):
    """Cliente INATIVO nao aparece como candidato, mesmo com divida antiga."""
    await make_settings(meses_atraso=3)
    client = await make_client("9200001", status=ClientStatus.INATIVO)

    inv = invoice_vencida_ha(client, meses=5)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_cliente_ja_cortado_nao_e_candidato(test_db):
    """Cliente ja CORTADO nao aparece como candidato novamente."""
    await make_settings(meses_atraso=3)
    client = await make_client("9200002", status=ClientStatus.CORTADO)

    inv = invoice_vencida_ha(client, meses=5)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


# ==================== REGRA: JA NO WORKFLOW ====================

@pytest.mark.asyncio
async def test_cliente_em_lista_nao_e_candidato(test_db):
    """Cliente ja EM_LISTA nao aparece nos candidatos."""
    await make_settings(meses_atraso=3)
    client = await make_client("9300001")

    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    # Adiciona ao workflow
    result = await CutoffService.add_to_list(client.id)
    assert result.success is True

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_cliente_em_contagem_nao_e_candidato(test_db):
    """Cliente ja EM_CONTAGEM nao aparece nos candidatos."""
    await make_settings(meses_atraso=3)
    client = await make_client("9300002")

    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() + timedelta(days=10),
    )
    await notice.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id not in ids


@pytest.mark.asyncio
async def test_cliente_que_saiu_por_pagamento_volta_a_ser_candidato_se_atrasar(test_db):
    """
    Cliente que saiu do workflow por pagamento mas voltou a atrasar
    deve reaparecer como candidato (aviso antigo tem saiu_por_pagamento=True).
    """
    await make_settings(meses_atraso=3)
    client = await make_client("9300003")

    # Aviso antigo marcado como saido por pagamento
    old_notice = CutoffNotice(
        client=client,
        status=CutoffStatus.EM_LISTA,
        divida_original=Decimal("32500"),
        meses_atraso=3,
        saiu_por_pagamento=True,
    )
    await old_notice.insert()

    # Nova divida
    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    ids = [c.client_id for c in candidates]
    assert client.id in ids


# ==================== REGRA: COUNTDOWN DO AVISO ====================

@pytest.mark.asyncio
async def test_countdown_calculado_a_partir_de_dias_prazo_aviso(test_db):
    """fecha_limite_pago = data da entrega + dias_prazo_aviso."""
    settings = await make_settings(dias_aviso=15)
    client = await make_client("9400001")
    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.EM_AVISO,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        qr_token_entrega="tok_test_countdown_001",
    )
    await notice.insert()

    result = await CutoffService.register_delivery_manual(notice.id, entregue_por="Entregador")
    assert result.success is True

    updated = await CutoffNotice.get(notice.id)
    expected_limit = date.today() + timedelta(days=15)
    assert updated.fecha_limite_pago == expected_limit


@pytest.mark.asyncio
async def test_countdown_configuravel_30_dias(test_db):
    """Com dias_prazo_aviso=30, prazo e 30 dias."""
    await make_settings(dias_aviso=30)
    client = await make_client("9400002")
    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.EM_AVISO,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        qr_token_entrega="tok_test_countdown_002",
    )
    await notice.insert()

    await CutoffService.register_delivery_manual(notice.id, entregue_por="Entregador")
    updated = await CutoffNotice.get(notice.id)
    assert updated.fecha_limite_pago == date.today() + timedelta(days=30)


@pytest.mark.asyncio
async def test_nao_pode_marcar_pronto_com_countdown_ativo(test_db):
    """Nao avanca para PRONTO_PARA_CORTE se o prazo nao expirou."""
    await make_settings(dias_aviso=15)
    client = await make_client("9400003")
    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() + timedelta(days=5),  # Ainda ativo
    )
    await notice.insert()

    result = await CutoffService.mark_ready_for_cutoff(notice.id)
    assert result.success is False


@pytest.mark.asyncio
async def test_pode_marcar_pronto_com_countdown_expirado(test_db):
    """Avanca para PRONTO_PARA_CORTE quando o prazo expirou."""
    await make_settings(dias_aviso=15)
    client = await make_client("9400004")
    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() - timedelta(days=1),  # Expirado
    )
    await notice.insert()

    result = await CutoffService.mark_ready_for_cutoff(notice.id)
    assert result.success is True

    updated = await CutoffNotice.get(notice.id)
    assert updated.status == CutoffStatus.PRONTO_PARA_CORTE


@pytest.mark.asyncio
async def test_batch_so_avanca_expirados(test_db):
    """process_expired_countdowns so avanca avisos com prazo vencido."""
    await make_settings(dias_aviso=15)
    client_a = await make_client("9400005")
    client_b = await make_client("9400006")

    for c in [client_a, client_b]:
        inv = invoice_vencida_ha(c, meses=4)
        await inv.insert()

    notice_expirado = CutoffNotice(
        client=client_a,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() - timedelta(days=1),
    )
    await notice_expirado.insert()

    notice_ativo = CutoffNotice(
        client=client_b,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("32500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() + timedelta(days=5),
    )
    await notice_ativo.insert()

    count = await CutoffService.process_expired_countdowns()
    assert count == 1

    assert (await CutoffNotice.get(notice_expirado.id)).status == CutoffStatus.PRONTO_PARA_CORTE
    assert (await CutoffNotice.get(notice_ativo.id)).status == CutoffStatus.EM_CONTAGEM


# ==================== REGRA: AUTO-EXIT POR PAGAMENTO ====================

@pytest.mark.asyncio
async def test_pagamento_total_antes_do_corte_remove_do_workflow(test_db):
    """
    Cliente paga toda a divida enquanto ainda esta EM_CONTAGEM
    — deve sair do workflow sem precisar de corte.
    """
    await make_settings(meses_atraso=3)
    client = await make_client("9500001")

    inv = invoice_vencida_ha(client, meses=4)
    await inv.insert()

    # Entra no workflow
    add_result = await CutoffService.add_to_list(client.id)
    assert add_result.success is True

    # Paga tudo
    await inv.update({"$set": {
        "saldo_devedor": Decimal("0"),
        "status": InvoiceStatus.PAGADA.value,
    }})

    exited = await CutoffService.check_auto_exit_for_client(client.id)
    assert exited is True

    notice = await CutoffNotice.get(add_result.cutoff_notice_id)
    assert notice.saiu_por_pagamento is True
    assert notice.fecha_saida is not None


@pytest.mark.asyncio
async def test_pagamento_parcial_nao_remove_do_workflow(test_db):
    """Pagamento parcial nao remove o cliente do workflow."""
    await make_settings(meses_atraso=3)
    client = await make_client("9500002")

    inv1 = invoice_vencida_ha(client, meses=5)
    await inv1.insert()
    inv2 = invoice_vencida_ha(client, meses=4)
    await inv2.insert()

    add_result = await CutoffService.add_to_list(client.id)
    assert add_result.success is True

    # Paga apenas 1 das 2 faturas
    await inv1.update({"$set": {
        "saldo_devedor": Decimal("0"),
        "status": InvoiceStatus.PAGADA.value,
    }})

    exited = await CutoffService.check_auto_exit_for_client(client.id)
    assert exited is False

    notice = await CutoffNotice.get(add_result.cutoff_notice_id)
    assert notice.saiu_por_pagamento is False


@pytest.mark.asyncio
async def test_auto_exit_nao_ocorre_se_ja_cortado(test_db):
    """
    Cliente ja CORTADO nao sai por pagamento — precisa solicitar reativacao.
    Isso garante que o tecnico vai fisicamente religar o servico.
    """
    await make_settings(meses_atraso=3)
    client = await make_client("9500003")

    inv = invoice_vencida_ha(client, meses=5)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.CORTADO,
        divida_original=Decimal("32500"),
        meses_atraso=4,
    )
    await notice.insert()
    await client.update({"$set": {"status": ClientStatus.CORTADO.value}})

    # Paga tudo
    await inv.update({"$set": {
        "saldo_devedor": Decimal("0"),
        "status": InvoiceStatus.PAGADA.value,
    }})

    # Auto-exit nao deve ocorrer — precisa de reativacao
    exited = await CutoffService.check_auto_exit_for_client(client.id)
    assert exited is False

    updated_client = await Client.get(client.id)
    assert updated_client.status == ClientStatus.CORTADO


# ==================== REGRA: TAXA DE REATIVACAO ====================

@pytest.mark.asyncio
async def test_reativacao_exige_divida_mais_taxa(test_db):
    """
    Reativacao exige valor_pago >= divida_atual + taxa_reativacao.
    Testa com diferentes combinacoes de divida e taxa.
    """
    taxa = Decimal("50000")
    await make_settings(meses_atraso=3, taxa_reativacao=taxa)
    client = await make_client("9600001")

    inv = invoice_vencida_ha(client, meses=5)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.CORTADO,
        divida_original=Decimal("32500"),
        meses_atraso=4,
    )
    await notice.insert()
    await client.update({"$set": {"status": ClientStatus.CORTADO.value}})

    divida = Decimal("32500")
    minimo = divida + taxa  # 82500

    # Exatamente o minimo: deve funcionar
    result_ok = await CutoffService.request_reactivation(
        client.id, valor_pago=minimo, registrado_por="Op"
    )
    assert result_ok.success is True


@pytest.mark.asyncio
async def test_reativacao_falha_com_um_centavo_a_menos(test_db):
    """Um centavo abaixo do minimo rejeita a reativacao."""
    taxa = Decimal("50000")
    await make_settings(meses_atraso=3, taxa_reativacao=taxa)
    client = await make_client("9600002")

    inv = invoice_vencida_ha(client, meses=5)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.CORTADO,
        divida_original=Decimal("32500"),
        meses_atraso=4,
    )
    await notice.insert()
    await client.update({"$set": {"status": ClientStatus.CORTADO.value}})

    divida = Decimal("32500")
    insuficiente = divida + taxa - Decimal("1")  # 82499

    result = await CutoffService.request_reactivation(
        client.id, valor_pago=insuficiente
    )
    assert result.success is False
    assert "Valor insuficiente" in result.error


@pytest.mark.asyncio
async def test_taxa_reativacao_configuravel(test_db):
    """Taxa de reativacao configuravel e usada corretamente."""
    taxa_alta = Decimal("100000")
    await make_settings(meses_atraso=3, taxa_reativacao=taxa_alta)
    client = await make_client("9600003")

    inv = invoice_vencida_ha(client, meses=5)
    await inv.insert()

    notice = CutoffNotice(
        client=client,
        status=CutoffStatus.CORTADO,
        divida_original=Decimal("32500"),
        meses_atraso=4,
    )
    await notice.insert()
    await client.update({"$set": {"status": ClientStatus.CORTADO.value}})

    # Com taxa anterior (50000) nao seria suficiente, mas taxa agora e 100000
    result_insuficiente = await CutoffService.request_reactivation(
        client.id, valor_pago=Decimal("82500")  # divida + 50000
    )
    assert result_insuficiente.success is False

    result_ok = await CutoffService.request_reactivation(
        client.id, valor_pago=Decimal("132500")  # divida + 100000
    )
    assert result_ok.success is True


# ==================== REGRA: DIVIDA REFLETIDA NO MOMENTO CERTO ====================

@pytest.mark.asyncio
async def test_divida_original_snapshot_no_momento_de_entrada(test_db):
    """
    divida_original e um snapshot do momento em que o cliente entrou no workflow.
    Novas faturas geradas depois nao alteram esse valor.
    """
    await make_settings(meses_atraso=3)
    client = await make_client("9700001")

    inv1 = invoice_vencida_ha(client, meses=4)
    await inv1.insert()

    # Entra no workflow com divida de 32500
    add_result = await CutoffService.add_to_list(client.id)
    assert add_result.success is True

    notice = await CutoffNotice.get(add_result.cutoff_notice_id)
    assert notice.divida_original == Decimal("32500")

    # Nova fatura gerada depois (nao altera divida_original)
    inv2 = invoice_vencida_ha(client, meses=3)
    await inv2.insert()

    notice_atual = await CutoffNotice.get(add_result.cutoff_notice_id)
    assert notice_atual.divida_original == Decimal("32500")  # Nao mudou


@pytest.mark.asyncio
async def test_divida_candidato_inclui_todas_faturas_pendentes(test_db):
    """divida_total do candidato soma TODAS as faturas pendentes, nao so a mais antiga."""
    await make_settings(meses_atraso=3)
    client = await make_client("9700002")

    # 3 faturas pendentes
    for meses_atras in [6, 5, 4]:
        inv = invoice_vencida_ha(client, meses=meses_atras)
        await inv.insert()

    candidates = await CutoffService.get_cutoff_candidates()
    found = next(c for c in candidates if c.client_id == client.id)
    assert found.divida_total == Decimal("97500")  # 3 x 32500
