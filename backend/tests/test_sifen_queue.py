"""
Testes da fila de emissão (queue.py) com provider FAKE. Precisam de MongoDB.
"""

import pytest
from requests.exceptions import ConnectionError as ReqConnError

from app.services.sifen import queue, lock, receptor
from app.models.sifen import SifenEmission, EmissionStatus


XML_OK = (b"<rDE><DE><gDatGralOpe><gDatRec><dNumDoc>0000121</dNumDoc></gDatRec>"
          b"</gDatGralOpe></DE><dProtAut>3364610579</dProtAut>"
          b"<dsig:Signature>x</dsig:Signature><dCarQR>https://qr</dCarQR></rDE>")


class FakeProvider:
    def __init__(self, *, sign_ok=True, xml=XML_OK, generar_raises=None):
        self.sign_ok = sign_ok
        self.xml = xml
        self.generar_raises = generar_raises
        self.calls = []

    def login(self): self.calls.append("login")
    def logout(self): self.calls.append("logout")
    def contribuyente(self, doc): return None            # não é contribuinte
    def ciudadano(self, doc):                            # cidadão comum, traz nome
        return {"razonSocial": "GASPAR FERNANDO AVANCO", "dv": None}
    def listar(self, *a, **k): return {"genericList": []}
    def generar(self, dte):
        self.calls.append("generar")
        if self.generar_raises:
            raise self.generar_raises
        return {"cdc": "01CDC", "proceso_id": "p1", "documento_id": "d1",
                "url_proceso": "https://sign.example/x"}
    def sign(self, url): self.calls.append("sign"); return self.sign_ok
    def guardar(self, p, d): self.calls.append("guardar"); return {"mensaje": "XML Aprobado"}
    def baixar_xml(self, cdc): self.calls.append("baixar_xml"); return self.xml


async def _novo_job(status=EmissionStatus.PROCESSANDO, rid="req-1") -> SifenEmission:
    job = SifenEmission(
        client_request_id=rid, created_by="op1", status=status,
        doc="7184730", nombre="GASPAR FERNANDO AVANCO", tipo_id=1,
        items=[{"descripcion": "AGUA", "cantidad": 1, "precio_unit": 150000,
                "tasa_iva": 10, "afectacion": 1}],
        condicion={"tipo": "contado", "forma_pago": {"codigo": 1, "desc": "Efectivo"}},
    )
    await job.insert()
    return job


async def _fake_creds():
    return ("12345678", "clave-test", "0000")


@pytest.mark.asyncio
async def test_emissao_feliz(test_db, monkeypatch):
    salvos = {}
    monkeypatch.setattr("app.services.sifen.queue.r2_put",
                        lambda k, b, c: salvos.update({k: b}))
    prov = FakeProvider()
    job = await _novo_job()
    await queue.processar_emissao(job, "coord-A",
                                  provider_factory=lambda *a: prov, load_creds=_fake_creds)
    assert job.status == EmissionStatus.EMITIDA
    assert job.cdc == "01CDC"
    assert job.numero_documento == "0000121"
    assert job.dprot_aut == "3364610579"
    assert job.xml_r2_key == "sifen/01CDC.xml"
    assert "sifen/01CDC.xml" in salvos
    assert prov.calls == ["login", "generar", "sign", "guardar", "baixar_xml", "logout"]
    # lock liberado no fim
    assert await lock.adquirir("outro") is True


@pytest.mark.asyncio
async def test_breaker_firma_falha_nao_guarda(test_db, monkeypatch):
    monkeypatch.setattr("app.services.sifen.queue.r2_put", lambda k, b, c: None)
    prov = FakeProvider(sign_ok=False)
    job = await _novo_job()
    await queue.processar_emissao(job, "coord-A",
                                  provider_factory=lambda *a: prov, load_creds=_fake_creds)
    assert job.status == EmissionStatus.FALHOU
    assert "breaker" in (job.error or "")
    assert "guardar" not in prov.calls        # NÃO guardou
    assert "logout" in prov.calls             # mas deslogou
    assert await lock.adquirir("outro") is True


@pytest.mark.asyncio
async def test_erro_de_rede_volta_pra_fila(test_db, monkeypatch):
    monkeypatch.setattr("app.services.sifen.queue.r2_put", lambda k, b, c: None)
    prov = FakeProvider(generar_raises=ReqConnError("timeout"))
    job = await _novo_job()
    await queue.processar_emissao(job, "coord-A",
                                  provider_factory=lambda *a: prov, load_creds=_fake_creds)
    assert job.status == EmissionStatus.PENDENTE  # auto-retry
    assert await lock.adquirir("outro") is True


@pytest.mark.asyncio
async def test_lock_ocupado_volta_pra_fila(test_db, monkeypatch):
    monkeypatch.setattr("app.services.sifen.queue.r2_put", lambda k, b, c: None)
    # outro coordenador já detém a sessão
    assert await lock.adquirir("coord-B") is True
    prov = FakeProvider()
    job = await _novo_job()
    await queue.processar_emissao(job, "coord-A",
                                  provider_factory=lambda *a: prov, load_creds=_fake_creds)
    assert job.status == EmissionStatus.PENDENTE
    assert prov.calls == []  # nem chegou a logar


@pytest.mark.asyncio
async def test_claim_next_atomico(test_db):
    j1 = await _novo_job(status=EmissionStatus.PENDENTE)
    claimed = await queue.claim_next("coord-A")
    assert claimed is not None and claimed.id == j1.id
    assert claimed.status == EmissionStatus.PROCESSANDO
    assert claimed.locked_by == "coord-A"
    # telemetria
    assert claimed.started_at is not None
    assert claimed.queue_depth_at_start >= 1
    # fila vazia agora
    assert await queue.claim_next("coord-A") is None


@pytest.mark.asyncio
async def test_claim_for_device_nunca_duas_sessoes(test_db):
    await _novo_job(status=EmissionStatus.PENDENTE, rid="r1")
    await _novo_job(status=EmissionStatus.PENDENTE, rid="r2")
    # device A pega o job E retém o lock de sessão
    jA = await queue.claim_for_device("dev-A")
    assert jA is not None
    # device B NÃO pega nada enquanto A tem a sessão (mesmo com job pendente)
    assert await queue.claim_for_device("dev-B") is None
    # A conclui e libera a sessão
    await queue.release_sessao("dev-A")
    # agora B pega o próximo (job diferente)
    jB = await queue.claim_for_device("dev-B")
    assert jB is not None and jB.id != jA.id


@pytest.mark.asyncio
async def test_claim_for_device_fila_vazia_solta_sessao(test_db):
    # fila vazia: pega o lock, não acha job, devolve a sessão
    assert await queue.claim_for_device("dev-A") is None
    # sessão foi liberada → outro consegue o lock
    assert await lock.adquirir("dev-B") is True
