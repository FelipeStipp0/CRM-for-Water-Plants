"""
Schemas para autenticacao e usuarios.
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=2, max_length=100)
    role: Literal["master", "operator"] = "operator"
    scopes: list[str] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    is_active: bool
    role: Literal["master", "operator"]
    must_change_password: bool
    scopes: list[str]
    phone: Optional[str] = None
    position: Optional[str] = None
    language: Literal["es", "pt"] = "es"
    avatar_base64: Optional[str] = None
    avatar_mime: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=30)
    position: Optional[str] = Field(None, max_length=100)
    language: Optional[Literal["es", "pt"]] = None


class Token(BaseModel):
    """
    Token JWT retornado no login.

    Campos importantes para frontend:
    - must_change_password: se True, forcar tela de troca de senha
    - role: master ou operator
    - org_slug: slug da org autenticada
    """
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    scopes: list[str] = Field(default_factory=list)
    role: Literal["master", "operator"] = "operator"
    org_slug: str = ""


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6)


class TokenData(BaseModel):
    username: Optional[str] = None
    org: Optional[str] = None
    role: Optional[str] = None
