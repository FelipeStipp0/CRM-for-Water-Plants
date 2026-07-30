"""Dialogs padronizados da aplicação.

``AppModal`` preserva a API usada pelas views, mas delega renderização e
gerenciamento de ciclo de vida ao sistema nativo de dialogs do Flet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import flet as ft

from components.theme import COLORS, FONTS, RADIUS


@dataclass
class ModalAction:
    """Define uma ação exibida no rodapé do dialog."""

    label: str
    on_click: Callable
    primary: bool = False
    danger: bool = False
    disabled: bool = False


class AppModal:
    """Compatibilidade para os dialogs imperativos existentes.

    O conteúdo é exibido por :meth:`Page.show_dialog`, sem manipular
    ``page.overlay`` e sem substituir o handler global de teclado.
    """

    def __init__(
        self,
        page: ft.Page,
        title: str,
        content: ft.Control,
        actions: Optional[list[ModalAction]] = None,
        width_pct: float = 0.5,
        max_height_pct: float = 0.85,
    ):
        self._page = page
        self._title = title
        self._content = content
        self._actions = actions or []
        self._width_pct = width_pct
        # Mantido apenas por compatibilidade. AlertDialog(scrollable=True)
        # calcula o limite vertical a partir da viewport e mantém as ações visíveis.
        self._max_height_pct = max_height_pct
        self._dialog: Optional[ft.AlertDialog] = None

    def _dialog_width(self) -> int:
        """Converte larguras percentuais antigas em tamanhos responsivos limitados."""
        page_width = int(self._page.width or 1280)
        requested = int(page_width * self._width_pct)

        if self._width_pct <= 0.36:
            cap = 440
        elif self._width_pct <= 0.48:
            cap = 620
        else:
            cap = 820

        viewport_limit = max(320, page_width - 96)
        return max(320, min(requested, cap, viewport_limit))

    @staticmethod
    def _button_text(label: str) -> ft.Text:
        return ft.Text(label, size=FONTS["size_sm"], weight=ft.FontWeight.W_600)

    def _build_action(self, action: ModalAction) -> ft.Control:
        if action.danger:
            return ft.FilledButton(
                content=self._button_text(action.label),
                on_click=action.on_click,
                disabled=action.disabled,
                style=ft.ButtonStyle(
                    bgcolor=COLORS["accent_error"],
                    color=COLORS["text_primary"],
                    shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
                    padding=ft.Padding.symmetric(horizontal=18, vertical=11),
                ),
            )

        if action.primary:
            return ft.FilledButton(
                content=self._button_text(action.label),
                on_click=action.on_click,
                disabled=action.disabled,
                style=ft.ButtonStyle(
                    bgcolor=COLORS["accent_primary"],
                    color=COLORS["text_primary"],
                    shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
                    padding=ft.Padding.symmetric(horizontal=18, vertical=11),
                ),
            )

        return ft.TextButton(
            content=self._button_text(action.label),
            on_click=action.on_click,
            disabled=action.disabled,
            style=ft.ButtonStyle(
                color=COLORS["text_secondary"],
                shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
                padding=ft.Padding.symmetric(horizontal=14, vertical=11),
            ),
        )

    def _build_content(self) -> ft.Control:
        return ft.Container(
            width=self._dialog_width(),
            content=self._content,
        )

    def _on_dismiss(self, _=None) -> None:
        self._dialog = None

    def _build_dialog(self) -> ft.AlertDialog:
        return ft.AlertDialog(
            modal=True,
            title=ft.Text(
                self._title,
                size=FONTS["size_xl"],
                weight=ft.FontWeight.W_600,
                color=COLORS["text_primary"],
            ),
            content=self._build_content(),
            actions=[self._build_action(action) for action in self._actions],
            actions_alignment=ft.MainAxisAlignment.END,
            scrollable=True,
            bgcolor=COLORS["bg_secondary"],
            barrier_color=ft.Colors.with_opacity(0.74, "#020617"),
            shape=ft.RoundedRectangleBorder(radius=RADIUS["xl"]),
            title_padding=ft.Padding.only(left=28, top=24, right=28, bottom=8),
            content_padding=ft.Padding.only(left=28, top=12, right=28, bottom=14),
            actions_padding=ft.Padding.only(left=28, top=8, right=28, bottom=22),
            actions_overflow_button_spacing=8,
            semantics_label=self._title,
            on_dismiss=self._on_dismiss,
        )

    @property
    def is_open(self) -> bool:
        """
        O dialog está na tela?

        Quem tem atalhos de teclado globais precisa saber disto: uma tecla de
        função que dispara com um dialog aberto empilha telas em cima de telas.
        """
        return self._dialog is not None and bool(self._dialog.open)

    def open(self) -> None:
        if self._dialog is not None and self._dialog.open:
            return
        self._dialog = self._build_dialog()
        self._page.show_dialog(self._dialog)

    def close(self) -> None:
        """Fecha o dialog. Para trocar de tela, feche ANTES de abrir o próximo.

        Nota para quem for mexer nisto: ``on_dismiss`` NÃO serve de gancho para
        encadear dialogs neste app. Ele só dispara em dismiss vindo do cliente,
        não em fechamento programático — a seção "Chaining dialogs" da doc do
        Flet vale para ``ft.use_dialog`` (declarativo), e aqui usamos
        ``page.show_dialog`` (imperativo). Medido em 2026-07-29.
        """
        dialog = self._dialog
        if dialog is None or not dialog.open:
            return
        # Fechamento explícito permite encerrar um dialog pai mesmo quando um
        # fluxo secundário ainda está terminando sua animação de saída.
        dialog.open = False
        dialog.update()

    def update(self) -> None:
        """Repinta o dialog inteiro (título, conteúdo, ações).

        Existe porque quem segura um AppModal segura um objeto Python, não um
        controle Flet: sem isto, `modal.update()` levantava AttributeError, e como
        as telas chamam isso dentro de try/except a atualização virava no-op
        silencioso (foi o que travou o progresso da emissão SIFEN). Atualizar o
        dialog basta: o digest do pai inclui os filhos não isolados.
        """
        dialog = self._dialog
        if dialog is not None and dialog.open:
            dialog.update()

    def update_content(self, new_content: ft.Control) -> None:
        """Substitui o conteúdo sem reconstruir o overlay/dialog inteiro."""
        self._content = new_content
        if self._dialog is not None and self._dialog.open:
            self._dialog.content = self._build_content()
            self._dialog.update()

