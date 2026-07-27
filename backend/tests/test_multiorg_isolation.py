"""
Isolamento multi-tenant: um processo servindo várias orgs não pode misturar dados.

Regressão real: `init_beanie` guarda a coleção em estado de CLASSE, então a
última org inicializada valia para todas — o master de uma junta vazia lia os
clientes da outra. Precisam de MongoDB.
"""

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.middleware.org_context import set_org_slug
from app.models.base import registrar_settings_da_org, limpar_registro, orgs_registradas
from app.models.client import Client, ClientCategory, ClientStatus
from app.models.invoice import Counter


MODELS = [Client, Counter]
ORGS = ("orgtest_a", "orgtest_b")


@pytest_asyncio.fixture
async def duas_orgs():
    """Inicializa duas orgs no mesmo processo, como o backend faz por request."""
    mongo = AsyncIOMotorClient("mongodb://127.0.0.1:27017")
    for slug in ORGS:
        db = mongo[f"wmapp_{slug}"]
        await init_beanie(database=db, document_models=MODELS)
        registrar_settings_da_org(slug, MODELS)
        await db["clients"].delete_many({})

    yield mongo

    for slug in ORGS:
        await mongo.drop_database(f"wmapp_{slug}")
    limpar_registro()
    set_org_slug(None)
    mongo.close()


def _cliente(nome: str, ci: str) -> Client:
    return Client(
        nombre_completo=nome, ci_ruc=ci, direccion="Calle 1",
        categoria=ClientCategory.RESIDENCIAL, status=ClientStatus.ATIVO,
    )


@pytest.mark.asyncio
async def test_cada_org_le_o_seu_banco(duas_orgs):
    set_org_slug("orgtest_a")
    await _cliente("Cliente de A", "111").insert()
    await _cliente("Otro de A", "112").insert()

    set_org_slug("orgtest_b")
    await _cliente("Cliente de B", "221").insert()

    set_org_slug("orgtest_a")
    nomes_a = sorted(c.nombre_completo for c in await Client.find_all().to_list())
    set_org_slug("orgtest_b")
    nomes_b = sorted(c.nombre_completo for c in await Client.find_all().to_list())

    assert nomes_a == ["Cliente de A", "Otro de A"]
    assert nomes_b == ["Cliente de B"]


@pytest.mark.asyncio
async def test_org_vazia_nao_enxerga_a_outra(duas_orgs):
    """O caso que apareceu em produção: a junta nova lia os dados da junta cheia."""
    set_org_slug("orgtest_a")
    await _cliente("Cliente de A", "111").insert()

    # a org B foi inicializada ANTES de A receber dados; mesmo assim segue vazia
    set_org_slug("orgtest_b")
    assert await Client.find_all().count() == 0
    assert await Client.find_one(Client.ci_ruc == "111") is None


@pytest.mark.asyncio
async def test_alternar_entre_orgs_nao_gruda(duas_orgs):
    """Tocar na org B não pode 'levar junto' as consultas seguintes da org A."""
    set_org_slug("orgtest_a")
    await _cliente("Cliente de A", "111").insert()

    for _ in range(3):
        set_org_slug("orgtest_b")
        assert await Client.find_all().count() == 0
        set_org_slug("orgtest_a")
        assert await Client.find_all().count() == 1


@pytest.mark.asyncio
async def test_contadores_sao_por_org(duas_orgs):
    """Numeração sequencial (factura/recibo/caja) não pode vazar entre juntas."""
    set_org_slug("orgtest_a")
    assert await Counter.get_next("invoice_number") == 1
    assert await Counter.get_next("invoice_number") == 2

    set_org_slug("orgtest_b")
    assert await Counter.get_next("invoice_number") == 1   # começa do zero

    set_org_slug("orgtest_a")
    assert await Counter.get_next("invoice_number") == 3   # continua de onde parou


@pytest.mark.asyncio
async def test_sem_slug_usa_a_ultima_inicializada(duas_orgs):
    """Scripts e testes de org única rodam sem ContextVar — não podem quebrar."""
    set_org_slug(None)
    await Client.find_all().count()   # não levanta
    assert set(orgs_registradas(Client)) == set(ORGS)
