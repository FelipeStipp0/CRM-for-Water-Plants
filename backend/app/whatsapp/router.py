"""
Router do módulo WhatsApp.

GET  /whatsapp/webhook  — verificação do webhook pela Meta
POST /whatsapp/webhook  — recebimento de mensagens e status
POST /whatsapp/send/text      — envia texto
POST /whatsapp/send/template  — envia template
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.models.user import User
from app.routers.auth import get_current_active_user
from app.whatsapp.schemas import (
    SendMessageResponse,
    SendTemplateRequest,
    SendTextRequest,
    WhatsAppWebhookPayload,
)
from app.whatsapp.service import WhatsAppService, get_whatsapp_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Webhook ──────────────────────────────────────────────────────────────────

@router.get("/webhook", response_class=PlainTextResponse, tags=["WhatsApp"])
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    """
    Verificação do webhook pela Meta.
    A Meta faz um GET com hub.mode=subscribe e hub.verify_token;
    devemos responder com hub.challenge se o token bater.
    """
    settings = get_settings()
    if (
        hub_mode == "subscribe"
        and settings.whatsapp_verify_token
        and hub_verify_token == settings.whatsapp_verify_token
    ):
        logger.info("[whatsapp] webhook verificado com sucesso")
        return hub_challenge
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token inválido")


@router.post("/webhook", status_code=status.HTTP_200_OK, tags=["WhatsApp"])
async def receive_webhook(request: Request):
    """
    Recebe notificações da Meta: mensagens inbound e status de entrega.
    A Meta exige resposta 200 em até 20s — processamento pesado deve ser async.
    """
    try:
        payload = WhatsAppWebhookPayload.model_validate(await request.json())
    except Exception as exc:
        logger.warning(f"[whatsapp] payload inválido: {exc}")
        return {"status": "ignored"}

    for entry in payload.entry:
        for change in entry.changes:
            value = change.value

            # Mensagens recebidas
            for msg in value.messages or []:
                sender = msg.from_
                text = msg.text.body if msg.text else f"[{msg.type}]"
                logger.info(f"[whatsapp] mensagem de {sender}: {text}")
                # TODO: encaminhar para handler de negócio (ex: resposta automática)

            # Atualizações de status
            for st in value.statuses or []:
                logger.info(f"[whatsapp] status {st.status} para msg {st.id} → {st.recipient_id}")

    return {"status": "ok"}


# ── Envio ────────────────────────────────────────────────────────────────────

@router.post("/send/text", response_model=SendMessageResponse, tags=["WhatsApp"])
async def send_text(
    body: SendTextRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    svc: WhatsAppService = Depends(get_whatsapp_service),
):
    """Envia mensagem de texto para um número (requer janela de 24h aberta)."""
    try:
        result = await svc.send_text(to=body.to, message=body.message)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/send/template", response_model=SendMessageResponse, tags=["WhatsApp"])
async def send_template(
    body: SendTemplateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    svc: WhatsAppService = Depends(get_whatsapp_service),
):
    """Envia mensagem via template aprovado (funciona fora da janela de 24h)."""
    try:
        result = await svc.send_template(
            to=body.to,
            template_name=body.template_name,
            language_code=body.language_code,
            components=body.components,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
