"""
Titular + suas ligações. Precisa de MongoDB.

O que importa aqui é o agrupamento: uma pessoa, várias casas, cada casa ainda
sendo um cliente próprio (medidor/fatura/corte).
"""

import pytest

from app.models.client import Client
from app.models.titular import Titular


async def _titular(nome="Reginaldo", doc="3773145-9") -> Titular:
    t = Titular(nombre_completo=nome, ci_ruc=doc, celular="0983511962")
    await t.insert()
    return t


async def _ligacao(t: Titular, nome: str, manzana="13", lote="13") -> Client:
    c = Client(
        nombre_completo=nome, ci_ruc=t.ci_ruc, direccion="Calle test 123",
        manzana=manzana, lote=lote, titular_id=t.id, celular=t.celular,
    )
    await c.insert()
    return c


@pytest.mark.asyncio
async def test_titular_agrupa_varias_ligacoes(test_db):
    t = await _titular()
    for n in ("Casa 01", "Casa 02", "Casa 03"):
        await _ligacao(t, f"Reginaldo - {n}")

    ligacoes = await Client.find(Client.titular_id == t.id).to_list()
    assert len(ligacoes) == 3
    # cada uma continua sendo um cliente independente
    assert len({c.id for c in ligacoes}) == 3
    assert all(c.ci_ruc == t.ci_ruc for c in ligacoes)


@pytest.mark.asyncio
async def test_ligacao_sem_titular_continua_valida(test_db):
    """O titular é opcional: ligação avulsa não pode quebrar."""
    c = Client(nombre_completo="Avulso", ci_ruc="1234567",
               direccion="Calle sin titular 1")
    await c.insert()
    assert c.titular_id is None
    assert await Client.find(Client.titular_id == None).count() >= 1  # noqa: E711


@pytest.mark.asyncio
async def test_documento_repetido_e_permitido(test_db):
    """
    Regra de negócio: o mesmo documento aparece em várias ligações (um dono com
    cinco casas) e em pessoas diferentes (todas as que usam o RUC ocasional).
    Se voltar a haver índice único em ci_ruc, este teste quebra.
    """
    t = await _titular()
    await _ligacao(t, "Casa A")
    await _ligacao(t, "Casa B")
    assert await Client.find(Client.ci_ruc == t.ci_ruc).count() == 2

    ocasional = "44444401-7"
    for nome in ("Sin doc 1", "Sin doc 2"):
        await Client(nombre_completo=nome, ci_ruc=ocasional,
                     direccion="Calle ocasional 1").insert()
    assert await Client.find(Client.ci_ruc == ocasional).count() == 2
