"""
AppModal - Modal base reutilizável.
Cobre a tela inteira com overlay escuro, card centralizado com header/footer.
"""
from __future__ import annotations

from typing import Callable, List, Optional

import flet as ft

from i18n import t
from components.theme import COLORS, FONTS, SPACING


class ModalAction:
    """Define um botão no rodapé do modal."""

    def __init__(
        self,
        label: str,
        on_click: Callable,
        primary: bool = False,
        danger: bool = False,
        disabled: bool = False,
    ):
        self.label = label
        self.on_click = on_click
        self.primary = primary
        self.danger = danger
        self.disabled = disabled


class AppModal(ft.Stack):
    """
    Modal overlay reutilizável.

    Uso:
        modal = AppModal(
            page=self.page,
            title="Título",
            content=ft.Text("corpo"),
            actions=[
                ModalAction("Cancelar", on_click=lambda: modal.close()),
                ModalAction("Confirmar", on_click=_do_thing, primary=True),
            ],
        )
        modal.open()
    """

    # Pilha global de modais abertos (último = topo). Usada pelo handler de teclado
    # para que ESC feche sempre o modal do topo e Enter dispare sua ação primária.
    _open_stack: List["AppModal"] = []

    def __init__(
        self,
        page: ft.Page,
        title: str,
        content: ft.Control,
        actions: Optional[List[ModalAction]] = None,
        width_pct: float = 0.5,
        max_height_pct: float = 0.85,
    ):
        super().__init__()
        self._page = page
        self._title = title
        self._content = content
        self._actions = actions or []
        self._width_pct = width_pct
        self._max_height_pct = max_height_pct

        self.expand = True
        self.visible = False
        self.controls = []

    # ------------------------------------------------------------------
    def _build(self) -> ft.Control:
        # Botão X no header
        close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=COLORS["text_muted"],
            icon_size=18,
            tooltip=t("common.close"),
            on_click=lambda e: self.close(),
            style=ft.ButtonStyle(padding=ft.padding.all(4)),
        )

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        self._title,
                        size=FONTS["size_lg"],
                        weight=ft.FontWeight.W_600,
                        color=COLORS["text_primary"],
                    ),
                    ft.Container(expand=True),
                    close_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"]),
        )

        divider_top = ft.Divider(height=1, color=COLORS["border"])

        page_w = self._page.width or 1280
        # O conteúdo dimensiona pelo próprio tamanho (sem altura fixa, que gerava
        # o vão em branco em formulários curtos). Modais muito altos rolam via o
        # Column externo (ver retorno).
        content_area = ft.Container(
            content=ft.Column(
                [self._content],
                tight=True,
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"]),
        )

        # Rodapé com botões centralizados
        footer: Optional[ft.Control] = None
        if self._actions:
            btn_controls = []
            for action in self._actions:
                if action.primary:
                    bg = COLORS["accent_secondary"]
                    fg = COLORS["text_primary"]
                elif action.danger:
                    bg = COLORS["accent_error"]
                    fg = COLORS["text_primary"]
                else:
                    bg = COLORS["bg_elevated"]
                    fg = COLORS["text_secondary"]

                btn_controls.append(
                    ft.Container(
                        content=ft.Text(action.label, color=fg, size=FONTS["size_sm"], weight=ft.FontWeight.W_500),
                        bgcolor=bg,
                        border_radius=6,
                        padding=ft.padding.symmetric(horizontal=20, vertical=10),
                        on_click=None if action.disabled else action.on_click,
                        opacity=0.4 if action.disabled else 1.0,
                        ink=True,
                    )
                )

            footer = ft.Container(
                content=ft.Column(
                    [
                        ft.Divider(height=1, color=COLORS["border"]),
                        ft.Row(
                            btn_controls,
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=SPACING["sm"],
                        ),
                    ],
                    spacing=SPACING["md"],
                    tight=True,
                ),
                padding=ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"]),
            )

        card_children = [header, divider_top, content_area]
        if footer:
            card_children.append(footer)

        modal_width = int(page_w * self._width_pct)

        card = ft.Container(
            content=ft.Column(
                card_children,
                spacing=0,
                tight=True,
            ),
            bgcolor=COLORS["bg_secondary"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=12,
            width=modal_width,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=40,
                color=ft.Colors.with_opacity(0.5, "#000000"),
                offset=ft.Offset(0, 8),
            ),
        )

        # Overlay escuro + card centralizado. O card dimensiona pela altura do
        # conteúdo (sem altura fixa, que gerava o vão em branco). A centralização
        # vem do Container interno com expand + alignment central.
        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.6, "#000000"),
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Container(
                            content=card,
                            width=modal_width,
                            margin=ft.margin.symmetric(horizontal=SPACING["xl"]),
                        ),
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                    )
                ],
                expand=True,
            ),
        )

    # ------------------------------------------------------------------
    def open(self):
        self.controls = [self._build()]
        if self not in self._page.overlay:
            self._page.overlay.append(self)
        self.visible = True
        # Registra no topo da pilha e ativa o handler de teclado (ESC/Enter).
        if self not in AppModal._open_stack:
            AppModal._open_stack.append(self)
        try:
            self._page.on_keyboard_event = AppModal._handle_key
        except Exception:
            pass
        try:
            self._page.update()
        except Exception:
            pass

    def close(self):
        self.visible = False
        try:
            self._page.overlay.remove(self)
        except ValueError:
            pass
        try:
            AppModal._open_stack.remove(self)
        except ValueError:
            pass
        # Se não há mais modais abertos, libera o handler de teclado.
        try:
            if not AppModal._open_stack:
                self._page.on_keyboard_event = None
        except Exception:
            pass
        try:
            self._page.update()
        except Exception:
            pass

    @classmethod
    def _handle_key(cls, e):
        """ESC fecha o modal do topo; Enter dispara a ação primária dele."""
        if not cls._open_stack:
            return
        top = cls._open_stack[-1]
        key = getattr(e, "key", None)
        if key == "Escape":
            top.close()
        elif key == "Enter":
            for action in top._actions:
                if action.primary and not action.disabled and action.on_click:
                    try:
                        action.on_click(e)
                    except Exception:
                        pass
                    break

    def update_content(self, new_content: ft.Control):
        """Substitui o conteúdo e reconstrói o modal."""
        self._content = new_content
        self.controls = [self._build()]
        try:
            self.update()
        except Exception:
            pass
