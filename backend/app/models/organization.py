"""
Modelo de Organizacao (Junta de Saneamento).

Armazenado no database wmapp_admin.
Cada org tem seu proprio database: wmapp_{slug}
"""

from datetime import datetime
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field


class Organization(Document):
    """
    Representa uma junta de saneamento cadastrada na plataforma.
    Os campos usam alias camelCase para mapear o formato gerado pelo admin-api (Node.js).
    """

    name: str
    slug: Indexed(str, unique=True)
    master_email: str = Field(alias="masterEmail")
    is_active: bool = Field(default=True, alias="isActive")

    # Connection string criptografada com AES-256 pelo admin-api
    # Formato: "{iv_hex}:{data_hex}"
    connection_string: Optional[str] = Field(default=None, alias="connectionString")

    deleted_at: Optional[datetime] = Field(default=None, alias="deletedAt")

    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")

    class Settings:
        name = "organizations"

    model_config = {"populate_by_name": True}

    @property
    def database_name(self) -> str:
        return f"wmapp_{self.slug}"
