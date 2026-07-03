"""
Testes de integracao para endpoints de configuracoes.

Valida:
- GET /settings/ retorna novos campos
- PATCH /settings/ aceita novos campos
- matching_prioridade invalido retorna 422
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_settings_returns_new_fields(
    test_client: AsyncClient, test_db, test_user, auth_headers, test_settings
):
    """GET /settings/ inclui gerar_sem_leitura_valor_minimo e matching_prioridade."""
    response = await test_client.get("/settings/", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "gerar_sem_leitura_valor_minimo" in data
    assert "matching_prioridade" in data
    assert isinstance(data["matching_prioridade"], list)


@pytest.mark.asyncio
async def test_update_settings_new_fields(
    test_client: AsyncClient, test_db, test_user, auth_headers, test_settings
):
    """PATCH /settings/ aceita gerar_sem_leitura_valor_minimo e matching_prioridade."""
    response = await test_client.patch(
        "/settings/",
        headers=auth_headers,
        json={
            "gerar_sem_leitura_valor_minimo": True,
            "matching_prioridade": ["ci_ruc", "numero_medidor", "nombre_completo"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["gerar_sem_leitura_valor_minimo"] is True
    assert data["matching_prioridade"] == ["ci_ruc", "numero_medidor", "nombre_completo"]


@pytest.mark.asyncio
async def test_update_settings_invalid_matching_prioridade(
    test_client: AsyncClient, test_db, test_user, auth_headers, test_settings
):
    """matching_prioridade com valor invalido retorna 422."""
    response = await test_client.patch(
        "/settings/",
        headers=auth_headers,
        json={
            "matching_prioridade": ["campo_invalido"],
        },
    )

    assert response.status_code == 422
    assert "campo_invalido" in str(response.json())


@pytest.mark.asyncio
async def test_update_settings_preserves_existing(
    test_client: AsyncClient, test_db, test_user, auth_headers, test_settings
):
    """PATCH parcial preserva campos nao enviados."""
    # Atualiza apenas um campo
    response = await test_client.patch(
        "/settings/",
        headers=auth_headers,
        json={"gerar_sem_leitura_valor_minimo": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["gerar_sem_leitura_valor_minimo"] is True
    # Campos existentes preservados
    assert data["tarifa_base"] is not None
    assert data["nombre_junta"] == "Junta Test"
