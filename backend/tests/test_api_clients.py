"""
Testes de integracao para endpoints de clientes.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_client(test_client: AsyncClient, auth_headers, test_db):
    """Testa criacao de cliente."""
    response = await test_client.post(
        "/clients/",
        headers=auth_headers,
        json={
            "nombre_completo": "Maria Garcia",
            "ci_ruc": "9876543",
            "telefono": "021987654",
            "celular": "0982987654",
            "direccion": "Avenida Central 456",
            "manzana": "B",
            "lote": "2",
            "numero_medidor": "MED-002",
            "tipo_tarifa": "RESIDENCIAL",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["nombre_completo"] == "Maria Garcia"
    assert data["ci_ruc"] == "9876543"
    assert data["status"] == "ATIVO"


@pytest.mark.asyncio
async def test_create_client_duplicate_medidor(
    test_client: AsyncClient, auth_headers, sample_client
):
    """Testa que nao permite medidor duplicado."""
    response = await test_client.post(
        "/clients/",
        headers=auth_headers,
        json={
            "nombre_completo": "Outro Cliente",
            "ci_ruc": "1111111",
            "direccion": "Rua Teste",
            "manzana": "C",
            "lote": "1",
            "numero_medidor": "MED-001",  # Ja existe
        },
    )

    assert response.status_code == 400
    assert "ja cadastrado" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_clients(test_client: AsyncClient, auth_headers, sample_client):
    """Testa listagem de clientes."""
    response = await test_client.get("/clients/", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(c["ci_ruc"] == "1234567" for c in data)


@pytest.mark.asyncio
async def test_search_clients_by_name(
    test_client: AsyncClient, auth_headers, sample_client
):
    """Testa busca por nome."""
    response = await test_client.get(
        "/clients/search",
        headers=auth_headers,
        params={"q": "Juan"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["nombre_completo"] == "Juan Perez"


@pytest.mark.asyncio
async def test_search_clients_by_medidor(
    test_client: AsyncClient, auth_headers, sample_client
):
    """Testa busca por numero do medidor."""
    response = await test_client.get(
        "/clients/search",
        headers=auth_headers,
        params={"q": "MED-001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_search_clients_by_manzana(
    test_client: AsyncClient, auth_headers, sample_client
):
    """Testa busca por manzana."""
    response = await test_client.get(
        "/clients/search",
        headers=auth_headers,
        params={"manzana": "A"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(c["manzana"] == "A" for c in data)


@pytest.mark.asyncio
async def test_get_client(test_client: AsyncClient, auth_headers, sample_client):
    """Testa obtencao de cliente por ID."""
    response = await test_client.get(
        f"/clients/{sample_client.id}",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["nombre_completo"] == "Juan Perez"


@pytest.mark.asyncio
async def test_get_client_not_found(test_client: AsyncClient, auth_headers, test_db):
    """Testa cliente nao encontrado."""
    response = await test_client.get(
        "/clients/507f1f77bcf86cd799439011",  # ID valido mas inexistente
        headers=auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_client(test_client: AsyncClient, auth_headers, sample_client):
    """Testa atualizacao de cliente."""
    response = await test_client.patch(
        f"/clients/{sample_client.id}",
        headers=auth_headers,
        json={"telefono": "021999999"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["telefono"] == "021999999"


@pytest.mark.asyncio
async def test_list_by_route(test_client: AsyncClient, auth_headers, sample_client):
    """Testa listagem por rota."""
    response = await test_client.get(
        "/clients/by-route",
        headers=auth_headers,
        params={"manzana": "A"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_delete_client_with_invoices(
    test_client: AsyncClient, auth_headers, sample_client, sample_invoice
):
    """Testa que nao pode deletar cliente com faturas."""
    response = await test_client.delete(
        f"/clients/{sample_client.id}",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "possui" in response.json()["detail"]
