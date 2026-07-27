"""
Utilitarios de seguranca: hashing de senhas e geracao de tokens JWT.
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha corresponde ao hash."""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def get_password_hash(password: str) -> str:
    """Gera hash bcrypt da senha."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Cria um token JWT com os dados fornecidos.

    Args:
        data: Dados a serem codificados no token (ex: {"sub": "username"})
        expires_delta: Tempo de expiracao customizado

    Returns:
        Token JWT como string
    """
    settings = get_settings()

    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm
    )

    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodifica e valida um token JWT.

    Args:
        token: Token JWT

    Returns:
        Payload decodificado ou None se invalido
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        return payload
    except JWTError:
        return None


def generate_temp_password() -> str:
    """
    Senha temporaria de primeiro acesso, gerada NO SERVIDOR.

    O master nao deve escolher (nem conhecer) a senha de outra pessoa: destroi a
    separacao de responsabilidade e, com o convite por email ativo, seria a senha
    dele viajando por email. Quem recebe e o proprio usuario, que e obrigado a
    troca-la no primeiro acesso (must_change_password).

    Formato legivel ao telefone — sem 0/O e 1/I/l, que se confundem quando alguem
    precisa ditar a senha.
    """
    import secrets
    alfabeto = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))
