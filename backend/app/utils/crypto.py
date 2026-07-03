"""
AES-256-CBC decrypt — espelho do admin-api/src/utils/crypto.ts.
Formato do campo: "{iv_hex}:{data_hex}"
"""

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
