"""
SplashView — telinha de boot do Saneo.

Renderiza o logo + uma area de status com tres estados:
  1. progresso (spinner girando, "Iniciando...")
  2. verificacao de sessao ("Verificando sesion...")
  3. sucesso (checkmark com animacao de escala + opacidade)

Em todos os estados, ocupa toda a area da janela (que e pequena enquanto o
boot acontece). Quando autoLogin sucede a gente transiciona o checkmark e
depois redimensiona a janela e troca pelo layout principal.

Tudo aqui e cosmetico — qualquer erro de update silenciosamente ignora.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import flet as ft

from components.theme import COLORS, FONTS, SPACING
from i18n import t


class SplashView(ft.Container):
    WINDOW_WIDTH = 480
    WINDOW_HEIGHT = 620

    def __init__(self):
        super().__init__()
        self.bgcolor = COLORS["bg_primary"]
        self.expand = True

        self._logo = ft.Image(src="saneo.png", width=220)

        # Spinner de "andamento". Mantem visivel durante boot + verificacao.
        self._spinner = ft.ProgressRing(
            width=36,
            height=36,
            stroke_width=3,
            color=COLORS["accent_primary"],
        )

        # Checkmark animado. Nasce em scale=0 e opacidade=0 — show_check muda
        # pra 1 e Flet anima por causa do animate_scale/animate_opacity.
        self._check_icon = ft.Icon(
            ft.Icons.CHECK_CIRCLE,
            color=COLORS["accent_success"],
            size=72,
        )
        self._check = ft.Container(
            content=self._check_icon,
            scale=ft.Scale(0.1),
            opacity=0,
            animate_scale=ft.Animation(280, ft.AnimationCurve.EASE_OUT_BACK),
            animate_opacity=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            visible=False,
            alignment=ft.Alignment(0, 0),
        )

        # Stack pra spinner/check ocuparem o mesmo espaco visual.
        self._status_icon_stack = ft.Stack(
            [
                ft.Container(
                    content=self._spinner,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Container(
                    content=self._check,
                    alignment=ft.Alignment(0, 0),
                ),
            ],
            width=80,
            height=80,
        )

        self._status_text = ft.Text(
            t("splash.starting"),
            size=14,
            color=COLORS["text_secondary"],
            text_align=ft.TextAlign.CENTER,
        )

        self.content = ft.Column(
            [
                ft.Container(expand=2),
                self._logo,
                ft.Container(height=32),
                self._status_icon_stack,
                ft.Container(height=14),
                self._status_text,
                ft.Container(expand=3),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=0,
            expand=True,
        )

    def _safe_update(self, control: Optional[ft.Control] = None):
        try:
            (control or self).update()
        except Exception:
            pass

    def set_status(self, message: str):
        """Troca o texto sob o spinner. Se o checkmark estiver ativo, restaura
        o spinner (pra reutilizar a splash em transicoes futuras)."""
        self._status_text.value = message
        # Garante spinner ativo se nao estiver.
        self._spinner.visible = True
        self._check.visible = False
        self._check.scale = ft.Scale(0.1)
        self._check.opacity = 0
        self._safe_update()

    def show_check(self, message: str, on_done: Optional[Callable] = None, hold_ms: int = 600):
        """Esconde o spinner, mostra o checkmark com animacao e chama on_done
        depois de hold_ms (default 600 ms — tempo pra usuario perceber o sinal).
        on_done roda dentro do mesmo thread que chamou show_check; se quiser
        sair pra outro thread, dispare via page.run_thread no callback."""
        self._status_text.value = message
        self._spinner.visible = False
        self._check.visible = True
        # Reinicia estado antes da animacao.
        self._check.scale = ft.Scale(0.1)
        self._check.opacity = 0
        self._safe_update()
        # Trigger da animacao: nova atribuicao + update faz Flet animar entre os valores.
        self._check.scale = ft.Scale(1.0)
        self._check.opacity = 1
        self._safe_update()
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass
