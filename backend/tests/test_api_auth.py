"""
Testes de integracao para endpoints de autenticacao.
"""

import pytest
from httpx import AsyncClient

from app.models.user import User
from app.utils.security import create_access_token, get_password_hash

@pytest.mark.asyncio
async def test_register_user(test_client: AsyncClient, test_user, auth_headers):
    """Testa registro de novo usuario (requer superadmin)."""
    response = await test_client.post(
        "/auth/register",
        headers=auth_headers,
        json={
            "username": "newuser",
            "email": "new@example.com",
            "password": "secret123",
            "full_name": "New User",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "newuser"
    assert data["email"] == "new@example.com"
    assert data["is_superuser"] is False


@pytest.mark.asyncio
async def test_register_requires_superadmin(test_client: AsyncClient, test_db):
    """Testa que registro sem autenticacao retorna 401."""
    response = await test_client.post(
        "/auth/register",
        json={
            "username": "hacker",
            "email": "hacker@example.com",
            "password": "secret123",
            "full_name": "Hacker",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_username(test_client: AsyncClient, test_user, auth_headers):
    """Testa que nao permite username duplicado."""
    response = await test_client.post(
        "/auth/register",
        headers=auth_headers,
        json={
            "username": "testuser",  # Ja existe
            "email": "another@example.com",
            "password": "secret123",
            "full_name": "Another User",
        },
    )

    assert response.status_code == 400
    assert "ja cadastrado" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_success(test_client: AsyncClient, test_user):
    """Testa login com credenciais corretas."""
    response = await test_client.post(
        "/auth/token",
        data={
            "username": "testuser",
            "password": "testpass123",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(test_client: AsyncClient, test_user):
    """Testa login com senha incorreta."""
    response = await test_client.post(
        "/auth/token",
        data={
            "username": "testuser",
            "password": "wrongpassword",
        },
    )

    assert response.status_code == 401
    assert "invalidas" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(test_client: AsyncClient, test_db):
    """Testa login com usuario inexistente."""
    response = await test_client.post(
        "/auth/token",
        data={
            "username": "nonexistent",
            "password": "anypassword",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(test_client: AsyncClient, test_user, auth_headers):
    """Testa endpoint /me com token valido."""
    response = await test_client.get("/auth/me", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_me_no_token(test_client: AsyncClient, test_db):
    """Testa endpoint /me sem token."""
    response = await test_client.get("/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_invalid_token(test_client: AsyncClient, test_db):
    """Testa endpoint /me com token invalido."""
    response = await test_client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid_token"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(test_client: AsyncClient, test_db):
    """Testa que endpoints protegidos exigem autenticacao."""
    response = await test_client.get("/clients/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_with_must_change_password_is_blocked_from_modules(test_client: AsyncClient, test_db):
    """Usuario com must_change_password=True deve acessar apenas /auth/me e /auth/change-password."""
    user = User(
        username="forcechange",
        email="forcechange@example.com",
        hashed_password=get_password_hash("forcepass123"),
        full_name="Force Change",
        is_superuser=False,
        must_change_password=True,
        scopes=["clients"],
    )
    await user.insert()

    token = create_access_token(data={"sub": user.username})
    headers = {"Authorization": f"Bearer {token}"}

    me_response = await test_client.get("/auth/me", headers=headers)
    assert me_response.status_code == 200

    clients_response = await test_client.get("/clients/", headers=headers)
    assert clients_response.status_code == 403
    assert "Troca de senha obrigatoria" in clients_response.json()["detail"]


@pytest.mark.asyncio
async def test_user_without_scope_is_blocked_from_module(test_client: AsyncClient, test_db):
    """Usuario ativo sem escopo do modulo deve receber 403."""
    user = User(
        username="limitedscope",
        email="limitedscope@example.com",
        hashed_password=get_password_hash("scopepass123"),
        full_name="Limited Scope",
        is_superuser=False,
        must_change_password=False,
        scopes=["readings"],  # Nao inclui "clients"
    )
    await user.insert()

    token = create_access_token(data={"sub": user.username})
    headers = {"Authorization": f"Bearer {token}"}

    response = await test_client.get("/clients/", headers=headers)
    assert response.status_code == 403
    assert "Permissao insuficiente" in response.json()["detail"]
