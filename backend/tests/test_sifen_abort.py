"""
Desistência da emissão ANTES da firma + número da factura (routers/sifen.py).

A regra que importa: enquanto o documento não foi assinado ele não existe para o
SET e dá para largar o job; depois da firma a única saída é a cancelación fiscal.
"""

import pytest

from app.models.sifen import SifenEmission, EmissionStatus, EmissionFase
from app.routers.sifen import numero_formateado
from app.services.sifen import queue

from tests.test_sifen_queue import FakeProvider, _fake_creds, _novo_job


# CDC real tem 44 dígitos: tipo(2) ruc(8) dv(1) est(3) punto(3) numero(7) …
CDC_44 = "01" + "80012345" + "6" + "001" + "002" + "0000123" + "1" + "20260727" + "1" + "123456789" + "4"


def test_numero_formateado_sai_do_cdc():
    assert len(CDC_44) == 44
    assert numero_formateado(CDC_44) == "001-002-0000123"


def test_numero_formateado_cai_no_dnumdoc_fora_do_formato():
    assert numero_formateado("01CDC", "0000121") == "0000121"
    assert numero_formateado(None, None) is None


@pytest.mark.asyncio
async def test_job_abortado_nao_e_servido_ao_coordenador(test_db):
    job = await _novo_job(status=EmissionStatus.PENDENTE, rid="abort-fila")
    job.abort_solicitado = True
    await job.save()

    assert await queue.claim_next("coord-A") is None


@pytest.mark.asyncio
async def test_abort_antes_da_firma_nao_assina_nem_guarda(test_db, monkeypatch):
    """O pedido chega enquanto o coordenador trabalha: para antes de `sign`."""
    monkeypatch.setattr("app.services.sifen.queue.r2_put", lambda k, b, c: None)
    prov = FakeProvider()
    job = await _novo_job(rid="abort-meio")

    # simula o operador clicando «Cancelar» logo depois de `generar`
    await SifenEmission.get_pymongo_collection().update_one(
        {"_id": job.id}, {"$set": {"abort_solicitado": True}})

    await queue.processar_emissao(job, "coord-A",
                                  provider_factory=lambda *a: prov, load_creds=_fake_creds)

    assert job.status == EmissionStatus.ABORTADA
    assert "sign" not in prov.calls and "guardar" not in prov.calls
    assert job.numero_documento is None
    assert "logout" in prov.calls   # a sessão do portal é sempre fechada


@pytest.mark.asyncio
async def test_sem_abort_a_emissao_segue_normal(test_db, monkeypatch):
    monkeypatch.setattr("app.services.sifen.queue.r2_put", lambda k, b, c: None)
    prov = FakeProvider()
    job = await _novo_job(rid="sem-abort")

    await queue.processar_emissao(job, "coord-A",
                                  provider_factory=lambda *a: prov, load_creds=_fake_creds)

    assert job.status == EmissionStatus.EMITIDA
    assert "sign" in prov.calls and "guardar" in prov.calls


@pytest.mark.asyncio
async def test_fase_firmar_fecha_a_janela_de_desistencia(test_db):
    """Depois de FIRMAR o endpoint recusa — é o que a UI usa para esconder o botão."""
    from app.models.sifen import FASES_ABORTAVEIS

    assert EmissionFase.GENERAR in FASES_ABORTAVEIS
    assert None in FASES_ABORTAVEIS
    assert EmissionFase.FIRMAR not in FASES_ABORTAVEIS
    assert EmissionFase.RECUPERAR not in FASES_ABORTAVEIS
