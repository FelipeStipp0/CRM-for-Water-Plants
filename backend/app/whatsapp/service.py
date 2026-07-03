"""
Serviço de integração com a Meta WhatsApp Cloud API.
Documentação: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import logging
from typing import List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class WhatsAppService:
    """Cliente para a Meta WhatsApp Cloud API."""

    def __init__(self):
        settings = get_settings()
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.access_token = settings.whatsapp_access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def send_text(self, to: str, message: str) -> dict:
        """Envia mensagem de texto livre (apenas dentro da janela de 24h)."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        return await self._post(payload)

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "es",
        components: Optional[List[dict]] = None,
    ) -> dict:
        """Envia mensagem via template aprovado pela Meta."""
        template: dict = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        return await self._post(payload)

    async def mark_as_read(self, message_id: str) -> dict:
        """Marca uma mensagem recebida como lida."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> dict:
        url = f"{GRAPH_API_BASE}/{self.phone_number_id}/messages"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.json()


# Singleton
_service: Optional[WhatsAppService] = None


def get_whatsapp_service() -> WhatsAppService:
    global _service
    if _service is None:
        _service = WhatsAppService()
    return _service
