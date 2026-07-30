"""
Testes do que o balcão precisa do backend (Fases 0, 1, 2 e 5 do plano da caja).

- a busca devolve o total que casou, não só a página (senão a tela esconde
  clientes sem avisar e o cajero cobra do homônimo errado);
- CI/RUC duplicado é recusado **no backend**, não só na tela;
- `payment-context` separa otros cargos (AVULSA) da grade de meses de água, e a
  grade marca a parte do mês que é cuota de acordo;
- `/payments/atenciones` acha o atendimento por nº de recibo, por cliente e por
  dia, e diz se já foi anulado — é a base da reimpressão e da anulação no balcão;
- `/caja/cargo` deixa o balcão faturar um cargo de valor livre **com o escopo
  que ele tem** — os testes do cargo usam uma usuária de escopo `caja`, não o
  usuário `*` dos outros testes, porque foi exatamente essa diferença que passou
  batido e virou 403 na junta.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.client import Client, ClientStatus
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus, InvoiceType
from app.models.payment import PaymentMethod
from app.models.user import User
from app.services.payment_distribution import PaymentDistributionService


async def _factura_consumo(client, mes, ano, valor, cuota=None):
    inv = Invoice(
        client=client, tipo=InvoiceType.CONSUMO, status=InvoiceStatus.PENDENTE,
        mes_referencia=mes, ano_referencia=ano, fecha_vencimiento=date(ano, mes, 15),
        valor_total=Decimal(valor), saldo_devedor=Decimal(valor),
        fecha_emision=datetime(ano, mes, 1),
        cuota_valor=Decimal(cuota) if cuota else None,
        cuota_iva_tasa=5 if cuota else None,
        cuota_iva_afectacion=3 if cuota else None,
        cuota_numero=2 if cuota else None,
    )
    await inv.insert()
    return inv


async def _factura_avulsa(client, mes, ano, desc, valor, tasa=10, afect=1):
    inv = Invoice(
        client=client, tipo=InvoiceType.AVULSA, status=InvoiceStatus.PENDENTE,
        mes_referencia=mes, ano_referencia=ano, fecha_vencimiento=date(ano, mes, 20),
        items=[InvoiceItem(descripcion=desc, cantidad=1,
                           precio_unitario=Decimal(valor),
                           iva_tasa=tasa, iva_afectacion=afect)],
        valor_total=Decimal(valor), saldo_devedor=Decimal(valor),
        fecha_emision=datetime(ano, mes, 2),
    )
    await inv.insert()
    return inv


# ------------------------------------------------------------------ Fase 0
@pytest.mark.asyncio
async def test_search_devuelve_el_total_que_coincide(
        test_client: AsyncClient, auth_headers, test_db):
    for i in range(7):
        await Client(
            nombre_completo=f"Ramirez {i}", ci_ruc=f"400000{i}",
            direccion="Calle 1", numero_medidor=f"MED-40{i}",
            status=ClientStatus.ATIVO,
        ).insert()

    r = await test_client.get("/clients/search", headers=auth_headers,
                              params={"q": "Ramirez", "limit": 3})
    assert r.status_code == 200
    assert len(r.json()) == 3
    # É este header que deixa a tela dizer "3 de 7" em vez de esconder o resto.
    assert r.headers["X-Total-Count"] == "7"


# ------------------------------------------------------------------ Fase 1
@pytest.mark.asyncio
async def test_ci_ruc_duplicado_bloqueado_en_el_backend(
        test_client: AsyncClient, auth_headers, sample_client):
    r = await test_client.post("/clients/", headers=auth_headers, json={
        "nombre_completo": "Otro Juan",
        "ci_ruc": sample_client.ci_ruc,
        "direccion": "Otra calle 999",
        "numero_medidor": "MED-999",
    })
    assert r.status_code == 400
    assert "CI/RUC" in r.json()["detail"]


# ------------------------------------------------------------------ Fase 2.1
@pytest.mark.asyncio
async def test_payment_context_separa_otros_cargos_de_la_grilla(
        test_client: AsyncClient, auth_headers, test_settings, sample_client):
    hoy = date.today()
    await _factura_consumo(sample_client, hoy.month, hoy.year, "30000")
    await _factura_avulsa(sample_client, hoy.month, hoy.year, "Reconexión", "50000",
                          tasa=5, afect=3)

    r = await test_client.get(f"/clients/{sample_client.id}/payment-context",
                              headers=auth_headers)
    assert r.status_code == 200
    data = r.json()

    # O cargo da tesouraria aparece em lista própria, com os itens e o IVA deles.
    assert len(data["otros_cargos"]) == 1
    cargo = data["otros_cargos"][0]
    assert cargo["tipo"] == "AVULSA"
    assert cargo["items"][0]["descripcion"] == "Reconexión"
    assert cargo["items"][0]["iva_tasa"] == 5
    assert cargo["items"][0]["iva_afectacion"] == 3

    # E NÃO entra no mês da grade: o mês é consumo de água.
    celda = next(c for c in data["grade_meses"]
                 if c["mes"] == hoy.month and c["ano"] == hoy.year)
    assert float(celda["saldo"]) == 30000.0
    assert celda["estado"] == "pendente"

    # O saldo pendente do cliente continua contando os dois.
    assert float(data["saldo_pendiente"]) == 80000.0
    # Cada fatura vem com id: é o que permite cobro direcionado e parcial.
    assert all(f["id"] for f in data["facturas"])


@pytest.mark.asyncio
async def test_payment_context_marca_la_cuota_del_mes(
        test_client: AsyncClient, auth_headers, test_settings, sample_client):
    hoy = date.today()
    await _factura_consumo(sample_client, hoy.month, hoy.year, "55000", cuota="30000")

    r = await test_client.get(f"/clients/{sample_client.id}/payment-context",
                              headers=auth_headers)
    data = r.json()
    celda = next(c for c in data["grade_meses"]
                 if c["mes"] == hoy.month and c["ano"] == hoy.year)
    assert float(celda["cuota"]) == 30000.0

    # A factura legal separa "cuota" de "agua", e a cuota leva o IVA do acordo —
    # não o das configurações. Sem estes campos no contexto, a caja emitiria a
    # parcela com o IVA da água.
    factura = next(f for f in data["facturas"]
                   if f["mes_referencia"] == hoy.month and f["ano_referencia"] == hoy.year)
    assert float(factura["cuota_valor"]) == 30000.0
    assert factura["cuota_iva_tasa"] == 5
    assert factura["cuota_iva_afectacion"] == 3
    assert factura["cuota_numero"] == 2


@pytest.mark.asyncio
async def test_payment_context_ignora_anuladas(
        test_client: AsyncClient, auth_headers, test_settings, sample_client):
    hoy = date.today()
    inv = await _factura_consumo(sample_client, hoy.month, hoy.year, "30000")
    await inv.update({"$set": {"status": InvoiceStatus.ANULADA.value,
                               "saldo_devedor": Decimal("0")}})

    r = await test_client.get(f"/clients/{sample_client.id}/payment-context",
                              headers=auth_headers)
    data = r.json()
    assert float(data["saldo_pendiente"]) == 0.0
    celda = next(c for c in data["grade_meses"]
                 if c["mes"] == hoy.month and c["ano"] == hoy.year)
    # Sem fatura viva o mês volta a ser "sem factura", não "pagada": ninguém pagou.
    assert celda["estado"] == "sem_factura"


# ------------------------------------------------------------ Fases 4 e 5
@pytest.mark.asyncio
async def test_atenciones_busca_por_recibo_cliente_y_dia(
        test_client: AsyncClient, auth_headers, test_settings, sample_client):
    inv = await _factura_consumo(sample_client, 1, 2026, "40000")
    result = await PaymentDistributionService.process_payment(
        client_id=sample_client.id, valor_total=Decimal("40000"),
        metodo=PaymentMethod.EFECTIVO, aplicar_subsidio=False,
        invoice_ids=[inv.id], recibido_por="Cajera",
    )
    assert result.success

    r = await test_client.get("/payments/atenciones", headers=auth_headers)
    assert r.status_code == 200
    filas = r.json()
    assert len(filas) == 1
    fila = filas[0]
    assert fila["client_name"] == sample_client.nombre_completo
    assert fila["grupo_pagamento"]          # chave da reimpressão do recibo
    assert fila["anulada"] is False
    assert fila["emission_id"] is None      # saiu só recibo, sem factura legal
    recibo = fila["numero_recibo"]

    # Por nº de recibo
    r = await test_client.get("/payments/atenciones", headers=auth_headers,
                              params={"q": str(recibo)})
    assert len(r.json()) == 1

    # Por nome do cliente
    r = await test_client.get("/payments/atenciones", headers=auth_headers,
                              params={"q": "Juan"})
    assert len(r.json()) == 1

    # Por dia (janela em UTC, como a tela manda)
    ahora = datetime.utcnow()
    r = await test_client.get("/payments/atenciones", headers=auth_headers, params={
        "desde": (ahora - timedelta(hours=2)).isoformat(),
        "hasta": (ahora + timedelta(hours=2)).isoformat(),
    })
    assert len(r.json()) == 1
    r = await test_client.get("/payments/atenciones", headers=auth_headers, params={
        "desde": (ahora - timedelta(days=9)).isoformat(),
        "hasta": (ahora - timedelta(days=8)).isoformat(),
    })
    assert r.json() == []

    # Termo que não casa com nada não devolve tudo por descuido.
    r = await test_client.get("/payments/atenciones", headers=auth_headers,
                              params={"q": "zzzz-no-existe"})
    assert r.json() == []


@pytest.mark.asyncio
async def test_atenciones_muestra_el_cobro_anulado(
        test_client: AsyncClient, auth_headers, test_settings, sample_client):
    inv = await _factura_consumo(sample_client, 2, 2026, "25000")
    result = await PaymentDistributionService.process_payment(
        client_id=sample_client.id, valor_total=Decimal("25000"),
        metodo=PaymentMethod.EFECTIVO, aplicar_subsidio=False, invoice_ids=[inv.id],
    )
    r = await test_client.post(f"/payments/{result.payment_id}/anular",
                               headers=auth_headers,
                               json={"motivo": "Cobré al cliente equivocado"})
    assert r.status_code == 200

    r = await test_client.get("/payments/atenciones", headers=auth_headers)
    fila = r.json()[0]
    assert fila["anulada"] is True
    assert fila["motivo_anulacion"] == "Cobré al cliente equivocado"
    assert fila["anulada_por"]


# ------------------------------- cargo de valor livre lançado no balcão
@pytest_asyncio.fixture
async def cajera(test_db) -> User:
    """
    Usuária de balcão: escopo `caja` e mais nada.

    É ela que tem de conseguir lançar o cargo. Testar isto com o usuário padrão
    (escopo `*`) não prova nada — foi assim que a primeira versão passou nos
    testes e tomou **403** na junta.
    """
    from app.utils.security import get_password_hash

    user = User(
        username="cajera", email="cajera@example.com",
        hashed_password=get_password_hash("x"), full_name="Cajera",
        must_change_password=False, role="operator", scopes=["caja"],
    )
    await user.insert()
    return user


@pytest.mark.asyncio
async def test_cargo_libre_del_mostrador_nace_cobrable_con_su_iva(
        test_client: AsyncClient, headers_for, test_settings, sample_client, cajera):
    """
    O balcão fatura na hora, com valor e IVA livres, e cobra no mesmo atendimento.

    O plano original dizia que todo cargo nasce na tesouraria e o balcão só
    cobra — mas a junta não tem setores, e quem cobra tem de poder faturar o
    que ninguém lançou. O cargo sai do endpoint pronto para ser cobrado:
    numerado, pendente e **com o IVA escolhido**, que é o que vai para a
    factura legal.
    """
    from app.services.caja_service import abrir_caja

    headers = headers_for(cajera)
    await abrir_caja("cajera", Decimal("0"))

    r = await test_client.post("/caja/cargo", headers=headers, json={
        "client_id": str(sample_client.id),
        "descripcion": "Multa por conexión clandestina",
        "cantidad": 2, "valor": 75000, "iva_tasa": 5, "iva_afectacion": 3,
    })
    assert r.status_code == 201, r.text
    creada = r.json()
    assert creada["numero_factura"]
    assert float(creada["valor_total"]) == 150000.0

    # E já aparece no balcão, em «otros cargos», com o IVA que a factura legal
    # vai usar. Sem o IVA por item, toda AVULSA nascia 10% gravado e o cargo de
    # valor livre não teria como ser exento.
    r = await test_client.get(f"/clients/{sample_client.id}/payment-context",
                              headers=headers)
    cargos = r.json()["otros_cargos"]
    assert len(cargos) == 1
    assert cargos[0]["id"] == creada["id"]
    assert float(cargos[0]["saldo_devedor"]) == 150000.0
    assert cargos[0]["items"][0]["iva_tasa"] == 5
    assert cargos[0]["items"][0]["iva_afectacion"] == 3


@pytest.mark.asyncio
async def test_el_mostrador_no_llega_al_modulo_de_facturas(
        test_client: AsyncClient, headers_for, test_settings, sample_client, cajera):
    """
    Por que `/caja/cargo` existe: o cajero **não** passa em `/invoices` nem em
    `/products`.

    A primeira versão do cargo livre chamava `POST /invoices/` e `GET /products/`
    e tomava 403 no balcão (visto nos logs de produção). Este teste é o guarda:
    se alguém religar o balcão àqueles routers, quebra aqui e não na junta.
    """
    from app.services.caja_service import abrir_caja

    headers = headers_for(cajera)
    await abrir_caja("cajera", Decimal("0"))

    hoy = date.today()
    r = await test_client.post("/invoices/", headers=headers, json={
        "client_id": str(sample_client.id), "tipo": "AVULSA",
        "mes_referencia": hoy.month, "ano_referencia": hoy.year,
        "items": [{"descripcion": "Cargo", "cantidad": 1, "precio_unitario": 1000}],
    })
    assert r.status_code == 403

    assert (await test_client.get("/products/", headers=headers)).status_code == 403

    # O que o balcão usa no lugar responde para ela.
    assert (await test_client.get("/caja/productos", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_cargo_libre_exige_caja_abierta(
        test_client: AsyncClient, headers_for, test_settings, sample_client, cajera):
    """Cargo lançado com a caja fechada é fatura que ninguém viu nascer."""
    r = await test_client.post("/caja/cargo", headers=headers_for(cajera), json={
        "client_id": str(sample_client.id), "descripcion": "Reconexión",
        "valor": 50000,
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cargo_libre_rechaza_iva_invalido_y_valor_cero(
        test_client: AsyncClient, headers_for, test_settings, sample_client, cajera):
    """IVA fora de 0/5/10 não existe no SIFEN — trava aqui, não no KuDE."""
    from app.services.caja_service import abrir_caja

    headers = headers_for(cajera)
    await abrir_caja("cajera", Decimal("0"))
    base = {"client_id": str(sample_client.id), "descripcion": "Cargo raro"}

    r = await test_client.post("/caja/cargo", headers=headers,
                               json={**base, "valor": 1000, "iva_tasa": 7})
    assert r.status_code == 422

    r = await test_client.post("/caja/cargo", headers=headers,
                               json={**base, "valor": 0})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_factura_avulsa_de_tesoreria_guarda_el_iva_del_producto(
        test_client: AsyncClient, auth_headers, test_settings, sample_client):
    """
    O mesmo IVA por item no caminho da tesouraria (`POST /invoices/`).

    Era descartado no schema: toda AVULSA nascia 10% gravado, e a factura legal
    ignorava o IVA do produto do catálogo.
    """
    hoy = date.today()
    r = await test_client.post("/invoices/", headers=auth_headers, json={
        "client_id": str(sample_client.id), "tipo": "AVULSA",
        "mes_referencia": hoy.month, "ano_referencia": hoy.year,
        "items": [{"descripcion": "Cuota de conexión", "cantidad": 1,
                   "precio_unitario": 300000, "iva_tasa": 5, "iva_afectacion": 3}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["items"][0]["iva_tasa"] == 5
    assert r.json()["items"][0]["iva_afectacion"] == 3

    r = await test_client.post("/invoices/", headers=auth_headers, json={
        "client_id": str(sample_client.id), "tipo": "AVULSA",
        "mes_referencia": hoy.month, "ano_referencia": hoy.year,
        "items": [{"descripcion": "Cargo raro", "cantidad": 1,
                   "precio_unitario": 1000, "iva_tasa": 7}],
    })
    assert r.status_code == 422
