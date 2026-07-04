"""
AES-256-CBC encrypt/decrypt — espelho do admin-api/src/utils/crypto.ts.
Formato do campo: "{iv_hex}:{data_hex}"
"""

import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


def decrypt_connection_string(encrypted: str, key_hex: str) -> str:
    """
    Decripta uma connection string criptografada pelo admin-api.
    key_hex: chave AES-256 em hexadecimal (64 chars = 32 bytes).
    """
    iv_hex, data_hex = encrypted.split(":", 1)
    iv = bytes.fromhex(iv_hex)
    data = bytes.fromhex(data_hex)
    key = bytes.fromhex(key_hex)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(data) + decryptor.finalize()

    # Remove PKCS7 padding
    pad_len = padded[-1]
    return padded[:-pad_len].decode("utf-8")


def encrypt(plain: str, key_hex: str) -> str:
    """
    Cifra uma string com AES-256-CBC no mesmo formato "{iv_hex}:{data_hex}"
    (par de decrypt_connection_string). key_hex: 64 chars = 32 bytes.
    """
    key = bytes.fromhex(key_hex)
    iv = os.urandom(16)
    raw = plain.encode("utf-8")
    pad_len = 16 - (len(raw) % 16)
    padded = raw + bytes([pad_len]) * pad_len

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    data = encryptor.update(padded) + encryptor.finalize()
    return f"{iv.hex()}:{data.hex()}"


def decrypt(encrypted: str, key_hex: str) -> str:
    """Alias explícito de decrypt_connection_string (mesmo formato {iv}:{data})."""
    return decrypt_connection_string(encrypted, key_hex)
