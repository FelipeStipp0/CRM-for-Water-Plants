"""
Schemas para mensagens e webhooks do WhatsApp (Meta Cloud API).
"""

from typing import Any, List, Literal, Optional
from pydantic import BaseModel


# ── Webhook inbound ──────────────────────────────────────────────────────────

class WhatsAppProfile(BaseModel):
    name: str


class WhatsAppContact(BaseModel):
    profile: WhatsAppProfile
    wa_id: str


class WhatsAppTextBody(BaseModel):
    body: str


class WhatsAppMessage(BaseModel):
    id: str
    from_: str
    timestamp: str
    type: str
    text: Optional[WhatsAppTextBody] = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def model_validate(cls, obj: Any, **kwargs):
        if isinstance(obj, dict) and "from" in obj:
            obj = dict(obj)
            obj["from_"] = obj.pop("from")
        return super().model_validate(obj, **kwargs)


class WhatsAppStatus(BaseModel):
    id: str
    status: str  # sent | delivered | read | failed
    timestamp: str
    recipient_id: str

    model_config = {"extra": "allow"}


class WhatsAppValue(BaseModel):
    messaging_product: str
    metadata: dict
    contacts: Optional[List[WhatsAppContact]] = None
    messages: Optional[List[WhatsAppMessage]] = None
    statuses: Optional[List[WhatsAppStatus]] = None

    model_config = {"extra": "allow"}


class WhatsAppChange(BaseModel):
    value: WhatsAppValue
    field: str


class WhatsAppEntry(BaseModel):
    id: str
    changes: List[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    object: str
    entry: List[WhatsAppEntry]


# ── Outbound send ─────────────────────────────────────────────────────────────

class SendTextRequest(BaseModel):
    to: str
    message: str


class SendTemplateRequest(BaseModel):
    to: str
    template_name: str
    language_code: str = "es"
    components: Optional[List[dict]] = None


class SendMessageResponse(BaseModel):
    messaging_product: str
    contacts: List[dict]
    messages: List[dict]
