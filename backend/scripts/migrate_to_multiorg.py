"""
Script de migracao: single-tenant -> multi-tenant.

O que faz:
1. Cria o database wmapp_admin com a org padrao
2. Copia todos os dados do database atual (wmapp) para wmapp_default
3. Adiciona campo role="master" ao usuario sysadmin existente
4. Renomeia is_superuser -> role nos documentos de usuarios

Uso:
    cd backend
    python scripts/migrate_to_multiorg.py

Variaveis de ambiente necessarias:
    MONGODB_URL       (default: mongodb://127.0.0.1:27017)
    DATABASE_NAME     (default: wmapp)
    DEFAULT_ORG_NAME  (default: "Junta Padrao")
    DEFAULT_ORG_SLUG  (default: "default")
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient


MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://127.0.0.1:27017")
SOURCE_DB = os.getenv("DATABASE_NAME", "wmapp")
DEFAULT_ORG_NAME = os.getenv("DEFAULT_ORG_NAME", "Junta Padrao")
DEFAULT_ORG_SLUG = os.getenv("DEFAULT_ORG_SLUG", "default")
TARGET_DB = f"wmapp_{DEFAULT_ORG_SLUG}"
ADMIN_DB = "wmapp_admin"


async def migrate():
    client = AsyncIOMotorClient(MONGODB_URL)

    source = client[SOURCE_DB]
    target = client[TARGET_DB]
    admin = client[ADMIN_DB]

    print(f"Migrando '{SOURCE_DB}' -> '{TARGET_DB}'")

    # 1. Copia todas as collections para o novo database da org
    collections = await source.list_collection_names()
    for col_name in collections:
        print(f"  Copiando collection: {col_name}")
        docs = await source[col_name].find({}).to_list(length=None)
        if docs:
            await target[col_name].insert_many(docs)
            print(f"    {len(docs)} documentos copiados")

    # 2. Atualiza usuarios: is_superuser=True -> role="master", outros -> role="operator"
    print("  Atualizando roles dos usuarios...")
    await target["users"].update_many(
        {"is_superuser": True},
        {"$set": {"role": "master"}, "$unset": {"is_superuser": ""}}
    )
    await target["users"].update_many(
        {"is_superuser": {"$exists": True}},
        {"$set": {"role": "operator"}, "$unset": {"is_superuser": ""}}
    )
    # Usuarios sem nenhum dos campos
    await target["users"].update_many(
        {"role": {"$exists": False}},
        {"$set": {"role": "operator"}}
    )

    # 3. Cria a org padrao no wmapp_admin
    print(f"  Criando org '{DEFAULT_ORG_SLUG}' no wmapp_admin...")
    from datetime import datetime
    existing = await admin["organizations"].find_one({"slug": DEFAULT_ORG_SLUG})
    if not existing:
        await admin["organizations"].insert_one({
            "name": DEFAULT_ORG_NAME,
            "slug": DEFAULT_ORG_SLUG,
            "master_email": "master@system.local",
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": None,
        })
        print(f"    Org '{DEFAULT_ORG_SLUG}' criada.")
    else:
        print(f"    Org '{DEFAULT_ORG_SLUG}' ja existe, pulando.")

    print()
    print("Migracao concluida.")
    print(f"  Database da org: {TARGET_DB}")
    print(f"  Database admin:  {ADMIN_DB}")
    print()
    print("PROXIMO PASSO: atualize o frontend para enviar org_slug='default' no login.")
    print("O database original '{SOURCE_DB}' NAO foi removido. Remova manualmente apos validar.")

    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
