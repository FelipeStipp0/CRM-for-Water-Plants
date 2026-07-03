"""
Testes para o servico de matching de clientes.

Testa:
- Matching por numero_medidor, ci_ruc, nombre
- Normalizacao de identificadores
- Ordem de prioridade
- Fallback entre campos
- Exclusao de clientes inativos
"""

import pytest
import pytest_asyncio

from app.models.client import Client, ClientCategory, ClientStatus
from app.services.client_matching import (
    ClientMatchingService,
    normalize_identifier,
    normalize_name,
)


# ---- Testes unitarios de normalizacao (sem DB) ----

def test_normalize_identifier_basic():
    assert normalize_identifier("MED-001") == "med001"


def test_normalize_identifier_spaces_and_case():
    assert normalize_identifier("  Med 001  ") == "med001"


def test_normalize_identifier_special_chars():
    assert normalize_identifier("DOC/123.456-7") == "doc1234567"


def test_normalize_identifier_empty():
    assert normalize_identifier("") == ""
    assert normalize_identifier(None) == ""


def test_normalize_name_basic():
    assert normalize_name("Juan  Perez") == "juan perez"


def test_normalize_name_extra_spaces():
    assert normalize_name("  Maria   Del   Carmen  ") == "maria del carmen"


# ---- Testes com DB ----

@pytest_asyncio.fixture
async def three_clients(test_db):
    """Cria 3 clientes ativos para testes de matching."""
    clients = []
    data = [
        ("Juan Perez", "DOC-001", "MED-001"),
        ("Maria Lopez", "DOC-002", "MED-002"),
        ("Carlos Garcia", "DOC-003", "MED-003"),
    ]
    for nombre, ci, medidor in data:
        c = Client(
            nombre_completo=nombre,
            ci_ruc=ci,
            direccion="Calle Test",
            manzana="A",
            lote="1",
            numero_medidor=medidor,
            categoria=ClientCategory.RESIDENCIAL,
            status=ClientStatus.ATIVO,
        )
        await c.insert()
        clients.append(c)
    return clients


@pytest.mark.asyncio
async def test_match_by_meter(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match(numero_medidor="MED-001")
    assert result is not None
    assert result.nombre_completo == "Juan Perez"


@pytest.mark.asyncio
async def test_match_by_meter_normalized(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match(numero_medidor="med 002")
    assert result is not None
    assert result.nombre_completo == "Maria Lopez"


@pytest.mark.asyncio
async def test_match_by_ci_ruc(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match(ci_ruc="DOC-003")
    assert result is not None
    assert result.nombre_completo == "Carlos Garcia"


@pytest.mark.asyncio
async def test_match_by_name(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match(nombre="juan perez")
    assert result is not None
    assert result.nombre_completo == "Juan Perez"


@pytest.mark.asyncio
async def test_match_by_name_case_insensitive(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match(nombre="MARIA LOPEZ")
    assert result is not None
    assert result.nombre_completo == "Maria Lopez"


@pytest.mark.asyncio
async def test_match_priority_meter_first(test_db, three_clients):
    """Com prioridade padrao, medidor vem antes de nome."""
    matcher = ClientMatchingService(
        three_clients,
        prioridade=["numero_medidor", "ci_ruc", "nombre_completo"]
    )
    # Medidor de Juan, nome de Maria - deve retornar Juan (medidor tem prioridade)
    result = matcher.match(numero_medidor="MED-001", nombre="Maria Lopez")
    assert result.nombre_completo == "Juan Perez"


@pytest.mark.asyncio
async def test_match_priority_name_first(test_db, three_clients):
    """Com prioridade alterada, nome vem antes de medidor."""
    matcher = ClientMatchingService(
        three_clients,
        prioridade=["nombre_completo", "numero_medidor", "ci_ruc"]
    )
    # Medidor de Juan, nome de Maria - deve retornar Maria (nome tem prioridade)
    result = matcher.match(numero_medidor="MED-001", nombre="Maria Lopez")
    assert result.nombre_completo == "Maria Lopez"


@pytest.mark.asyncio
async def test_match_fallback(test_db, three_clients):
    """Se medidor nao fornecido, cai pro proximo campo."""
    matcher = ClientMatchingService(
        three_clients,
        prioridade=["numero_medidor", "ci_ruc", "nombre_completo"]
    )
    # Sem medidor, com CI - deve usar CI
    result = matcher.match(ci_ruc="DOC-002")
    assert result is not None
    assert result.nombre_completo == "Maria Lopez"


@pytest.mark.asyncio
async def test_match_no_match(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match(numero_medidor="MED-999")
    assert result is None


@pytest.mark.asyncio
async def test_match_no_identifiers(test_db, three_clients):
    matcher = ClientMatchingService(three_clients)
    result = matcher.match()
    assert result is None


@pytest.mark.asyncio
async def test_match_excludes_inactive(test_db):
    """Clientes inativos nao sao incluidos no matching via factory."""
    active = Client(
        nombre_completo="Ativo",
        ci_ruc="A-001",
        direccion="Rua",
        manzana="A",
        lote="1",
        numero_medidor="MED-A",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    inactive = Client(
        nombre_completo="Inativo",
        ci_ruc="I-001",
        direccion="Rua",
        manzana="A",
        lote="2",
        numero_medidor="MED-I",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.INATIVO,
    )
    await active.insert()
    await inactive.insert()

    matcher = await ClientMatchingService.create()

    assert matcher.match(numero_medidor="MED-A") is not None
    assert matcher.match(numero_medidor="MED-I") is None


@pytest.mark.asyncio
async def test_create_factory(test_db, three_clients):
    """Testa factory method que carrega do banco."""
    matcher = await ClientMatchingService.create()
    result = matcher.match(numero_medidor="MED-001")
    assert result is not None
    assert result.nombre_completo == "Juan Perez"
