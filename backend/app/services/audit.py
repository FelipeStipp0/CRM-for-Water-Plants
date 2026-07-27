"""Helper para registrar entradas na trilha de auditoria."""

from typing import Optional

from app.models.audit import AuditLog


async def registrar_audit(
    action: str,
    entity_type: str,
    usuario: str,
    *,
    entity_id: Optional[str] = None,
    entity_label: Optional[str] = None,
    motivo: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        usuario=usuario,
        motivo=motivo,
        before=before,
        after=after,
    )
    await log.insert()
    return log
