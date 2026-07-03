"""
Contexto de org por request.

org_slug e extraido do JWT e armazenado em um ContextVar —
async-safe, cada request tem o seu proprio valor.
"""

from contextvars import ContextVar
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

_org_slug_ctx: ContextVar[Optional[str]] = ContextVar("org_slug", default=None)


def set_org_slug(slug: str) -> None:
    _org_slug_ctx.set(slug)


def get_org_slug() -> Optional[str]:
    return _org_slug_ctx.get()


def require_org_slug() -> str:
    slug = get_org_slug()
    if not slug:
        raise RuntimeError("org_slug nao definido no contexto do request.")
    return slug


async def activate_org_db(slug: str) -> AsyncIOMotorDatabase:
    """
    Ativa o database da org para o request atual.
    ensure_org_db e idempotente — init_beanie so roda uma vez por org por processo.
    """
    from app.database import ensure_org_db
    db = await ensure_org_db(slug)
    set_org_slug(slug)
    return db
