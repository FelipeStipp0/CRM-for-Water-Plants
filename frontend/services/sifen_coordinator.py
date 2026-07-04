from __future__ import annotations

"""
WMApp Frontend - Coordenador de emissão SIFEN.

Roda em background (thread). Anuncia o dispositivo, faz poll no backend e, quando
recebe um job (gateado por sessão — jamais duas sessões), executa a emissão LOCAL
(via `executor`) e devolve o resultado com telemetria de tempo. Invisível ao operador.

O `executor` é plugável (recebe o job, faz as chamadas ao portal e devolve os campos
do SET). Isso mantém o loop independente do adapter/pipeline.
"""

import threading
import time
import traceback
from typing import Callable, Optional

from services.api_client import APIError
from services.sifen_service import sifen_service
from config.local_settings import get_machine_id, get_device_label


# executor(job: dict) -> dict com {cdc, numero_documento, dprot_aut, xml_r2_key, phases_ms?}
# deve levantar exceção em falha (vira FALHOU).
Executor = Callable[[dict], dict]

POLL_IDLE = 2.0        # sem job: intervalo de poll
POLL_BUSY = 0.1        # logo após emitir: drena a fila rápido (emissão imediata)
BACKOFF_ERRO = 5.0     # erro de rede/backend
BACKOFF_NEGADO = 30.0  # PC não permitido / não logado


class SifenCoordinator:
    def __init__(self, executor: Executor, log: Optional[Callable[[str], None]] = None):
        self._executor = executor
        self._log = log or (lambda m: print(f"[sifen-coord] {m}", flush=True))
        self._machine_id = get_machine_id()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._announced = False

    # ---------- ciclo de vida ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sifen-coordinator", daemon=True)
        self._thread.start()
        self._log(f"iniciado (machine_id={self._machine_id[:8]})")

    def stop(self) -> None:
        self._stop.set()

    # ---------- loop ----------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self._announced:
                    sifen_service.announce(self._machine_id, get_device_label())
                    self._announced = True

                job = sifen_service.poll(self._machine_id)
                if not job:
                    self._wait(POLL_IDLE)
                    continue

                self._processar(job)
                self._wait(POLL_BUSY)  # tenta pegar o próximo já

            except APIError as e:
                # 401 = não logado; 403 = PC não permitido → recua mais
                status = getattr(e, "status", None) or getattr(e, "status_code", None)
                self._announced = self._announced and status not in (401,)
                self._wait(BACKOFF_NEGADO if status in (401, 403) else BACKOFF_ERRO)
            except Exception as e:  # noqa: BLE001
                self._log(f"loop error: {e}")
                self._wait(BACKOFF_ERRO)

    def _processar(self, job: dict) -> None:
        emission_id = job["id"]
        t0 = time.perf_counter()
        payload: dict
        try:
            result = self._executor(job)  # emissão local (portal)
            payload = {
                "status": "EMITIDA",
                "cdc": result.get("cdc"),
                "numero_documento": result.get("numero_documento"),
                "dprot_aut": result.get("dprot_aut"),
                "xml_r2_key": result.get("xml_r2_key"),
                "phases_ms": result.get("phases_ms"),
            }
            self._log(f"emitida {payload.get('numero_documento')} (cdc …{(payload.get('cdc') or '')[-6:]})")
        except Exception as e:  # noqa: BLE001
            payload = {"status": "FALHOU", "error": f"{type(e).__name__}: {e}"}
            self._log(f"falhou {emission_id}: {e}\n{traceback.format_exc()}")

        payload["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        # PATCH libera a sessão no backend (status terminal)
        try:
            sifen_service.patch_result(emission_id, {k: v for k, v in payload.items() if v is not None})
        except Exception as e:  # noqa: BLE001
            self._log(f"patch falhou {emission_id}: {e}")

    def _wait(self, secs: float) -> None:
        self._stop.wait(secs)


# instância única do coordenador (ligada ao executor real). Inicie após o login.
_instance: Optional["SifenCoordinator"] = None


def get_coordinator() -> "SifenCoordinator":
    """Coordenador com o executor real (emissão local). Lazy p/ evitar ciclo de import."""
    global _instance
    if _instance is None:
        from services.sifen_executor import emitir_job
        _instance = SifenCoordinator(emitir_job)
    return _instance
