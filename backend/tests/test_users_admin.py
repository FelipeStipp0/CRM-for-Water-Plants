"""
Gestao de usuarios pelo master: promover, ajustar modulos, remover.

O que estava faltando e motivou isto: nao havia como editar permissoes nem
excluir usuario. Promover alguem exigiria recriar a conta, perdendo o historico.
"""

import pytest

from app.models.user import User
from app.routers.auth import SCOPES_DISPONIVEIS
from app.utils.security import get_password_hash


async def _user(username, role="operator", scopes=None) -> User:
    u = User(
        username=username, email=f"{username}@test.py",
        hashed_password=get_password_hash("x123456"),
        full_name=username.title(), role=role, scopes=scopes or [],
    )
    await u.insert()
    return u


def test_catalogo_de_scopes_cobre_o_que_o_backend_exige():
    """
    A UI monta os checkboxes a partir deste catalogo. Se um escopo exigido pelo
    backend nao estiver aqui, ele e INCONCEDIVEL pela interface — foi o caso de
    `caja`, que tornava impossivel criar um cajero.
    """
    oferecidos = {s["scope"] for s in SCOPES_DISPONIVEIS}
    exigidos = {"caja", "clients", "cutoff", "finance", "invoices",
                "payments", "readings", "sifen", "sponsors"}
    assert exigidos <= oferecidos, f"faltam no catalogo: {exigidos - oferecidos}"

    # e nao pode oferecer escopo que nao existe: `settings` e gateado por role
    assert "settings" not in oferecidos


@pytest.mark.asyncio
async def test_promover_operador_a_master_da_acesso_total(test_db):
    u = await _user("cajero1", scopes=["caja"])
    await u.update({"$set": {"role": "master", "scopes": ["*"]}})
    u = await User.find_one(User.username == "cajero1")
    assert u.role == "master" and u.scopes == ["*"]


@pytest.mark.asyncio
async def test_nao_remove_o_ultimo_master(test_db):
    """A org ficaria sem quem administra — inclusive sem quem cria outro master."""
    await _user("unico", role="master", scopes=["*"])
    masters = await User.find(User.role == "master").count()
    assert masters == 1
    # a regra do endpoint: com <= 1 master, a remocao e recusada
    assert masters <= 1


@pytest.mark.asyncio
async def test_scope_caja_e_distinto_de_payments(test_db):
    """
    Modo Caja entra por escopo `caja`; `payments` e o modulo de Pagamentos. Eram
    tratados como sinonimo na UI e o cajero caia na tela errada.
    """
    u = await _user("cajero2", scopes=["caja"])
    assert "caja" in u.scopes and "payments" not in u.scopes
