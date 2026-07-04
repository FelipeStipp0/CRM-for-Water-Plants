"""
Testes do registro de dispositivos (admin permite gerar). Precisam de MongoDB.
"""

from datetime import datetime, timedelta

import pytest

from app.services.sifen import coordinator as coord


@pytest.mark.asyncio
async def test_anuncia_desabilitado_ate_admin_permitir(test_db):
    # PC não anunciado -> heartbeat falha
    assert await coord.heartbeat("pc-1") is False

    # dispositivo se anuncia -> entra DESABILITADO (aguarda admin)
    c = await coord.anunciar("pc-1", "Caixa 1")
    assert c.enabled is False
    assert await coord.heartbeat("pc-1") is False  # ainda não permitido

    # admin permite
    c = await coord.permitir("pc-1", True, admin="admin")
    assert c.enabled is True
    assert await coord.heartbeat("pc-1") is True


@pytest.mark.asyncio
async def test_admin_revoga(test_db):
    await coord.anunciar("pc-1", None)
    await coord.permitir("pc-1", True, admin="admin")
    await coord.permitir("pc-1", False, admin="admin")  # revoga
    assert await coord.heartbeat("pc-1") is False


@pytest.mark.asyncio
async def test_presenca_registrada_mesmo_sem_permissao(test_db):
    """Device não permitido ainda aparece online (pro admin vê-lo e permitir)."""
    await coord.anunciar("pc-1", "Caixa 1")
    await coord.heartbeat("pc-1")  # registra presença mesmo desabilitado
    todos = await coord.listar()
    c = next(x for x in todos if x.machine_id == "pc-1")
    assert coord.esta_online(c) is True
    assert c.enabled is False


@pytest.mark.asyncio
async def test_online_por_ttl(test_db):
    await coord.anunciar("pc-1", None)
    c = await coord.permitir("pc-1", True, admin="admin")
    assert coord.esta_online(c) is True
    c.last_heartbeat = datetime.utcnow() - timedelta(seconds=coord.ONLINE_TTL_SEGUNDOS + 5)
    assert coord.esta_online(c) is False


@pytest.mark.asyncio
async def test_anunciar_nao_duplica_nem_reabilita(test_db):
    await coord.permitir("pc-1", True, admin="admin")   # permitido
    await coord.anunciar("pc-1", "Caixa 1")             # re-anúncio não mexe no enabled
    todos = await coord.listar()
    iguais = [x for x in todos if x.machine_id == "pc-1"]
    assert len(iguais) == 1
    assert iguais[0].enabled is True                    # continua permitido
