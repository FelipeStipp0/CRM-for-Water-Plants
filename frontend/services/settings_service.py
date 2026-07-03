"""
WMApp Frontend - Settings Service
Serviço para configurações do sistema
"""
from typing import Optional
from services.api_client import api


class SettingsService:
    """Gerencia configurações do sistema."""
    
    def get(self) -> dict:
        """Retorna todas as configurações."""
        return api.get("/settings/")
    
    def update(self, data: dict) -> dict:
        """
        Atualiza configurações.
        Requer permissão de superusuário.
        """
        return api.patch("/settings/", data=data)
    
    def get_tarifas(self) -> dict:
        """Retorna apenas as tarifas (endpoint leve)."""
        return api.get("/settings/tarifas")

    def upload_logo(self, file_path: str) -> dict:
        """Envia logo da empresa (PNG/JPG/WebP). Requer superusuário."""
        return api.post_file("/settings/logo", file_path=file_path, field="file")

    def delete_logo(self) -> dict:
        """Remove logo da empresa. Requer superusuário."""
        return api.delete("/settings/logo")


# Instância global
settings_service = SettingsService()
