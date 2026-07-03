"""
Tradução de erros técnicos para mensagens amigáveis ao usuário.

Regra: nunca jogar URL, traceback, WinError ou status code cru na tela.
- Erros de negócio do backend (4xx com mensagem útil em espanhol) são exibidos
  como vieram (ex.: "Saldo insuficiente").
- Conexão (status 0), 401/403, 5xx e exceções inesperadas viram mensagem genérica.
"""
from __future__ import annotations

from i18n import t


def friendly_error(err: Exception, *, fallback_key: str = "error.unexpected") -> str:
    """Mensagem amigável (es/pt) para qualquer exceção vinda da API/serviços."""
    # Import tardio para evitar ciclo (api_client importa pouco, mas por segurança).
    try:
        from services.api_client import APIError
    except Exception:
        APIError = None  # type: ignore

    if APIError is not None and isinstance(err, APIError):
        code = getattr(err, "status_code", None)
        detail = (getattr(err, "detail", "") or "").strip()

        if code in (0, None) or detail == "connection_failed":
            return t("error.no_connection")
        if code == 401:
            return t("error.unauthorized")
        if code == 403:
            return t("error.forbidden")
        if code == 404:
            return t("error.not_found")
        if code >= 500:
            return t("error.server")
        # 4xx restantes (400/409/422...): o detalhe costuma ser uma mensagem de
        # negócio já em espanhol vinda do backend — exibe se existir e for legível.
        if detail and detail != "connection_failed":
            return detail
        return t(fallback_key)

    # Exceção não-API (ex.: erro local de impressão/arquivo).
    return t(fallback_key)
