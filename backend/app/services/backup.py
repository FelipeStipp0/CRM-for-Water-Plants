"""
Backup / restore lógico por org.

Dump lógico em Python (sem depender do binário `mongodump`, que pode não estar no
ambiente): serializa cada coleção em Extended-JSON (via bson.json_util, que preserva
ObjectId / Decimal128 / datetime / DBRef), gzipa e sobe pro R2 em `backups/{slug}/...`.

Restore lê o arquivo e regrava as coleções (substituição). Round-trip testável sem R2
pelas funções puras `dump_database` / `load_database`.

Uso operacional: `tools/backup_cli.py` (backup/list/restore manual).
"""

import gzip
import logging
from datetime import datetime
from typing import Optional

from bson import json_util
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.database import ensure_org_db, get_admin_client
from app.utils.r2 import get_r2_client, r2_put, r2_get

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "backups"
_SKIP = ("system.",)


# ----------------------------------------------------------------- puro (testável)
async def dump_database(db: AsyncIOMotorDatabase) -> bytes:
    """Dump lógico de todas as coleções → gzip(Extended-JSON). Round-trippável."""
    payload = {
        "_meta": {"created_at": datetime.utcnow().isoformat() + "Z", "collections": []},
        "data": {},
    }
    for name in await db.list_collection_names():
        if any(name.startswith(p) for p in _SKIP):
            continue
        docs = await db[name].find({}).to_list(length=None)
        payload["data"][name] = docs
        payload["_meta"]["collections"].append({"name": name, "count": len(docs)})

    raw = json_util.dumps(payload).encode("utf-8")
    return gzip.compress(raw)


async def load_database(
    db: AsyncIOMotorDatabase, blob: bytes, *, drop_existing: bool = True
) -> dict:
    """
    Restaura um dump. drop_existing=True limpa cada coleção antes de reinserir
    (restore = substituição, não merge). Retorna {coleção: nº de docs restaurados}.
    """
    parsed = json_util.loads(gzip.decompress(blob).decode("utf-8"))
    data = parsed.get("data", {})
    restored: dict = {}
    for name, docs in data.items():
        coll = db[name]
        if drop_existing:
            await coll.delete_many({})
        if docs:
            await coll.insert_many(docs)
        restored[name] = len(docs)
    return restored


# ----------------------------------------------------------------- R2 por org
def _backup_key(slug: str, ts: Optional[datetime] = None) -> str:
    ts = ts or datetime.utcnow()
    return f"{BACKUP_PREFIX}/{slug}/{ts:%Y%m%dT%H%M%SZ}.json.gz"


async def backup_org(slug: str) -> dict:
    """Dump da org + upload pro R2. Retorna {slug, key, collections, bytes}."""
    if get_r2_client() is None:
        raise RuntimeError("R2 não configurado — impossível fazer backup remoto.")
    db = await ensure_org_db(slug)
    blob = await dump_database(db)
    key = _backup_key(slug)
    r2_put(key, blob, "application/gzip")
    logger.info("[backup] %s → %s (%d bytes)", slug, key, len(blob))
    return {"slug": slug, "key": key, "bytes": len(blob)}


def list_org_backups(slug: str, limit: int = 100) -> list[dict]:
    """Lista os backups de uma org no R2 (mais recentes primeiro)."""
    s3 = get_r2_client()
    if s3 is None:
        return []
    settings = get_settings()
    resp = s3.list_objects_v2(
        Bucket=settings.r2_bucket_name, Prefix=f"{BACKUP_PREFIX}/{slug}/", MaxKeys=1000)
    items = [
        {"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"].isoformat()}
        for o in resp.get("Contents", [])
    ]
    items.sort(key=lambda x: x["key"], reverse=True)
    return items[:limit]


async def restore_org(slug: str, key: str, *, drop_existing: bool = True) -> dict:
    """Restaura um backup específico (por key do R2) no banco da org. DESTRUTIVO."""
    blob = r2_get(key)
    db = await ensure_org_db(slug)
    restored = await load_database(db, blob, drop_existing=drop_existing)
    logger.warning("[restore] %s ← %s (%s)", slug, key, restored)
    return {"slug": slug, "key": key, "restored": restored}


def _prune_org_backups(slug: str, keep: int = 14) -> int:
    """Mantém só os `keep` backups mais recentes da org; apaga o resto. Retorna nº apagados."""
    s3 = get_r2_client()
    if s3 is None:
        return 0
    settings = get_settings()
    backups = list_org_backups(slug, limit=10000)
    old = backups[keep:]
    for b in old:
        s3.delete_object(Bucket=settings.r2_bucket_name, Key=b["key"])
    return len(old)


async def backup_all_orgs(keep: int = 14) -> list[dict]:
    """Backup de todas as orgs (job diário). Aplica retenção. Nunca levanta — loga e segue."""
    results = []
    admin = get_admin_client()["wmapp_admin"]
    orgs = await admin["organizations"].find({}, {"slug": 1}).to_list(length=None)
    for o in orgs:
        slug = o.get("slug")
        if not slug:
            continue
        try:
            res = await backup_org(slug)
            res["pruned"] = _prune_org_backups(slug, keep=keep)
            results.append(res)
        except Exception as err:  # noqa: BLE001
            logger.error("[backup] falhou para org %s: %s", slug, err)
            results.append({"slug": slug, "error": str(err)})
    return results
