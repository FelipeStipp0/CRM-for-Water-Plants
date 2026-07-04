"""
Credenciais cifradas do portal (clave + PIN de assinatura), por org.

Guardadas em AES-256 no banco da org (mesma ENCRYPTION_KEY do projeto). O PIN em
claro só deve viver em memória do coordenador durante o lote (1×/dia).
"""

from typing import Tuple

from app.config import get_settings
from app.utils import crypto
from app.models.sifen import SifenCredential


def _key() -> str:
    return get_settings().encryption_key  # hex de 64 chars


async def salvar_credenciais(ruc: str, clave: str, pin: str) -> None:
    key = _key()
    cred = await SifenCredential.find_one(SifenCredential.key == "default")
    if cred is None:
        cred = SifenCredential(ruc=ruc, clave_enc="", pin_enc="")
    cred.ruc = ruc
    cred.clave_enc = crypto.encrypt(clave, key)
    cred.pin_enc = crypto.encrypt(pin, key)
    await cred.save()


async def carregar_credenciais() -> Tuple[str, str, str]:
    """Retorna (ruc, clave, pin) em claro. Levanta se não configurado."""
    cred = await SifenCredential.find_one(SifenCredential.key == "default")
    if cred is None:
        raise RuntimeError("Credenciais SIFEN não configuradas para esta org.")
    key = _key()
    return cred.ruc, crypto.decrypt(cred.clave_enc, key), crypto.decrypt(cred.pin_enc, key)
