"""
Testes da cancelación fiscal (evento sobre um DTE já emitido). Precisam de MongoDB.

Regra central: anular o pagamento no CRM não cancela o documento no SET — só
SOLICITA. O `status` continua EMITIDA até o portal aceitar o evento.
"""

import pytest
from requests.exceptions import ConnectionError as ReqConnError

from app.services.sifen import queue, lock
from app.models.sifen import SifenEmission, EmissionStatus


class FakeProvider:
    def __init__(self, *, cancelar_raises=None):
        self.cancelar_raises = cancelar_raises
        self.calls = []

    def login(self): self.calls.append("login")
    def logout(self): self.calls.append("logout")

    def cancelar(self, cdc, motivo):
        self.calls.append(("cancelar", cdc, motivo))
        if self.cancelar_raises:
            raise self.cancelar_raises
        return {"mensaje": "Cancelación registrada"}


async def _emitida(rid="req-c1", cdc="01CDC", payment_id=None) -> SifenEmission:
    job = SifenEmission(
        client_request_id=rid, created_by="op1", status=EmissionStatus.EMITIDA,
        doc="7184730", tipo_id=1, cdc=cdc, numero_documento="0000121",
        items=[{"descripcion": "AGUA", "cantidad": 1, "precio_unit": 150000,
                "tasa_iva": 10, "afectacion": 1}],
        condicion={"tipo": "contado", "forma_pago": {"codigo": 1, "desc": "Efectivo"}},
        payment_id=payment_id,
    )
    await job.insert()
    return job


async def _fake_creds():
    return ("12345678", "clave-test", "0000")


@pytest.mark.asyncio
async def test_solicitar_marca_sem_cancelar_no_set(test_db):
    job = await _emitida()
    await queue.solicitar_cancelacion(job, "Anulación de pago: cobro duplicado", "admin")

    assert job.cancel_solicitada is True
    assert job.cancel_solicitada_por == "admin"
    assert job.cancel_solicitada_at is not None
    # o documento SEGUE emitido: quem cancela é o coordenador, depois
    assert job.status == EmissionStatus.EMITIDA
    assert job.cancelada_at is None


@pytest.mark.asyncio
async def test_solicitar_exige_emitida(test_db):
    job = await _emitida(rid="req-c-pend")
    job.status = EmissionStatus.PENDENTE
    await job.save()
    with pytest.raises(queue.EmissionError):
        await queue.solicitar_cancelacion(job, "motivo cualquiera", "admin")


@pytest.mark.asyncio
async def test_cancelacion_feliz(test_db):
    job = await _emitida(rid="req-c2")
    await queue.solicitar_cancelacion(job, "Anulación de pago: error de monto", "admin")
    claimed = await queue.claim_next_cancelacion("coord-A")
    assert claimed is not None and claimed.id == job.id
    assert claimed.cancel_locked_by == "coord-A"

    prov = FakeProvider()
    await queue.processar_cancelacion(claimed, "coord-A",
                                      provider_factory=lambda *a: prov, load_creds=_fake_creds)

    assert claimed.status == EmissionStatus.CANCELADA
    assert claimed.cancelada_at is not None
    assert claimed.cancel_error is None
    assert claimed.cancel_locked_by is None
    assert prov.calls[0] == "login" and prov.calls[-1] == "logout"
    assert ("cancelar", "01CDC", "Anulación de pago: error de monto") in prov.calls
    assert await lock.adquirir("outro") is True   # sessão liberada


@pytest.mark.asyncio
async def test_erro_de_rede_volta_pra_fila(test_db):
    job = await _emitida(rid="req-c3")
    await queue.solicitar_cancelacion(job, "Anulación de pago", "admin")
    claimed = await queue.claim_next_cancelacion("coord-A")

    prov = FakeProvider(cancelar_raises=ReqConnError("timeout"))
    await queue.processar_cancelacion(claimed, "coord-A",
                                      provider_factory=lambda *a: prov, load_creds=_fake_creds)

    assert claimed.status == EmissionStatus.EMITIDA   # não cancelou
    assert claimed.cancel_error is None               # rede não vira erro de negócio
    assert claimed.cancel_locked_by is None
    # volta a ser reivindicável (auto-retry)
    assert (await queue.claim_next_cancelacion("coord-B")) is not None


@pytest.mark.asyncio
async def test_erro_de_negocio_sai_da_fila_e_retenta_sob_pedido(test_db):
    job = await _emitida(rid="req-c4")
    await queue.solicitar_cancelacion(job, "Anulación de pago", "admin")
    claimed = await queue.claim_next_cancelacion("coord-A")

    prov = FakeProvider(cancelar_raises=ValueError("plazo de cancelación vencido"))
    await queue.processar_cancelacion(claimed, "coord-A",
                                      provider_factory=lambda *a: prov, load_creds=_fake_creds)

    assert claimed.status == EmissionStatus.EMITIDA
    assert "plazo" in (claimed.cancel_error or "")
    # não se repete sozinho
    assert await queue.claim_next_cancelacion("coord-B") is None
    # pedir de novo limpa o erro e devolve à fila
    await queue.solicitar_cancelacion(claimed, "Anulación de pago (2º intento)", "admin")
    assert claimed.cancel_error is None
    assert (await queue.claim_next_cancelacion("coord-B")) is not None


@pytest.mark.asyncio
async def test_emissao_tem_prioridade_sobre_cancelacion(test_db):
    """Quem espera na emissão é o cliente no balcão."""
    cancelar = await _emitida(rid="req-c5")
    await queue.solicitar_cancelacion(cancelar, "Anulación de pago", "admin")

    pendente = SifenEmission(
        client_request_id="req-nova", created_by="op1", status=EmissionStatus.PENDENTE,
        doc="7184730", tipo_id=1, items=[], condicion={},
    )
    await pendente.insert()

    servido = await queue.claim_for_device("dev-A")
    assert servido is not None and servido.id == pendente.id
    await queue.release_sessao("dev-A")

    servido2 = await queue.claim_for_device("dev-A")
    assert servido2 is not None and servido2.id == cancelar.id
