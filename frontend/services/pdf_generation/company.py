"""
Helpers for company metadata in printed PDFs.
"""
from __future__ import annotations

import base64
import io
from typing import Any

from reportlab.lib.units import mm

from services.pdf_generation.styles import PdfColors, PdfStyles, draw_h_rule


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_company(company_data: dict[str, Any] | None) -> dict:
    d = company_data or {}
    return {
        "name":         _clean(d.get("name")        or d.get("nombre_junta")   or "JUNTA"),
        "ruc":          _clean(d.get("ruc")          or d.get("ruc_junta")      or "-"),
        "address":      _clean(d.get("address")      or d.get("direccion")      or d.get("direccion_junta") or "-"),
        "phone":        _clean(d.get("phone")        or d.get("telefono")       or d.get("telefono_junta")  or "-"),
        "activity":     _clean(d.get("activity")     or d.get("actividad")      or "-"),
        "logo_base64":  d.get("logo_base64") or "",
        "logo_mime":    d.get("logo_mime") or "",
    }


def extract_company(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("company")
    return normalize_company(raw if isinstance(raw, dict) else {})


# ---------------------------------------------------------------------------
# A4 header
#
# Reference layout (from NOTA DE PAGO.docx):
#
#   [LOGO]   NOME DA EMPRESA EM BOLD GRANDE
#            RUC: xxx
#            Dirección: xxx
#            Teléfono: xxx
#            ─────────────────────────────────────────   (linha fina)
#                                           TIPO DE DOCUMENTO
#   ═══════════════════════════════════════════════════  (linha separadora)
#
# Logo e bloco de texto ficam alinhados verticalmente pelo topo.
# O nome da empresa quebra em múltiplas linhas se necessário — nunca truncado.
# Retorna y logo abaixo da linha separadora.
# ---------------------------------------------------------------------------

_LOGO_W      = 28 * mm
_LOGO_H      = 28 * mm
_LOGO_GAP    =  4 * mm   # espaço entre logo e bloco de texto
_LINE_NAME   =  7 * mm   # altura de cada linha do nome (pode ser múltiplas)
_LINE_META   =  5 * mm   # altura de cada linha de meta (ruc, tel, endereço)


def _wrap_text(c, text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    """Quebra texto em linhas que caibam em max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def draw_company_header_a4(
    c,
    *,
    width: float,
    margin: float,
    y: float,
    title: str,
    company: dict[str, Any] | None,
) -> float:
    """
    Draws a clean institutional header following the reference document layout.

    Left column: logo (optional, _LOGO_W × _LOGO_H).
    Right of logo: company name (bold, wraps if needed), then RUC, Dirección,
    Teléfono — each on its own line, no truncation.
    Below the info block: thin rule, then document title right-aligned,
    then a slightly thicker separator rule.

    Returns y below the separator.

    Logo spec (see REFERENCIAS.md):
      - Key: company["logo_path"] — absolute path to PNG or JPG
      - Recommended: PNG with transparent background, min 300×300 px, square
      - Rendered at _LOGO_W × _LOGO_H (28×28mm), aspect-ratio preserved
    """
    GAP  = PdfStyles.GAP
    info = normalize_company(company)

    logo_b64  = info.get("logo_base64", "")
    logo_mime = info.get("logo_mime", "")

    # Logo à esquerda — altura fixa 28mm, largura proporcional
    text_x = margin
    if logo_b64:
        try:
            from PIL import Image as _PILImage
            from reportlab.lib.utils import ImageReader
            raw = base64.b64decode(logo_b64)
            buf = io.BytesIO(raw)
            with _PILImage.open(buf) as _img:
                _iw, _ih = _img.size
            buf.seek(0)
            logo_w = _LOGO_H * (_iw / _ih) if _ih else _LOGO_H
            c.drawImage(
                ImageReader(buf),
                margin, y - _LOGO_H,
                width=logo_w, height=_LOGO_H,
                preserveAspectRatio=False,
                mask="auto",
            )
            text_x = margin + logo_w + _LOGO_GAP
        except Exception:
            pass

    text_w  = width - margin - text_x
    right_x = width - margin   # margem direita

    # --- Nome da empresa — alinhado à direita ---
    fn, fs = PdfStyles.FONT_COMPANY
    name_lines = _wrap_text(c, info["name"].upper(), fn, fs, text_w)
    cursor_y = y - _LINE_NAME + 1 * mm
    c.setFont(fn, fs)
    c.setFillColor(PdfColors.DARK)
    for line in name_lines:
        c.drawRightString(right_x, cursor_y, line)
        cursor_y -= _LINE_NAME

    # --- Meta: RUC, Dirección, Teléfono — alinhados à direita ---
    c.setFont(*PdfStyles.FONT_META)
    c.setFillColor(PdfColors.GRAY)
    for label, value in [
        ("RUC",       info["ruc"]),
        ("Dirección", info["address"]),
        ("Teléfono",  info["phone"]),
    ]:
        c.drawRightString(right_x, cursor_y, f"{label}: {value}")
        cursor_y -= _LINE_META

    c.setFillColor(PdfColors.DARK)

    block_bottom  = min(cursor_y, y - _LOGO_H)
    y_after_block = block_bottom - GAP

    # --- Linha separadora ---
    draw_h_rule(c, margin, y_after_block, width - 2 * margin, thickness=0.7)

    # O título do documento é desenhado pelo caller, centrado, após esta linha.
    # Retornamos y imediatamente abaixo da linha para o caller posicionar o título.
    return y_after_block - GAP


# ---------------------------------------------------------------------------
# P80 header — mesmo conceito, nome quebra em linhas, sem logo
# ---------------------------------------------------------------------------

def draw_company_header_p80(
    c,
    *,
    width: float,
    margin: float,
    y: float,
    title: str,
    company: dict[str, Any] | None,
) -> float:
    """
    Compact header for 80mm thermal paper.
    Company name is centered and wraps across multiple lines — never truncated.
    RUC and phone centered below. Title centered. Separator rule at end.
    Returns y below the separator.
    """
    GAP  = PdfStyles.GAP - 1 * mm
    info = normalize_company(company)
    cx   = width / 2
    iw   = width - 2 * margin

    fn, fs = PdfStyles.P80_FONT_NAME
    name_lines = _wrap_text(c, info["name"].upper(), fn, fs, iw)

    c.setFont(fn, fs)
    c.setFillColor(PdfColors.DARK)
    for line in name_lines:
        c.drawCentredString(cx, y, line)
        y -= GAP

    c.setFont(*PdfStyles.P80_FONT_BODY)
    c.setFillColor(PdfColors.GRAY)
    c.drawCentredString(cx, y, f"RUC: {info['ruc']}")
    y -= GAP - 1 * mm
    c.drawCentredString(cx, y, f"Tel: {info['phone']}")
    y -= GAP

    draw_h_rule(c, margin, y, iw, thickness=0.8)
    y -= GAP - 1 * mm + 2.5 * mm

    c.setFont(*PdfStyles.P80_FONT_DOCTYPE)
    c.setFillColor(PdfColors.DARK)
    c.drawCentredString(cx, y, title.upper())
    y -= GAP

    draw_h_rule(c, margin, y, iw, thickness=0.4)
    y -= GAP

    return y
