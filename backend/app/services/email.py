"""
Email transacional do CRM (Forward Email).

Existe porque o convite de operador não saía: o `admin-api` tem a função de
convite escrita mas nunca chamada, e o backend do CRM — que é quem realmente
cadastra operadores — não tinha envio nenhum. Resultado: o operador era criado
com `must_change_password=True` e ninguém recebia a senha temporária.

Envio é BEST-EFFORT: se a chave não estiver configurada ou o provedor falhar, o
cadastro não pode quebrar por causa disso. Devolve False e registra no log.
"""

import base64
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

API_URL = "https://api.forwardemail.net/v1/emails"

# Paleta do app — mesmos tons do admin-api, para o email não destoar.
C = {
    "bg": "#1a1a2e", "card": "#16213e", "surface": "#0f3460",
    "accent": "#e94560", "accent2": "#0ea5e9",
    "text": "#f8fafc", "text2": "#94a3b8", "muted": "#64748b", "border": "#334155",
}


def _assunto(texto: str) -> str:
    """
    RFC 2047: cabeçalho é ASCII. Texto com acento vai como encoded-word inteiro —
    misturar 8-bit cru com encoded-word produz header inválido e o cliente mostra
    o token literal (foi o que aconteceu no email de boas-vindas da primeira junta).
    """
    if all(ord(c) < 128 for c in texto):
        return texto
    return "=?UTF-8?B?" + base64.b64encode(texto.encode("utf-8")).decode() + "?="


def _layout(titulo: str, corpo: str) -> str:
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:{C['bg']};font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['bg']};padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{C['card']};border:1px solid {C['border']};border-radius:16px;overflow:hidden;">
<tr><td style="background:{C['surface']};padding:28px 40px;border-bottom:1px solid {C['border']};">
  <div style="font-size:20px;font-weight:700;color:{C['text']};">Saneo</div>
  <div style="font-size:12px;color:{C['text2']};margin-top:6px;letter-spacing:2px;text-transform:uppercase;">Sistema de Saneamiento</div>
</td></tr>
<tr><td style="padding:34px 40px 10px 40px;">
  <h1 style="margin:0 0 14px 0;font-size:21px;color:{C['text']};font-weight:700;">{titulo}</h1>
  {corpo}
</td></tr>
<tr><td style="padding:20px 40px 30px 40px;border-top:1px solid {C['border']};">
  <p style="margin:0;font-size:13px;color:{C['text2']};">Atentamente,<br><strong style="color:{C['text']};">Equipo ArqSoftware</strong></p>
</td></tr></table></td></tr></table></body></html>"""


def _card_credenciais(org_slug: str, username: str, senha: str) -> str:
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['surface']};border:1px solid {C['border']};border-radius:12px;margin:6px 0 22px 0;">
<tr><td style="padding:20px 22px;">
  <div style="font-size:11px;font-weight:700;color:{C['accent2']};letter-spacing:1px;text-transform:uppercase;margin-bottom:12px;">Credenciales de acceso</div>
  <table role="presentation" width="100%" style="font-size:14px;color:{C['text']};">
    <tr><td style="padding:6px 0;color:{C['text2']};">Organización</td><td style="padding:6px 0;text-align:right;font-weight:600;">{org_slug}</td></tr>
    <tr><td style="padding:6px 0;color:{C['text2']};">Usuario</td><td style="padding:6px 0;text-align:right;font-weight:600;">{username}</td></tr>
    <tr><td style="padding:6px 0;color:{C['text2']};">Contraseña temporal</td>
        <td style="padding:6px 0;text-align:right;"><span style="font-family:Consolas,monospace;background:{C['accent']};color:#fff;padding:5px 13px;border-radius:6px;font-weight:600;letter-spacing:1px;">{senha}</span></td></tr>
  </table>
</td></tr></table>"""


async def _enviar(para: str, assunto: str, html: str) -> bool:
    cfg = get_settings()
    if not cfg.forward_email_api_key:
        logger.warning("[email] FORWARD_EMAIL_API_KEY ausente — envio para %s ignorado", para)
        return False
    auth = base64.b64encode(f"{cfg.forward_email_api_key}:".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=20.0) as cli:
            r = await cli.post(API_URL, headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json; charset=utf-8",
            }, json={"from": cfg.email_from, "to": para,
                     "subject": _assunto(assunto), "html": html})
        if r.status_code >= 400:
            logger.error("[email] Forward Email %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:  # noqa: BLE001 — envio nunca derruba o cadastro
        logger.error("[email] falha ao enviar para %s: %s", para, e)
        return False


async def enviar_convite_operador(
    *, para: str, nombre: str, org_slug: str, username: str,
    senha_temporal: str, convidado_por: Optional[str] = None,
) -> bool:
    """Convite de acesso ao operador recém-cadastrado. Best-effort."""
    quem = f" por {convidado_por}" if convidado_por else ""
    corpo = (
        f"<p style=\"margin:0 0 18px 0;font-size:15px;line-height:1.65;color:{C['text2']};\">"
        f"Hola <strong style=\"color:{C['text']};\">{nombre}</strong>, fuiste dado de alta{quem} "
        f"en el sistema de gestión de la junta.</p>"
        + _card_credenciais(org_slug, username, senha_temporal)
        + f"<p style=\"margin:0;font-size:13px;line-height:1.6;color:{C['muted']};\">"
          f"Al ingresar por primera vez el sistema te pedirá cambiar la contraseña.</p>"
    )
    return await _enviar(para, f"Acceso a Saneo — {org_slug}",
                         _layout("Tu acceso está listo", corpo))
