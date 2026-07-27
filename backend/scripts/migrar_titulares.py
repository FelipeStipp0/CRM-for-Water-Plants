"""
Cria os Titulares a partir dos clientes existentes e vincula cada ligação.

  python -m scripts.migrar_titulares <slug> [--apply]

Regra de agrupamento: mesmo `ci_ruc` = mesmo titular. Com UMA exceção que importa
muito — `44444401-7` é o RUC de cliente ocasional, usado por quem não tem
documento válido. Agrupar por ele fundiria dezenas de pessoas sem relação num
titular só. Esses ficam com um titular individual cada.

Idempotente: quem já tem `titular_id` é ignorado, então dá para rodar de novo.
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RUC_OCASIONAL = "44444401-7"


def _nome_do_titular(clientes: list) -> str:
    """
    O nome do titular sai da ligação com o nome mais "limpo".

    O cadastro antigo carrega contexto no nome ("CASA 01 - Reginaldo",
    "ALQUILLER - FABIO"). Preferimos o mais curto sem marcador, que costuma ser
    o nome da pessoa; se todos tiverem marcador, fica o mais curto mesmo.
    """
    marcadores = ("alquil", "allquil", "aluga", "casa ", "chalé", "chale")
    limpos = [c.nombre_completo for c in clientes
              if not any(m in c.nombre_completo.lower() for m in marcadores)]
    return min(limpos or [c.nombre_completo for c in clientes], key=len).strip()


async def _main(args) -> int:
    from app.database import init_db, ensure_org_db, close_db
    from app.middleware.org_context import set_org_slug
    from app.models.client import Client
    from app.models.titular import Titular

    await init_db()
    set_org_slug(args.slug)
    await ensure_org_db(args.slug)

    clientes = await Client.find(Client.titular_id == None).to_list()  # noqa: E711
    if not clientes:
        print("Nenhuma ligacao sem titular — nada a fazer.")
        await close_db()
        return 0

    grupos: dict = defaultdict(list)
    for c in clientes:
        # ocasional: chave unica por cliente, senao viram todos a mesma pessoa
        chave = f"__ocasional__{c.id}" if c.ci_ruc == RUC_OCASIONAL else c.ci_ruc
        grupos[chave].append(c)

    multi = {k: v for k, v in grupos.items() if len(v) > 1}
    print(f"ligacoes sem titular : {len(clientes)}")
    print(f"titulares a criar    : {len(grupos)}")
    print(f"  com 1 ligacao      : {len(grupos) - len(multi)}")
    print(f"  com 2+ ligacoes    : {len(multi)}")
    print("\n--- titulares com varias ligacoes ---")
    for k, v in sorted(multi.items(), key=lambda x: -len(x[1]))[:8]:
        print(f"  {_nome_do_titular(v)[:34]:<36} {len(v)} ligacoes  (doc {v[0].ci_ruc})")

    if not args.apply:
        print("\nDRY-RUN: nada gravado.")
        await close_db()
        return 0

    criados = vinculados = 0
    for _, membros in grupos.items():
        base = membros[0]
        titular = Titular(
            nombre_completo=_nome_do_titular(membros),
            ci_ruc=base.ci_ruc,
            es_contribuyente=base.es_contribuyente,
            celular=next((m.celular for m in membros if m.celular), None),
            telefono=next((m.telefono for m in membros if m.telefono), None),
            email=next((m.email for m in membros if m.email), None),
            created_at=datetime.utcnow(),
        )
        await titular.insert()
        criados += 1
        for m in membros:
            m.titular_id = titular.id
            await m.save()
            vinculados += 1

    print(f"\ntitulares criados : {criados}")
    print(f"ligacoes vinculadas: {vinculados}")
    print(f"sem titular restante: {await Client.find(Client.titular_id == None).count()}")  # noqa: E711
    await close_db()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Cria Titulares a partir dos clientes.")
    p.add_argument("slug")
    p.add_argument("--apply", action="store_true", help="grava (sem isto e dry-run)")
    sys.exit(asyncio.run(_main(p.parse_args())))
