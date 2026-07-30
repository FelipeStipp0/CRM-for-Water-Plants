from __future__ import annotations

"""
Dinheiro do turno: sangría, reposición e o resumo parcial.

**Sangría** é dinheiro que sai da gaveta no meio do turno (levado ao banco, ao
cofre ou entregue à tesouraria). **Reposición** é dinheiro que volta a entrar
(troco que faltou). Nenhuma das duas é cobrança de ninguém: não mexem em fatura
nem em recibo, só na gaveta — e por isso pesam no efectivo esperado. Sem elas o
esperado mente assim que alguém leva dinheiro ao banco.

O **resumo parcial** é só de tela, quando o cajero pede: entradas, anulações,
sangrías e o esperado até agora. Não imprime — o papel do turno é o cierre.
"""

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, RADIUS, create_text_field
from services.api_client import APIError
from services.caja_service import caja_service
from utils.errors import friendly_error
from utils.formatters import format_currency, format_local
from i18n import t

SANGRIA = "SANGRIA_CAJA"
REPOSICION = "REPOSICION_CAJA"


def _money(v) -> str:
    return format_currency(v or 0, "Gs.")


def _parse(raw: str):
    raw = (raw or "").strip().replace(".", "").replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def open_movimiento_dialog(page: ft.Page, show_snackbar, categoria: str, on_done=None):
    """Lança uma sangría ou uma reposición no turno aberto."""
    es_sangria = categoria == SANGRIA
    titulo = "Sangría de caja" if es_sangria else "Reposición de caja"

    monto = ft.TextField(
        value="", hint_text="0", border=ft.InputBorder.NONE, autofocus=True,
        text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700,
                                color=COLORS["text_primary"]),
        content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    motivo = create_text_field(
        "¿A dónde va?" if es_sangria else "¿De dónde viene?", width=None)
    err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)

    def _u(ctrl):
        try:
            ctrl.update()
        except Exception:  # noqa: BLE001
            pass

    def _confirmar(e=None):
        valor = _parse(monto.value)
        texto = (motivo.value or "").strip()
        if not valor or valor <= 0:
            err.value = "Ingresá un monto mayor a cero."
            err.visible = True
            _u(err)
            return
        if len(texto) < 3:
            err.value = ("Indicá a dónde va la plata." if es_sangria
                         else "Indicá de dónde viene la plata.")
            err.visible = True
            _u(err)
            return

        def work():
            try:
                r = caja_service.movimiento(categoria, valor, texto)
            except APIError as exc:
                err.value = friendly_error(exc)
                err.visible = True
                _u(err)
                return
            try:
                modal.close()
            except Exception:  # noqa: BLE001
                pass
            esperado = (r or {}).get("resumen", {}).get("efectivo_esperado")
            show_snackbar(
                f"✓ {'Sangría' if es_sangria else 'Reposición'} de {_money(valor)} "
                f"— en la gaveta quedan {_money(esperado)}")
            if on_done:
                on_done(r)

        try:
            page.run_thread(work)
        except Exception:  # noqa: BLE001
            work()

    monto.on_submit = _confirmar

    explicacion = (
        "La plata sale de la gaveta ahora. Se descuenta del efectivo esperado del "
        "cierre, así lo contado sigue cuadrando."
        if es_sangria else
        "La plata entra en la gaveta ahora, sin ser un cobro. Se suma al efectivo "
        "esperado del cierre.")

    modal = AppModal(
        page=page,
        title=titulo,
        content=ft.Column([
            ft.Text(explicacion, size=13, color=COLORS["text_secondary"]),
            ft.Container(
                content=ft.Row([
                    ft.Text("Gs.", size=16, weight=ft.FontWeight.W_600,
                            color=COLORS["text_muted"]),
                    ft.Container(content=monto, expand=True),
                ], spacing=10),
                bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["border"]),
                border_radius=RADIUS["md"],
                padding=ft.Padding.symmetric(horizontal=15, vertical=0), height=50,
            ),
            motivo,
            err,
        ], spacing=12, tight=True),
        actions=[
            ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
            ModalAction("Registrar", primary=True, on_click=_confirmar),
        ],
        width_pct=0.38,
    )
    modal.open()
    return modal


