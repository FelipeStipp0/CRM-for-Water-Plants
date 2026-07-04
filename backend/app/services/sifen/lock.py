"""
Lock de sessão da facturación electrónica (uma sessão ativa por RUC).

O portal só permite UMA sessão por contribuinte → a emissão é serializada num
coordenador único. Lock distribuído (singleton no Mongo da org) com TTL + heartbeat:
quem detém o lock renova por heartbeat enquanto emite; se o coordenador cai, o lock
expira (TTL) e outra máquina pode assumir.
"""

from datetime import datetime, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.models.sifen import SifenSessionLock

TTL_SEGUNDOS = 60  # lock expira sem heartbeat; renovar a cada ~20s enquanto emite


async def adquirir(holder: str) -> bool:
    """
    Tenta adquirir o lock singleton. True se `holder` passou a deter o lock.
    Assume o lock se estiver livre, se já for do próprio holder, ou se estiver stale
    (heartbeat mais velho que o TTL).
    """
    now = datetime.utcnow()
    stale = now - timedelta(seconds=TTL_SEGUNDOS)
    coll = SifenSessionLock.get_pymongo_collection()
    try:
        res = await coll.find_one_and_update(
            {
                "key": "session",
                "$or": [
                    {"holder": None},
                    {"holder": holder},
                    {"heartbeat_at": {"$lt": stale}},
                ],
            },
            {
                "$set": {"holder": holder, "acquired_at": now, "heartbeat_at": now},
                "$setOnInsert": {"key": "session"},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # já existe um lock (key único) detido por outro holder ainda vivo → não adquire
        return False
    return bool(res) and res.get("holder") == holder


async def heartbeat(holder: str) -> bool:
    """Renova o lock enquanto `holder` o detém. False se perdeu o lock."""
    coll = SifenSessionLock.get_pymongo_collection()
    res = await coll.find_one_and_update(
        {"key": "session", "holder": holder},
        {"$set": {"heartbeat_at": datetime.utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return bool(res)


async def liberar(holder: str) -> None:
    """Libera o lock se for do `holder` (idempotente)."""
    coll = SifenSessionLock.get_pymongo_collection()
    await coll.update_one(
        {"key": "session", "holder": holder},
        {"$set": {"holder": None, "heartbeat_at": None}},
    )
