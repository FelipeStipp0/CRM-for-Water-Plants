"""
Sincroniza o padrón RUC do DNIT sob demanda (o normal é o cron diário fazer isso).

Baixa direto do portal do DNIT, carrega em coleção temporária e troca atomicamente
— a lógica toda vive em `app/services/ruc_registry.py`, para não existirem dois
parsers divergentes. Antes este script tinha o seu próprio, que quebrava nas linhas
com `|` dentro do nome e gravava o código de equivalencia como estado.

Uso (a partir de `backend/`):

    python -m scripts.import_ruc            # sincroniza se houver publicação nova
    python -m scripts.import_ruc --forcar   # reimporta mesmo sem mudança
    python -m scripts.import_ruc --status   # só mostra o estado atual
"""

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _aplicar_public_host(host: str) -> None:
    """
    Troca o host do MONGODB_URL pelo proxy TCP publico.

    Rodando de fora do Railway, o MONGODB_URL do servico aponta para a rede
    privada (`*.railway.internal`), que so resolve la dentro. Precisa acontecer
    ANTES do init_db, que e quem le a configuracao.
    """
    url = os.environ.get("MONGODB_URL") or os.environ.get("MONGO_PUBLIC_URL", "")
    if url:
        os.environ["MONGODB_URL"] = re.sub(
            r"(://(?:[^@/]*@)?)[^/?]+", r"\g<1>" + host, url, count=1)


async def _main(args) -> int:
    if args.public_host:
        _aplicar_public_host(args.public_host)

    from app.database import init_db, close_db      # noqa: PLC0415 — depois do env
    from app.services import ruc_registry           # noqa: PLC0415

    await init_db()
    try:
        if args.status:
            print(await ruc_registry.status())
            return 0
        print("Sincronizando o padron RUC (pode levar alguns minutos)...")
        r = await ruc_registry.sincronizar(forcar=args.forcar)
        print(r)
        return 0 if r.get("status") in ("ok", "sem_mudanca") else 1
    finally:
        await close_db()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Sincroniza o padron RUC do DNIT.")
    p.add_argument("--forcar", action="store_true",
                   help="reimporta mesmo se o Last-Modified nao mudou")
    p.add_argument("--status", action="store_true",
                   help="mostra o estado da ultima sincronizacao")
    p.add_argument("--public-host", metavar="HOST:PORT",
                   help="troca o host da URL (proxy TCP publico do Railway)")
    sys.exit(asyncio.run(_main(p.parse_args())))
