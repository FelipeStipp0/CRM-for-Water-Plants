"""
Modelo de Usuario para autenticacao e controle de acesso.

Fluxo de Primeiro Acesso:
- Todo usuario criado tem must_change_password = True
- Login retorna token com escopo restrito se must_change_password = True
- Frontend deve forcar tela de "Nova Senha" antes de liberar acesso

Roles:
- master: admin da org, gerencia usuarios e configuracoes
- operator: usuario comum, permissoes controladas por scopes
"""

from datetime import datetime
from typing import Optional, List, Literal
from beanie import Document, Indexed
from pydantic import Field


class User(Document):
    """Usuario do sistema com credenciais de acesso."""

    username: Indexed(str, unique=True)
    email: Indexed(str, unique=True)
    hashed_password: str
    full_name: str

    is_active: bool = True

    role: Literal["master", "operator"] = "operator"
    must_change_password: bool = True
    scopes: List[str] = Field(default_factory=list)

    # Perfil
    phone: Optional[str] = None
    position: Optional[str] = None          # cargo: "Presidente", "Tesorero", etc.
    language: Literal["es", "pt"] = "es"
    avatar_base64: Optional[str] = None
    avatar_mime: Optional[str] = None       # "image/png", "image/jpeg"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "users"
        use_state_management = True

    def __repr__(self) -> str:
        return f"User(username={self.username}, email={self.email})"

    @classmethod
    async def ensure_master(cls) -> None:
        """
        Garante que existe usuario master no banco da org.
        Chamado no startup de cada org.
        """
        from app.utils.security import get_password_hash

        existing = await cls.find_one(cls.username == "master")
        if not existing:
            master = cls(
                username="master",
                email="master@system.local",
                hashed_password=get_password_hash("master"),
                full_name="Master",
                role="master",
                must_change_password=True,
                scopes=["*"],
            )
            await master.insert()
