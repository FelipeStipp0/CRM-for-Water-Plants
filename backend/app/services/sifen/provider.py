"""
Interface do provider de facturación electrónica (a costura).

O código público depende SÓ desta interface. O adapter concreto — que carrega as
URLs reais do portal e a máquina de estados da assinatura — mora num módulo à parte
(versionado fora do repo público) e é carregado dinamicamente por `get_provider`.
Se o adapter não estiver instalado, a emissão fica simplesmente desabilitada.

Convenção do adapter externo: um módulo importável cujo caminho vem de
`settings.sifen_provider` (default: "app.services.sifen._adapter"), expondo
`def build_provider(ruc, clave, pin) -> SifenProvider`.
"""

from importlib import import_module
from typing import Optional, Protocol, runtime_checkable

from app.config import get_settings


@runtime_checkable
class SifenProvider(Protocol):
    """Contrato mínimo que o adapter concreto do portal deve cumprir."""

    def login(self) -> None: ...
    def keep(self) -> None: ...
    def logout(self) -> None: ...

    def contribuyente(self, ruc: str) -> Optional[dict]:
        """Lookup de nome/DV do contribuinte (RUC). None se não for contribuinte."""
        ...

    def ciudadano(self, doc: str) -> Optional[dict]:
        """Lookup de cidadão comum por cédula (traz o nome). None se não achar."""
        ...

    def es_oee(self, ruc: str) -> bool:
        """True se o RUC é Organismo/Entidad del Estado (OEE) — habilita B2G."""
        ...

    def generar(self, dte: dict) -> dict:
        """Gera o DTE. Retorna {cdc, proceso_id, documento_id, url_proceso}."""
        ...

    def sign(self, url_proceso: str) -> bool:
        """Executa a assinatura. True = concluída; False = breaker (NÃO guardar)."""
        ...

    def guardar(self, proceso_id: str, documento_id: str) -> dict:
        """Finaliza a emissão após assinar."""
        ...

    def baixar_xml(self, cdc: str) -> bytes:
        """XML assinado (com dsig + dCarQR) por CDC."""
        ...

    def cancelar(self, cdc: str, motivo: str) -> dict: ...

    def listar(self, filtros: Optional[dict] = None, inicio: int = 0,
               cantidad: int = 50) -> dict: ...


class ProviderNaoInstalado(RuntimeError):
    """O adapter concreto do portal não está disponível neste ambiente."""


def _provider_module_path() -> str:
    return getattr(get_settings(), "sifen_provider", "") or "app.services.sifen._adapter"


def provider_disponivel() -> bool:
    try:
        import_module(_provider_module_path())
        return True
    except ImportError:
        return False


def get_provider(ruc: str, clave: str, pin: str) -> SifenProvider:
    """
    Instancia o provider concreto (adapter externo). Levanta ProviderNaoInstalado
    se o módulo não estiver presente — a emissão fica desabilitada sem quebrar o app.
    """
    path = _provider_module_path()
    try:
        mod = import_module(path)
    except ImportError as e:
        raise ProviderNaoInstalado(
            f"Adapter de facturación electrónica ausente ({path}). "
            "A emissão está desabilitada até instalá-lo."
        ) from e
    if not hasattr(mod, "build_provider"):
        raise ProviderNaoInstalado(
            f"Módulo {path} não expõe build_provider(ruc, clave, pin)."
        )
    return mod.build_provider(ruc, clave, pin)
