"""
CLI de backup/restore por org (uso operacional).

  python -m scripts.backup_cli backup <slug>
  python -m scripts.backup_cli backup-all
  python -m scripts.backup_cli list <slug>
  python -m scripts.backup_cli restore <slug> <r2_key>   # DESTRUTIVO — pede confirmação

`restore` SUBSTITUI os dados da org pelo conteúdo do backup. Sempre teste o restore
num ambiente à parte antes de confiar num backup em produção.
"""

import asyncio
import sys

from app.database import init_db, close_db
from app.services.backup import (
    backup_org, backup_all_orgs, list_org_backups, restore_org,
)


async def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    await init_db()
    try:
        if cmd == "backup" and len(argv) == 3:
            print(await backup_org(argv[2]))
        elif cmd == "backup-all":
            for r in await backup_all_orgs():
                print(r)
        elif cmd == "list" and len(argv) == 3:
            rows = list_org_backups(argv[2])
            if not rows:
                print("(sem backups)")
            for b in rows:
                print(f"{b['last_modified']}  {b['size']:>10}  {b['key']}")
        elif cmd == "restore" and len(argv) == 4:
            slug, key = argv[2], argv[3]
            print(f"⚠️  Isto SUBSTITUI todos os dados de '{slug}' pelo backup:\n    {key}")
            if input("Digite 'RESTORE' para confirmar: ").strip() != "RESTORE":
                print("Cancelado.")
                return 1
            print(await restore_org(slug, key))
        else:
            print(__doc__)
            return 1
    finally:
        await close_db()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv)))
