"""
Registro de dispositivos da facturación electrónica.

Não é opt-in do usuário: é o **admin** que **permite** quais PCs podem GERAR docs
eletrônicos (não afeta o uso do PC no dia a dia). O dispositivo se anuncia sozinho
(auto-registro) e aparece no painel com presença/uptime; o backend só serve jobs a
dispositivos **permitidos (enabled)** e **online** — assim a emissão sai só de máquinas
autorizadas e o trabalho não para.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from app.models.sifen import SifenCoordinator

ONLINE_TTL_SEGUNDOS = 45  # sem heartbeat nesse tempo => offline


async def anunciar(machine_id: str, label: Optional[str] = None) -> SifenCoordinator:
    """
    Auto-registro do dispositivo (na inicialização do app). Novo device entra
    **desabilitado** — aguarda o admin permitir. Não altera o enabled de um existente.
    """
    now = datetime.utcnow()
    coord = await SifenCoordinator.find_one(SifenCoordinator.machine_id == machine_id)
    if coord is None:
        coord = SifenCoordinator(
            machine_id=machine_id, label=label, enabled=False,
            registered_at=now, last_heartbeat=now,
        )
    else:
        if label:
            coord.label = label
        coord.last_heartbeat = now
    await coord.save()
    return coord


async def permitir(machine_id: str, enabled: bool, admin: Optional[str] = None,
                   label: Optional[str] = None) -> SifenCoordinator:
    """Admin permite (ou revoga) a geração de docs neste dispositivo. Upsert."""
    coord = await SifenCoordinator.find_one(SifenCoordinator.machine_id == machine_id)
    if coord is None:
        coord = SifenCoordinator(machine_id=machine_id, label=label,
                                 registered_at=datetime.utcnow())
    coord.enabled = enabled
    coord.permitted_by = admin
    if label:
        coord.label = label
    await coord.save()
    return coord


async def heartbeat(machine_id: str) -> bool:
    """
    Marca presença do dispositivo. Retorna True se ele está **permitido** (enabled).
    Um device não permitido ainda registra presença (para o admin vê-lo online e permitir).
    """
    coord = await SifenCoordinator.find_one(SifenCoordinator.machine_id == machine_id)
    if coord is None:
        return False
    coord.last_heartbeat = datetime.utcnow()
    await coord.save()
    return coord.enabled


def esta_online(coord: SifenCoordinator) -> bool:
    if not coord.last_heartbeat:
        return False
    return coord.last_heartbeat >= datetime.utcnow() - timedelta(seconds=ONLINE_TTL_SEGUNDOS)


async def listar() -> List[SifenCoordinator]:
    return await SifenCoordinator.find_all().to_list()
