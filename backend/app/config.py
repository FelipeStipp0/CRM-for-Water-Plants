"""
Configuracoes centralizadas da aplicacao.
Carrega variaveis de ambiente e define valores padrao.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuracoes da aplicacao carregadas do ambiente."""

    # Ambiente
    environment: str = "development"

    # MongoDB
    mongodb_url: str = "mongodb://127.0.0.1:27017"
    database_name: str = "wmapp"

    # Chave AES-256 compartilhada com admin-api (hex, 64 chars = 32 bytes)
    encryption_key: str = ""

    # JWT
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 horas

    # Cloudflare R2 (S3-compatible storage)
    r2_endpoint: str = ""
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url: str = ""

    # Mapbox (tile proxy)
    mapbox_token: str = ""
    mapbox_username: str = "mapbox"
    mapbox_style: str = "streets-v12"

    # WhatsApp Cloud API
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    # Facturación electrónica (SIFEN) — o adapter concreto e a base do endpoint
    # ficam FORA do repo público; vêm por env (.env). Se vazios, emissão desabilitada.
    sifen_provider: str = ""   # ex.: "app.services.sifen._adapter" (módulo externo via junction)
    sifen_base: str = ""       # base URL do portal (usada só pelo adapter externo)

    # App
    debug: bool = True
    app_name: str = "Saneo API"
    app_version: str = "1.0.0"
    cors_origins: str = "http://localhost:8550,http://127.0.0.1:8550,http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Retorna lista de origens CORS a partir da string configurada."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """Indica se a aplicacao esta em modo producao."""
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def validate_security_settings(self):
        """
        Valida configuracoes de seguranca.

        Em producao, impede uso da chave JWT padrao de desenvolvimento.
        """
        default_secret = "dev-secret-key-change-in-production"
        if self.is_production and self.secret_key == default_secret:
            raise ValueError(
                "SECRET_KEY padrao nao pode ser usada em producao. Defina SECRET_KEY no ambiente."
            )
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Retorna instancia cacheada das configuracoes."""
    return Settings()
