"""
Remove o indice UNICO de `ci_ruc` das orgs existentes.

O modelo deixou de declarar unicidade (uma pessoa tem varias ligacoes; e quem nao
tem documento valido usa o RUC de cliente ocasional, que se repete). Mas o indice
ja criado nao muda sozinho: o Beanie tenta cria-lo sem `unique` no init_beanie,
bate com o que existe e a org inteira falha com IndexKeySpecsConflict — ou seja,
qualquer request para essa org devolve 500.

Orgs criadas DEPOIS da mudanca ja nascem certas; isto e so para as antigas.

  python -m scripts.fix_indice_ci_ruc            # todas as orgs do MONGODB_URL
  python -m scripts.fix_indice_ci_ruc --apply
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

PREFIXO = "wmapp_"
IGNORAR = {"wmapp_admin", "wmapp_ruc"}


async def _main(args) -> int:
    url = os.environ.get("MONGODB_URL")
    if not url:
        print("ERRO: defina MONGODB_URL no ambiente.")
        return 1

    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=20000)
    nomes = [n for n in await client.list_database_names()
             if n.startswith(PREFIXO) and n not in IGNORAR]

    afetadas = []
    for nome in nomes:
        col = client[nome]["clients"]
        try:
            idx = await col.list_indexes().to_list(None)
        except Exception:
            continue
        for i in idx:
            if i["name"] == "ci_ruc_1" and i.get("unique"):
                afetadas.append(nome)

    print(f"orgs encontradas : {len(nomes)}")
    print(f"com indice unico : {len(afetadas)}")
    for n in afetadas:
        print("   -", n)

    if not afetadas:
        print("\nNada a corrigir.")
        return 0
    if not args.apply:
        print("\nDRY-RUN: nada alterado. Rode com --apply.")
        return 0

    for nome in afetadas:
        col = client[nome]["clients"]
        await col.drop_index("ci_ruc_1")
        await col.create_index("ci_ruc")          # segue indexado, sem unicidade
        print(f"   corrigida: {nome}")
    print("\nConcluido.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Remove o indice unico de ci_ruc.")
    p.add_argument("--apply", action="store_true", help="aplica (sem isto e dry-run)")
    sys.exit(asyncio.run(_main(p.parse_args())))
