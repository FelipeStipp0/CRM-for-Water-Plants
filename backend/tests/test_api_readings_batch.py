"""
Testes de integracao para POST /readings/batch.

Valida:
- Payload antigo (com client_id) continua aceito
- Matching por identificadores funciona
- matching_prioridade invalido retorna 422
- Idempotencia (batch duplicado pula)
"""

import pytest
from httpx import AsyncClient

from app.models.client import Client, ClientCategory, ClientStatus


@pytest.mark.asyncio
async def test_batch_with_client_id_compat(test_client: AsyncClient, test_db, test_user, auth_headers, sample_client):
    """Payload antigo com client_id continua funcionando."""
    response = await test_client.post(
        "/readings/batch",
        headers=auth_headers,
        json={
            "mes_referencia": 11,
            "ano_referencia": 2025,
            "readings": [
                {
                    "client_id": str(sample_client.id),
                    "valor_leitura": 150,
                },
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 1
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_batch_with_matching_by_meter(test_client: AsyncClient, test_db, test_user, auth_headers, sample_client):
    """Matching por numero_medidor quando client_id nao fornecido."""
    response = await test_client.post(
        "/readings/batch",
        headers=auth_headers,
        json={
            "mes_referencia": 11,
            "ano_referencia": 2025,
            "readings": [
                {
                    "numero_medidor": sample_client.numero_medidor,
                    "valor_leitura": 200,
                },
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 1
    assert data["matched"] == 1
    assert data["unmatched"] == 0


@pytest.mark.asyncio
async def test_batch_invalid_matching_prioridade_returns_422(
    test_client: AsyncClient, test_db, test_user, auth_headers, sample_client
):
    """matching_prioridade com valor invalido retorna 422."""
    response = await test_client.post(
        "/readings/batch",
        headers=auth_headers,
        json={
            "mes_referencia": 11,
            "ano_referencia": 2025,
            "readings": [
                {
                    "client_id": str(sample_client.id),
                    "valor_leitura": 100,
                },
            ],
            "matching_prioridade": ["campo_invalido"],
        },
    )

    assert response.status_code == 422
    detail = response.json()
    # Pydantic validation error deve mencionar o campo invalido
    assert "campo_invalido" in str(detail)


@pytest.mark.asyncio
async def test_batch_valid_matching_prioridade(
    test_client: AsyncClient, test_db, test_user, auth_headers, sample_client
):
    """matching_prioridade com valores validos e aceito."""
    response = await test_client.post(
        "/readings/batch",
        headers=auth_headers,
        json={
            "mes_referencia": 12,
            "ano_referencia": 2025,
            "readings": [
                {
                    "client_id": str(sample_client.id),
                    "valor_leitura": 120,
                },
            ],
            "matching_prioridade": ["ci_ruc", "numero_medidor", "nombre_completo"],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 1


@pytest.mark.asyncio
async def test_batch_idempotent_skips_duplicate(
    test_client: AsyncClient, test_db, test_user, auth_headers, sample_client
):
    """Segunda execucao do mesmo batch pula leituras existentes."""
    payload = {
        "mes_referencia": 10,
        "ano_referencia": 2025,
        "readings": [
            {
                "client_id": str(sample_client.id),
                "valor_leitura": 180,
            },
        ],
    }

    # Primeira vez
    r1 = await test_client.post("/readings/batch", headers=auth_headers, json=payload)
    assert r1.status_code == 201
    assert r1.json()["created"] == 1

    # Segunda vez - mesmo periodo, mesmo cliente
    r2 = await test_client.post("/readings/batch", headers=auth_headers, json=payload)
    assert r2.status_code == 201
    assert r2.json()["created"] == 0
    assert r2.json()["skipped"] == 1


@pytest.mark.asyncio
async def test_batch_unmatched_identifier(
    test_client: AsyncClient, test_db, test_user, auth_headers
):
    """Identificador sem match retorna em unmatched_details."""
    response = await test_client.post(
        "/readings/batch",
        headers=auth_headers,
        json={
            "mes_referencia": 11,
            "ano_referencia": 2025,
            "readings": [
                {
                    "numero_medidor": "MED-INEXISTENTE",
                    "valor_leitura": 100,
                },
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] == 0
    assert data["unmatched"] == 1
    assert len(data["unmatched_details"]) == 1
    assert data["unmatched_details"][0]["numero_medidor"] == "MED-INEXISTENTE"


@pytest.mark.asyncio
async def test_batch_requires_client_id_or_identifier(
    test_client: AsyncClient, test_db, test_user, auth_headers
):
    """Item sem client_id e sem identificadores retorna 422."""
    response = await test_client.post(
        "/readings/batch",
        headers=auth_headers,
        json={
            "mes_referencia": 11,
            "ano_referencia": 2025,
            "readings": [
                {
                    "valor_leitura": 100,
                    # Sem client_id, sem identificadores
                },
            ],
        },
    )

    assert response.status_code == 422
