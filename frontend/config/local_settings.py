"""
WMApp Frontend - Configurações Locais
Gerencia preferências persistidas no arquivo preferences.json
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _preferences_path() -> Path:
    """Caminho do preferences.json.

    Empacotado (PyInstaller) → grava em %APPDATA%\\JuntaCRM (pasta gravável do
    usuário). Senão o arquivo cairia em Program Files\\...\\_internal\\, que é
    somente-leitura e causa 'Permission denied'.

    Em desenvolvimento mantém o histórico: ao lado do código.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
        data_dir = Path(base) / "JuntaCRM"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return data_dir / "preferences.json"
    return Path(__file__).parent.parent / "preferences.json"


PREFERENCES_FILE = _preferences_path()

DEFAULT_PREFERENCES = {
    # URL do backend. Em produção, configure via preferences.json / painel de ajustes.
    "api_base_url": "http://localhost:8000",
    "printer_thermal": None,
    "printer_a4": None,
    "theme": "dark",
    "language": "es",
    "org_slug": "",
    # Formato de impressão das faturas: "p80" (térmica, padrão) ou "a4".
    "invoice_print_format": "p80",
}


def load_preferences() -> dict:
    """Carrega preferências do arquivo local."""
    if PREFERENCES_FILE.exists():
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_PREFERENCES, **json.load(f)}
        except (json.JSONDecodeError, IOError):
            return DEFAULT_PREFERENCES.copy()
    return DEFAULT_PREFERENCES.copy()


def save_preferences(prefs: dict) -> None:
    """Salva preferências no arquivo local."""
    current = load_preferences()
    current.update(prefs)
    try:
        PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=4, ensure_ascii=False)


def get_api_url() -> str:
    """Retorna URL base da API."""
    return load_preferences().get("api_base_url", DEFAULT_PREFERENCES["api_base_url"])


def get_invoice_print_format() -> str:
    """Formato de impressão das faturas: 'p80' (padrão) ou 'a4'."""
    val = load_preferences().get("invoice_print_format", "p80")
    return val if val in ("p80", "a4") else "p80"


def set_invoice_print_format(fmt: str) -> None:
    save_preferences({"invoice_print_format": fmt if fmt in ("p80", "a4") else "p80"})


def get_printer(printer_type: str) -> Optional[str]:
    """Retorna impressora configurada (thermal ou a4)."""
    key = f"printer_{printer_type}"
    return load_preferences().get(key)


def set_printer(printer_type: str, printer_name: Optional[str]) -> None:
    """Define impressora (thermal ou a4)."""
    save_preferences({f"printer_{printer_type}": printer_name})



def get_theme() -> str:
    """Retorna tema (dark/light)."""
    return load_preferences().get("theme", "dark")


def get_token() -> Optional[str]:
    """Retorna token JWT salvo."""
    return load_preferences().get("auth_token")


def set_token(token: Optional[str]) -> None:
    """Salva token JWT localmente."""
    save_preferences({"auth_token": token})


def get_org_slug() -> str:
    """Retorna org_slug salvo."""
    return load_preferences().get("org_slug", "")


def set_org_slug(slug: str) -> None:
    """Salva org_slug localmente."""
    save_preferences({"org_slug": slug})


def get_mapbox_tile_url() -> str:
    """Retorna URL template de tiles via proxy backend (controla concorrência e faz cache)."""
    base = get_api_url().rstrip("/")
    return f"{base}/map/tiles/{{z}}/{{x}}/{{y}}"
