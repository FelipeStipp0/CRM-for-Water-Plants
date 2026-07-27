"""Consulta da trilha de auditoria (só master)."""

from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.models.audit import AuditLog
from app.models.user import User
from app.routers.auth import get_current_master

router = APIRouter()


class AuditEntry(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    entity_label: Optional[str] = None
    usuario: str
    motivo: Optional[str] = None
    before: Optional[dict] = None
    after: Optional[dict] = None
    created_at: datetime


@router.get("/", response_model=List[AuditEntry])
async def list_audit(
    current_user: Annotated[User, Depends(get_current_master)],
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    """Lista as entradas de auditoria (mais recentes primeiro). Requer role master."""
    query = {}
    if action:
        query["action"] = action
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id

    logs = await AuditLog.find(query).sort(-AuditLog.created_at).limit(limit).to_list()
    return [
        AuditEntry(
            id=str(log.id), action=log.action, entity_type=log.entity_type,
            entity_id=log.entity_id, entity_label=log.entity_label, usuario=log.usuario,
            motivo=log.motivo, before=log.before, after=log.after, created_at=log.created_at,
        )
        for log in logs
    ]
