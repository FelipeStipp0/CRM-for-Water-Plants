"""
Testes de integracao para endpoints HTTP do workflow de corte.

Cobre todos os endpoints de /cutoff:
  - GET  /cutoff/candidates
  - POST /cutoff/notices
  - GET  /cutoff/notices
  - GET  /cutoff/notices/ready
  - GET  /cutoff/notices/client/{client_id}
  - GET  /cutoff/notices/{notice_id}
  - POST /cutoff/notices/{notice_id}/generate
  - POST /cutoff/notices/{notice_id}/deliver
  - POST /cutoff/notices/{notice_id}/mark-ready
  - POST /cutoff/notices/{notice_id}/generate-order
  - POST /cutoff/notices/{notice_id}/execute
  - POST /cutoff/reactivation/request
  - POST /cutoff/reactivation/{notice_id}/confirm
  - POST /cutoff/notices/process-expired
  - GET  /cutoff/qr/{token}/info       (publico)
  - POST /cutoff/qr/{token}/confirm    (publico)
"""

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.cutoff import CutoffNotice, CutoffStatus
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.settings import SystemSettings


# ==================== FIXTURES ====================

@pytest_asyncio.fixture
async def cutoff_settings(test_db) -> SystemSettings:
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
async def debtor(test_db) -> Client:
    """Cliente inadimplente."""
    client = Client(
        nombre_completo="Ana Devedora",
        ci_ruc="5551234",
        direccion="Rua da Divida 1",
        manzana="C",
        lote="3",
        numero_medidor="MED-DEBT-API",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await client.insert()
    return client


@pytest_asyncio.fixture
async def old_debts(test_db, debtor) -> list[Invoice]:
    """Tres faturas com mais de 3 meses de atraso."""
    invoices = []
    today = date.today()
    for i in range(3):
        ref = today - timedelta(days=(6 - i) * 30)
        inv = Invoice(
            client=debtor,
            tipo=InvoiceType.CONSUMO,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=ref.month,
            ano_referencia=ref.year,
            fecha_vencimiento=ref,
            consumo=20,
            tarifa_base=Decimal("25000"),
            excedente=Decimal("7500"),
            valor_total=Decimal("32500"),
            saldo_devedor=Decimal("32500"),
        )
        await inv.insert()
        invoices.append(inv)
    return invoices


@pytest_asyncio.fixture
async def notice_em_lista(test_db, debtor, old_debts, cutoff_settings) -> CutoffNotice:
    n = CutoffNotice(
        client=debtor,
        status=CutoffStatus.EM_LISTA,
        divida_original=Decimal("97500"),
        meses_atraso=4,
    )
    await n.insert()
    return n


@pytest_asyncio.fixture
async def notice_em_aviso(test_db, debtor, old_debts, cutoff_settings) -> CutoffNotice:
    n = CutoffNotice(
        client=debtor,
        status=CutoffStatus.EM_AVISO,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        qr_token_entrega="api_test_token_entrega_xyz",
        fecha_aviso_gerado=datetime.utcnow(),
    )
    await n.insert()
    return n


@pytest_asyncio.fixture
async def notice_em_contagem(test_db, debtor, old_debts, cutoff_settings) -> CutoffNotice:
    n = CutoffNotice(
        client=debtor,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_aviso_gerado=datetime.utcnow() - timedelta(days=20),
        fecha_entrega_aviso=datetime.utcnow() - timedelta(days=16),
        aviso_entregue_por="Entregador",
        fecha_limite_pago=date.today() - timedelta(days=1),  # Expirado
    )
    await n.insert()
    return n


@pytest_asyncio.fixture
async def notice_pronto(test_db, debtor, old_debts, cutoff_settings) -> CutoffNotice:
    n = CutoffNotice(
        client=debtor,
        status=CutoffStatus.PRONTO_PARA_CORTE,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_aviso_gerado=datetime.utcnow() - timedelta(days=30),
        fecha_entrega_aviso=datetime.utcnow() - timedelta(days=25),
        fecha_limite_pago=date.today() - timedelta(days=10),
    )
    await n.insert()
    return n


@pytest_asyncio.fixture
async def notice_cortado(test_db, debtor, old_debts, cutoff_settings) -> CutoffNotice:
    n = CutoffNotice(
        client=debtor,
        status=CutoffStatus.CORTADO,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_corte=datetime.utcnow(),
        cortado_por="Tecnico Teste",
    )
    await n.insert()
    # Reflete status no cliente
    await debtor.update({"$set": {"status": ClientStatus.CORTADO.value}})
    return n


# ==================== AUTENTICACAO ====================

@pytest.mark.asyncio
async def test_cutoff_requires_auth(test_client: AsyncClient, test_db):
    """Endpoints de corte exigem autenticacao."""
    response = await test_client.get("/cutoff/candidates")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cutoff_requires_scope(test_client: AsyncClient, test_db):
    """Usuario sem escopo 'cutoff' recebe 403."""
    from app.models.user import User
    from app.utils.security import get_password_hash, create_access_token

    user = User(
        username="noscope",
        email="noscope@test.com",
        hashed_password=get_password_hash("pass123"),
        full_name="No Scope",
        is_superuser=False,
        must_change_password=False,
        scopes=["readings"],
    )
    await user.insert()

    token = create_access_token(data={"sub": user.username})
    headers = {"Authorization": f"Bearer {token}"}

    response = await test_client.get("/cutoff/candidates", headers=headers)
    assert response.status_code == 403


# ==================== CANDIDATOS ====================

@pytest.mark.asyncio
async def test_get_candidates(
    test_client: AsyncClient, auth_headers, debtor, old_debts, cutoff_settings
):
    """Lista candidatos a corte."""
    response = await test_client.get("/cutoff/candidates", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    ids = [c["client_id"] for c in data]
    assert str(debtor.id) in ids


@pytest.mark.asyncio
async def test_candidates_excludes_already_in_workflow(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Cliente ja no workflow nao aparece como candidato."""
    response = await test_client.get("/cutoff/candidates", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    # O debtor ja esta no workflow via notice_em_lista
    notice = await CutoffNotice.get(notice_em_lista.id)
    client = await notice.client.fetch()
    ids = [c["client_id"] for c in data]
    assert str(client.id) not in ids


@pytest.mark.asyncio
async def test_candidates_fields(
    test_client: AsyncClient, auth_headers, debtor, old_debts, cutoff_settings
):
    """Verifica campos retornados para candidato."""
    response = await test_client.get("/cutoff/candidates", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    candidate = next(c for c in data if c["client_id"] == str(debtor.id))
    assert candidate["nombre_completo"] == "Ana Devedora"
    assert Decimal(candidate["divida_total"]) == Decimal("97500")
    assert candidate["meses_atraso"] >= 3
    assert "oldest_invoice_date" in candidate


# ==================== CRIAR AVISO (POST /notices) ====================

@pytest.mark.asyncio
async def test_create_notice(
    test_client: AsyncClient, auth_headers, debtor, old_debts, cutoff_settings
):
    """Adiciona cliente a lista de corte."""
    response = await test_client.post(
        "/cutoff/notices",
        headers=auth_headers,
        json={"client_id": str(debtor.id)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["cutoff_notice_id"] is not None


@pytest.mark.asyncio
async def test_create_notice_duplicate_rejected(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Nao permite duas entradas no workflow para o mesmo cliente."""
    client_obj = await (await CutoffNotice.get(notice_em_lista.id)).client.fetch()
    client_id = str(client_obj.id)
    response = await test_client.post(
        "/cutoff/notices",
        headers=auth_headers,
        json={"client_id": client_id},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_notice_invalid_client_id(test_client: AsyncClient, auth_headers, test_db):
    """ID de cliente invalido retorna 400."""
    response = await test_client.post(
        "/cutoff/notices",
        headers=auth_headers,
        json={"client_id": "nao_e_um_object_id"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_notice_client_without_debt(
    test_client: AsyncClient, auth_headers, test_db, cutoff_settings
):
    """Cliente sem divida nao pode entrar no workflow."""
    client = Client(
        nombre_completo="Sem Divida API",
        ci_ruc="0001112",
        direccion="Rua OK",
        manzana="A",
        lote="9",
        numero_medidor="MED-OK-API",
        status=ClientStatus.ATIVO,
    )
    await client.insert()

    response = await test_client.post(
        "/cutoff/notices",
        headers=auth_headers,
        json={"client_id": str(client.id)},
    )
    assert response.status_code == 400


# ==================== LISTAR AVISOS (GET /notices) ====================

@pytest.mark.asyncio
async def test_list_notices(test_client: AsyncClient, auth_headers, notice_em_lista):
    """Lista avisos de corte."""
    response = await test_client.get("/cutoff/notices", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_notices_filter_by_status(
    test_client: AsyncClient, auth_headers, notice_em_lista, notice_em_aviso
):
    """Filtra avisos por status."""
    response = await test_client.get(
        "/cutoff/notices",
        headers=auth_headers,
        params={"status": "EM_LISTA"},
    )
    assert response.status_code == 200
    data = response.json()
    assert all(n["status"] == "EM_LISTA" for n in data)


@pytest.mark.asyncio
async def test_list_notices_excludes_exited_by_default(
    test_client: AsyncClient, auth_headers, debtor, old_debts, cutoff_settings
):
    """Por padrao, avisos com saiu_por_pagamento=True nao aparecem."""
    exited = CutoffNotice(
        client=debtor,
        status=CutoffStatus.EM_LISTA,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        saiu_por_pagamento=True,
    )
    await exited.insert()

    response = await test_client.get("/cutoff/notices", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    ids = [n["id"] for n in data]
    assert str(exited.id) not in ids


@pytest.mark.asyncio
async def test_list_notices_include_exited(
    test_client: AsyncClient, auth_headers, debtor, old_debts, cutoff_settings
):
    """Com include_exited=true, avisos pagos tambem aparecem."""
    exited = CutoffNotice(
        client=debtor,
        status=CutoffStatus.EM_LISTA,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        saiu_por_pagamento=True,
    )
    await exited.insert()

    response = await test_client.get(
        "/cutoff/notices",
        headers=auth_headers,
        params={"include_exited": "true"},
    )
    assert response.status_code == 200
    data = response.json()
    ids = [n["id"] for n in data]
    assert str(exited.id) in ids


# ==================== AVISOS PRONTOS ====================

@pytest.mark.asyncio
async def test_list_ready_for_cutoff(
    test_client: AsyncClient, auth_headers, notice_pronto
):
    """Lista avisos PRONTO_PARA_CORTE com dados do cliente."""
    response = await test_client.get("/cutoff/notices/ready", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    ids = [n["id"] for n in data]
    assert str(notice_pronto.id) in ids
    # Verifica campos de detalhe do cliente
    entry = next(n for n in data if n["id"] == str(notice_pronto.id))
    assert "client_nombre" in entry
    assert "divida_atual" in entry


@pytest.mark.asyncio
async def test_list_ready_empty_when_none(test_client: AsyncClient, auth_headers, test_db):
    """Retorna lista vazia quando nao ha prontos."""
    response = await test_client.get("/cutoff/notices/ready", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


# ==================== AVISO POR CLIENTE ====================

@pytest.mark.asyncio
async def test_get_client_notice(
    test_client: AsyncClient, auth_headers, debtor, notice_em_lista
):
    """Retorna aviso ativo de um cliente."""
    response = await test_client.get(
        f"/cutoff/notices/client/{debtor.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(notice_em_lista.id)
    assert data["status"] == "EM_LISTA"


@pytest.mark.asyncio
async def test_get_client_notice_not_found(
    test_client: AsyncClient, auth_headers, test_db
):
    """Retorna null quando cliente nao tem aviso ativo."""
    client = Client(
        nombre_completo="Sem Aviso",
        ci_ruc="9990001",
        direccion="Rua X",
        manzana="Z",
        lote="1",
        numero_medidor="MED-NONOTICE",
        status=ClientStatus.ATIVO,
    )
    await client.insert()

    response = await test_client.get(
        f"/cutoff/notices/client/{client.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_get_client_notice_invalid_id(test_client: AsyncClient, auth_headers, test_db):
    """ID invalido retorna 400."""
    response = await test_client.get(
        "/cutoff/notices/client/id_invalido",
        headers=auth_headers,
    )
    assert response.status_code == 400


# ==================== AVISO POR ID ====================

@pytest.mark.asyncio
async def test_get_notice_by_id(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Retorna detalhes completos de um aviso."""
    response = await test_client.get(
        f"/cutoff/notices/{notice_em_lista.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(notice_em_lista.id)
    assert data["status"] == "EM_LISTA"
    assert "client_nombre" in data
    assert "divida_atual" in data


@pytest.mark.asyncio
async def test_get_notice_not_found(test_client: AsyncClient, auth_headers, test_db):
    """ID inexistente retorna 404."""
    response = await test_client.get(
        "/cutoff/notices/507f1f77bcf86cd799439011",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ==================== GERAR AVISO (EM_LISTA -> EM_AVISO) ====================

@pytest.mark.asyncio
async def test_generate_notice(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Gera aviso de corte e retorna QR token (EM_LISTA -> EM_AVISO)."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_lista.id}/generate",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "qr_token" in data
    assert len(data["qr_token"]) == 32
    assert data["action_type"] == "ENTREGA_AVISO"

    # Verifica mudanca de status no banco
    notice = await CutoffNotice.get(notice_em_lista.id)
    assert notice.status == CutoffStatus.EM_AVISO


@pytest.mark.asyncio
async def test_generate_notice_wrong_status(
    test_client: AsyncClient, auth_headers, notice_em_aviso
):
    """Nao pode gerar aviso se ja esta em outro estado."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_aviso.id}/generate",
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_generate_notice_invalid_id(test_client: AsyncClient, auth_headers, test_db):
    """ID invalido retorna 400."""
    response = await test_client.post(
        "/cutoff/notices/id_invalido/generate",
        headers=auth_headers,
    )
    assert response.status_code == 400


# ==================== REGISTRAR ENTREGA (EM_AVISO -> EM_CONTAGEM) ====================

@pytest.mark.asyncio
async def test_register_delivery(
    test_client: AsyncClient, auth_headers, notice_em_aviso, cutoff_settings
):
    """Registra entrega manual do aviso (EM_AVISO -> EM_CONTAGEM)."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_aviso.id}/deliver",
        headers=auth_headers,
        json={"entregue_por": "Joao Cobrador", "observacion": "Entregue pessoalmente"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    notice = await CutoffNotice.get(notice_em_aviso.id)
    assert notice.status == CutoffStatus.EM_CONTAGEM
    assert notice.aviso_entregue_por == "Joao Cobrador"
    assert notice.fecha_limite_pago == date.today() + timedelta(days=15)


@pytest.mark.asyncio
async def test_register_delivery_uses_current_user_name(
    test_client: AsyncClient, auth_headers, notice_em_aviso, cutoff_settings
):
    """Se entregue_por nao informado, usa nome do usuario logado."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_aviso.id}/deliver",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200
    notice = await CutoffNotice.get(notice_em_aviso.id)
    assert notice.aviso_entregue_por is not None


@pytest.mark.asyncio
async def test_register_delivery_wrong_status(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Nao pode registrar entrega se nao esta EM_AVISO."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_lista.id}/deliver",
        headers=auth_headers,
        json={"entregue_por": "Alguem"},
    )
    assert response.status_code == 400


# ==================== MARCAR PRONTO ====================

@pytest.mark.asyncio
async def test_mark_ready(
    test_client: AsyncClient, auth_headers, notice_em_contagem
):
    """Marca como pronto para corte (EM_CONTAGEM -> PRONTO_PARA_CORTE)."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_contagem.id}/mark-ready",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    notice = await CutoffNotice.get(notice_em_contagem.id)
    assert notice.status == CutoffStatus.PRONTO_PARA_CORTE


@pytest.mark.asyncio
async def test_mark_ready_countdown_still_active(
    test_client: AsyncClient, auth_headers, debtor, old_debts, cutoff_settings
):
    """Nao pode marcar pronto se countdown ainda nao expirou."""
    notice = CutoffNotice(
        client=debtor,
        status=CutoffStatus.EM_CONTAGEM,
        divida_original=Decimal("97500"),
        meses_atraso=4,
        fecha_limite_pago=date.today() + timedelta(days=5),
    )
    await notice.insert()

    response = await test_client.post(
        f"/cutoff/notices/{notice.id}/mark-ready",
        headers=auth_headers,
    )
    assert response.status_code == 400


# ==================== GERAR ORDEM DE CORTE ====================

@pytest.mark.asyncio
async def test_generate_cutoff_order(
    test_client: AsyncClient, auth_headers, notice_pronto
):
    """Gera ordem de corte + QR token (PRONTO_PARA_CORTE)."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_pronto.id}/generate-order",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "qr_token" in data
    assert len(data["qr_token"]) == 32
    assert data["action_type"] == "EXECUCAO_CORTE"

    notice = await CutoffNotice.get(notice_pronto.id)
    assert notice.qr_token_corte == data["qr_token"]


@pytest.mark.asyncio
async def test_generate_order_wrong_status(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Nao pode gerar ordem se nao esta PRONTO_PARA_CORTE."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_lista.id}/generate-order",
        headers=auth_headers,
    )
    assert response.status_code == 400


# ==================== EXECUTAR CORTE ====================

@pytest.mark.asyncio
async def test_execute_cutoff(
    test_client: AsyncClient, auth_headers, notice_pronto, debtor
):
    """Executa corte manual (PRONTO_PARA_CORTE -> CORTADO)."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_pronto.id}/execute",
        headers=auth_headers,
        json={
            "cortado_por": "Tecnico API",
            "observacion": "Corte via API",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    notice = await CutoffNotice.get(notice_pronto.id)
    assert notice.status == CutoffStatus.CORTADO
    assert notice.cortado_por == "Tecnico API"
    assert notice.fecha_corte is not None

    client = await Client.get(debtor.id)
    assert client.status == ClientStatus.CORTADO


@pytest.mark.asyncio
async def test_execute_cutoff_with_photo_and_gps(
    test_client: AsyncClient, auth_headers, notice_pronto, debtor
):
    """Executa corte com foto e GPS."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_pronto.id}/execute",
        headers=auth_headers,
        json={
            "foto_url": "https://r2.example.com/foto_corte.jpg",
            "gps_latitude": -25.2867,
            "gps_longitude": -57.6478,
        },
    )
    assert response.status_code == 200

    notice = await CutoffNotice.get(notice_pronto.id)
    assert notice.foto_instalacao_url == "https://r2.example.com/foto_corte.jpg"
    assert notice.gps_corte_latitude == pytest.approx(-25.2867)
    assert notice.gps_corte_longitude == pytest.approx(-57.6478)


@pytest.mark.asyncio
async def test_execute_cutoff_wrong_status(
    test_client: AsyncClient, auth_headers, notice_em_lista
):
    """Nao pode executar corte se nao esta PRONTO_PARA_CORTE."""
    response = await test_client.post(
        f"/cutoff/notices/{notice_em_lista.id}/execute",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 400


# ==================== SOLICITAR REATIVACAO ====================

@pytest.mark.asyncio
async def test_request_reactivation(
    test_client: AsyncClient, auth_headers, notice_cortado, debtor
):
    """Solicita reativacao com pagamento suficiente."""
    # divida: 97500 + taxa: 50000 = 147500
    response = await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={
            "client_id": str(debtor.id),
            "valor_pago": "147500",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "qr_token" in data
    assert data["action_type"] == "CONFIRMACAO_REATIVACAO"


@pytest.mark.asyncio
async def test_request_reactivation_insufficient_value(
    test_client: AsyncClient, auth_headers, notice_cortado, debtor
):
    """Reativacao falha com valor insuficiente."""
    response = await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={
            "client_id": str(debtor.id),
            "valor_pago": "10000",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_request_reactivation_invalid_client(
    test_client: AsyncClient, auth_headers, test_db
):
    """ID de cliente invalido retorna 400."""
    response = await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={"client_id": "id_invalido", "valor_pago": "200000"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_request_reactivation_client_not_cortado(
    test_client: AsyncClient, auth_headers, test_db, cutoff_settings
):
    """Cliente que nao esta CORTADO nao pode solicitar reativacao."""
    client = Client(
        nombre_completo="Cliente Ativo",
        ci_ruc="8881112",
        direccion="Rua Ativa",
        manzana="A",
        lote="2",
        numero_medidor="MED-ATIVO-REQ",
        status=ClientStatus.ATIVO,
    )
    await client.insert()

    response = await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={"client_id": str(client.id), "valor_pago": "200000"},
    )
    assert response.status_code == 400


# ==================== CONFIRMAR REATIVACAO ====================

@pytest.mark.asyncio
async def test_confirm_reactivation(
    test_client: AsyncClient, auth_headers, notice_cortado, debtor
):
    """Confirma reativacao manual (CORTADO -> ATIVO)."""
    # Primeiro solicita reativacao
    req_resp = await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={"client_id": str(debtor.id), "valor_pago": "147500"},
    )
    assert req_resp.status_code == 200

    # Confirma
    response = await test_client.post(
        f"/cutoff/reactivation/{notice_cortado.id}/confirm",
        headers=auth_headers,
        json={"confirmado_por": "Tecnico Reativacao"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    client = await Client.get(debtor.id)
    assert client.status == ClientStatus.ATIVO

    notice = await CutoffNotice.get(notice_cortado.id)
    assert notice.fecha_reativacao is not None
    assert notice.reativacao_confirmada_por == "Tecnico Reativacao"


@pytest.mark.asyncio
async def test_confirm_reactivation_with_photo(
    test_client: AsyncClient, auth_headers, notice_cortado, debtor
):
    """Confirma reativacao com foto e GPS."""
    await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={"client_id": str(debtor.id), "valor_pago": "147500"},
    )

    response = await test_client.post(
        f"/cutoff/reactivation/{notice_cortado.id}/confirm",
        headers=auth_headers,
        json={
            "foto_url": "https://r2.example.com/foto_reativacao.jpg",
            "gps_latitude": -25.2867,
            "gps_longitude": -57.6478,
        },
    )
    assert response.status_code == 200

    notice = await CutoffNotice.get(notice_cortado.id)
    assert notice.foto_reativacao_url == "https://r2.example.com/foto_reativacao.jpg"


@pytest.mark.asyncio
async def test_confirm_reactivation_without_request(
    test_client: AsyncClient, auth_headers, notice_cortado
):
    """Nao pode confirmar sem ter solicitado reativacao primeiro."""
    response = await test_client.post(
        f"/cutoff/reactivation/{notice_cortado.id}/confirm",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 400


# ==================== PROCESSAR COUNTDOWNS EXPIRADOS ====================

@pytest.mark.asyncio
async def test_process_expired_countdowns(
    test_client: AsyncClient, auth_headers, notice_em_contagem
):
    """Processa avisos com countdown expirado em batch."""
    response = await test_client.post(
        "/cutoff/notices/process-expired",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "1" in data["message"]

    notice = await CutoffNotice.get(notice_em_contagem.id)
    assert notice.status == CutoffStatus.PRONTO_PARA_CORTE


@pytest.mark.asyncio
async def test_process_expired_no_notices(test_client: AsyncClient, auth_headers, test_db):
    """Batch sem expirados retorna 0."""
    response = await test_client.post(
        "/cutoff/notices/process-expired",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "0" in data["message"]


# ==================== ENDPOINTS PUBLICOS DE QR ====================

@pytest.mark.asyncio
async def test_qr_info_entrega(test_db, notice_em_aviso):
    """Endpoint publico retorna info do token de entrega."""
    from httpx import AsyncClient as RawClient, ASGITransport
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from app.routers import cutoff as cutoff_router

    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(cutoff_router.qr_router, prefix="/cutoff")

    transport = ASGITransport(app=app)
    async with RawClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/cutoff/qr/api_test_token_entrega_xyz/info")

    assert response.status_code == 200
    data = response.json()
    assert data["action_type"] == "ENTREGA_AVISO"
    assert data["already_done"] is False
    assert data["client_nombre"] == "Ana Devedora"


@pytest.mark.asyncio
async def test_qr_info_invalid_token(test_client: AsyncClient, test_db):
    """Token invalido retorna 404 no endpoint publico."""
    response = await test_client.get("/cutoff/qr/token_inexistente_xpto/info")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_qr_confirm_entrega(
    test_client: AsyncClient, notice_em_aviso, cutoff_settings
):
    """Confirma entrega via QR sem autenticacao."""
    response = await test_client.post(
        "/cutoff/qr/api_test_token_entrega_xyz/confirm",
        json={"nome_responsavel": "Campo Worker"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    notice = await CutoffNotice.get(notice_em_aviso.id)
    assert notice.status == CutoffStatus.EM_CONTAGEM
    assert notice.aviso_entregue_por == "Campo Worker"


@pytest.mark.asyncio
async def test_qr_confirm_already_done(
    test_client: AsyncClient, notice_em_aviso, cutoff_settings
):
    """Confirmar QR ja utilizado retorna 400."""
    # Primeiro uso
    await test_client.post(
        "/cutoff/qr/api_test_token_entrega_xyz/confirm",
        json={"nome_responsavel": "Worker 1"},
    )
    # Segundo uso do mesmo token
    response = await test_client.post(
        "/cutoff/qr/api_test_token_entrega_xyz/confirm",
        json={"nome_responsavel": "Worker 2"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_qr_confirm_corte(
    test_client: AsyncClient, notice_pronto, debtor
):
    """Confirma corte via QR apos gerar ordem."""
    # Gera o token de corte primeiro (precisa de auth)
    from app.services.cutoff_service import CutoffService
    gen_result = await CutoffService.generate_cutoff_order(notice_pronto.id)
    assert gen_result.success is True

    response = await test_client.post(
        f"/cutoff/qr/{gen_result.qr_token}/confirm",
        json={"nome_responsavel": "Tecnico Campo"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    client = await Client.get(debtor.id)
    assert client.status == ClientStatus.CORTADO


@pytest.mark.asyncio
async def test_qr_confirm_reativacao(
    test_client: AsyncClient, notice_cortado, debtor, cutoff_settings
):
    """Confirma reativacao via QR."""
    from app.services.cutoff_service import CutoffService
    req_result = await CutoffService.request_reactivation(
        debtor.id, valor_pago=Decimal("147500"), registrado_por="Operador"
    )
    assert req_result.success is True

    response = await test_client.post(
        f"/cutoff/qr/{req_result.qr_token}/confirm",
        json={"nome_responsavel": "Tecnico Reativacao QR"},
    )
    assert response.status_code == 200

    client = await Client.get(debtor.id)
    assert client.status == ClientStatus.ATIVO


@pytest.mark.asyncio
async def test_qr_confirm_invalid_token(test_client: AsyncClient, test_db):
    """Token invalido no confirm retorna 404."""
    response = await test_client.post(
        "/cutoff/qr/token_xpto_invalido/confirm",
        json={"nome_responsavel": "Alguem"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_qr_confirm_missing_nome(test_client: AsyncClient, notice_em_aviso):
    """nome_responsavel e obrigatorio no QR confirm."""
    response = await test_client.post(
        "/cutoff/qr/api_test_token_entrega_xyz/confirm",
        json={},
    )
    assert response.status_code == 422


# ==================== FLUXO COMPLETO PONTA A PONTA ====================

@pytest.mark.asyncio
async def test_full_cutoff_workflow_api(
    test_client: AsyncClient,
    auth_headers,
    debtor,
    old_debts,
    cutoff_settings,
):
    """
    Fluxo completo via HTTP:
    candidatos -> criar aviso -> gerar aviso -> entregar -> marcar pronto
    -> gerar ordem -> executar -> solicitar reativacao -> confirmar
    """
    # 1. Verifica candidato
    r = await test_client.get("/cutoff/candidates", headers=auth_headers)
    assert r.status_code == 200
    assert any(c["client_id"] == str(debtor.id) for c in r.json())

    # 2. Cria aviso
    r = await test_client.post(
        "/cutoff/notices", headers=auth_headers,
        json={"client_id": str(debtor.id)},
    )
    assert r.status_code == 201
    notice_id = r.json()["cutoff_notice_id"]

    # 3. Gera aviso (QR entrega)
    r = await test_client.post(f"/cutoff/notices/{notice_id}/generate", headers=auth_headers)
    assert r.status_code == 200
    qr_entrega = r.json()["qr_token"]

    # 4. Confirma entrega via QR (sem auth)
    r = await test_client.post(
        f"/cutoff/qr/{qr_entrega}/confirm",
        json={"nome_responsavel": "Entregador"},
    )
    assert r.status_code == 200

    # 5. Avanca countdown (simula expiracao)
    notice = await CutoffNotice.get(notice_id)
    await notice.update({"$set": {"fecha_limite_pago": (date.today() - timedelta(days=1)).isoformat()}})

    # 6. Marca pronto
    r = await test_client.post(f"/cutoff/notices/{notice_id}/mark-ready", headers=auth_headers)
    assert r.status_code == 200

    # 7. Gera ordem de corte
    r = await test_client.post(f"/cutoff/notices/{notice_id}/generate-order", headers=auth_headers)
    assert r.status_code == 200
    qr_corte = r.json()["qr_token"]

    # 8. Executa corte via QR
    r = await test_client.post(
        f"/cutoff/qr/{qr_corte}/confirm",
        json={"nome_responsavel": "Tecnico Corte"},
    )
    assert r.status_code == 200

    client = await Client.get(debtor.id)
    assert client.status == ClientStatus.CORTADO

    # 9. Solicita reativacao
    r = await test_client.post(
        "/cutoff/reactivation/request",
        headers=auth_headers,
        json={"client_id": str(debtor.id), "valor_pago": "147500"},
    )
    assert r.status_code == 200
    qr_reat = r.json()["qr_token"]

    # 10. Confirma reativacao via QR
    r = await test_client.post(
        f"/cutoff/qr/{qr_reat}/confirm",
        json={"nome_responsavel": "Tecnico Reativacao"},
    )
    assert r.status_code == 200

    client = await Client.get(debtor.id)
    assert client.status == ClientStatus.ATIVO