def open_resumen_dialog(page: ft.Page, show_snackbar, sesion: dict):
    """Resumo parcial do turno — só na tela, sem impressão."""
    cuerpo = ft.Column([ft.Text("Calculando…", size=13, color=COLORS["text_muted"])],
                       spacing=7, tight=True)

    def _u(ctrl):
        try:
            ctrl.update()
        except Exception:  # noqa: BLE001
            pass

    def _line(label: str, value: str, strong: bool = False) -> ft.Control:
        return ft.Row([
            ft.Text(label, size=13, color=COLORS["text_secondary"]),
            ft.Container(expand=True),
            ft.Text(value, size=14 if strong else 13,
                    weight=ft.FontWeight.W_700 if strong else ft.FontWeight.W_500,
                    color=COLORS["text_primary"]),
        ])

    def load():
        try:
            r = caja_service.preview()
            movs = caja_service.movimientos()
        except APIError as exc:
            cuerpo.controls = [ft.Text(friendly_error(exc), size=13,
                                       color=COLORS["accent_error"])]
            _u(cuerpo)
            return

        filas = [
            _line("Caja", str(r.get("numero_fmt", "-"))),
            _line("Abierta", format_local(r.get("fecha_apertura"), "%d/%m/%Y %H:%M")),
            _line("Monto inicial", _money(r.get("monto_inicial"))),
            ft.Divider(height=1, color=COLORS["border_subtle"]),
            _line(f"Cobros en efectivo ({r.get('cantidad_pagos', 0)})",
                  _money(r.get("ingresos_efectivo"))),
        ]
        if float(r.get("ingresos_transferencia") or 0):
            filas.append(_line("Transferencias (no van en la gaveta)",
                               _money(r.get("ingresos_transferencia"))))
        if float(r.get("ingresos_cheque") or 0):
            filas.append(_line("Cheques (no van en la gaveta)",
                               _money(r.get("ingresos_cheque"))))
        if int(r.get("estornos_cantidad") or 0):
            filas.append(_line(f"Anulaciones ({r.get('estornos_cantidad')})",
                               f"− {_money(r.get('estornos_efectivo_previos'))}"))
        if int(r.get("sangrias_cantidad") or 0):
            filas.append(_line(f"Sangrías ({r.get('sangrias_cantidad')})",
                               f"− {_money(r.get('sangrias_total'))}"))
        if int(r.get("reposiciones_cantidad") or 0):
            filas.append(_line(f"Reposiciones ({r.get('reposiciones_cantidad')})",
                               _money(r.get("reposiciones_total"))))
        filas.append(ft.Divider(height=1, color=COLORS["border_subtle"]))
        filas.append(_line("Efectivo esperado ahora",
                           _money(r.get("efectivo_esperado")), strong=True))

        if movs:
            filas.append(ft.Container(height=6))
            filas.append(ft.Text("MOVIMIENTOS DE LA GAVETA", size=11,
                                 weight=ft.FontWeight.W_700, color=COLORS["text_muted"]))
            for m in movs[:12]:
                es_sangria = m.get("categoria") == SANGRIA
                filas.append(ft.Row([
                    ft.Text(format_local(m.get("fecha"), "%H:%M"), size=12,
                            color=COLORS["text_muted"], width=48),
                    ft.Text("Sangría" if es_sangria else "Reposición", size=12,
                            color=COLORS["accent_warning"] if es_sangria
                            else COLORS["accent_success"], width=82),
                    ft.Text(m.get("descripcion", "-"), size=12,
                            color=COLORS["text_secondary"], expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(("− " if es_sangria else "") + _money(m.get("valor")),
                            size=12, weight=ft.FontWeight.W_600,
                            color=COLORS["text_primary"]),
                ], spacing=8))

        filas.append(ft.Container(height=4))
        filas.append(ft.Text(
            "Resumen de control, solo en pantalla. El comprobante del turno sale al "
            "cerrar la caja.", size=11, color=COLORS["text_muted"]))
        cuerpo.controls = filas
        _u(cuerpo)

    modal = AppModal(
        page=page,
        title=f"Turno en curso — Caja {sesion.get('numero_fmt', '')}",
        content=ft.Column([cuerpo], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO),
        actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
        width_pct=0.42,
    )
    modal.open()
    try:
        page.run_thread(load)
    except Exception:  # noqa: BLE001
        load()
    return modal
