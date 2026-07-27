"""
Testes do backup/restore lógico (funções puras dump_database / load_database).

Round-trip real contra o Mongo de teste: dump → apaga tudo → restore → confere
que os dados (incluindo Decimal128) voltaram idênticos. "Backup que nunca foi
restaurado não é backup" — este teste é justamente a restauração.
"""

import gzip
from decimal import Decimal

import pytest
from bson import json_util

from app.models.client import Client, ClientCategory, ClientStatus
from app.models.invoice import Invoice
from app.services.backup import dump_database, load_database


@pytest.mark.asyncio
async def test_dump_e_gzip_com_meta(test_db, sample_client):
    blob = await dump_database(test_db)
    assert blob[:2] == b"\x1f\x8b"  # magic gzip
    payload = json_util.loads(gzip.decompress(blob).decode("utf-8"))
    assert "clients" in payload["data"]
    names = [c["name"] for c in payload["_meta"]["collections"]]
    assert "clients" in names


@pytest.mark.asyncio
async def test_backup_restore_roundtrip(test_db, sample_client, multiple_invoices):
    blob = await dump_database(test_db)

    # apaga tudo (simula perda de dados)
    for name in await test_db.list_collection_names():
        await test_db[name].delete_many({})
    assert await Client.find_all().count() == 0

    # restaura a partir do backup
    res = await load_database(test_db, blob)
    assert res.get("clients", 0) == 1
    assert res.get("invoices", 0) == 3

    # valores preservados (nome + Decimal128 dos saldos)
    c = await Client.find_one(Client.ci_ruc == "1234567")
    assert c is not None and c.nombre_completo == "Juan Perez"
    invs = await Invoice.find_all().to_list()
    assert len(invs) == 3
    assert sum(i.saldo_devedor for i in invs) == Decimal("83000")  # 25000+30000+28000


@pytest.mark.asyncio
async def test_restore_substitui_estado_atual(test_db, sample_client):
    """restore (drop_existing) traz o estado do backup, descartando mudanças posteriores."""
    blob = await dump_database(test_db)  # snapshot com 1 cliente

    extra = Client(
        nombre_completo="Añadido Después", ci_ruc="9999999", direccion="X",
        categoria=ClientCategory.RESIDENCIAL, status=ClientStatus.ATIVO,
    )
    await extra.insert()
    assert await Client.find_all().count() == 2

    await load_database(test_db, blob)  # restore → volta ao snapshot (1 cliente)
    assert await Client.find_all().count() == 1
    assert await Client.find_one(Client.ci_ruc == "9999999") is None
