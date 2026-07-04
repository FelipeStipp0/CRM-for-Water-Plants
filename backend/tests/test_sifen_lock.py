"""
Testes do lock de sessão da facturación electrónica (sessão única por RUC).
Precisam de MongoDB (fixture test_db).
"""

from datetime import datetime, timedelta

import pytest

from app.services.sifen import lock
from app.models.sifen import SifenSessionLock


@pytest.mark.asyncio
async def test_dois_coordenadores_um_emite(test_db):
    """Dois coordenadores disputam o lock → só um adquire."""
    a = await lock.adquirir("coord-A")
    b = await lock.adquirir("coord-B")
    assert a is True
    assert b is False  # B não consegue enquanto A detém

    # reentrância: A pode readquirir o próprio lock
    assert await lock.adquirir("coord-A") is True

    # A libera → B agora consegue
    await lock.liberar("coord-A")
    assert await lock.adquirir("coord-B") is True


@pytest.mark.asyncio
async def test_heartbeat_mantem_e_falha_apos_perder(test_db):
    assert await lock.adquirir("coord-A") is True
    assert await lock.heartbeat("coord-A") is True
    # B não detém → heartbeat de B falha
    assert await lock.heartbeat("coord-B") is False


@pytest.mark.asyncio
async def test_lock_stale_e_assumido_por_outro(test_db):
    """Se o detentor cai (heartbeat velho > TTL), outro assume."""
    assert await lock.adquirir("coord-A") is True
    # simula A morto: heartbeat antigo
    coll = SifenSessionLock.get_pymongo_collection()
    await coll.update_one(
        {"key": "session"},
        {"$set": {"heartbeat_at": datetime.utcnow() - timedelta(seconds=lock.TTL_SEGUNDOS + 5)}},
    )
    # B assume o lock stale
    assert await lock.adquirir("coord-B") is True
    # e agora A não consegue mais (B é o dono, heartbeat fresco)
    assert await lock.adquirir("coord-A") is False
