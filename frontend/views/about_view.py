"""
WMApp Frontend - About View
Página "Acerca de": exibe a logo da marca e informações do aplicativo.
"""
from datetime import datetime

import flet as ft

from components.theme import COLORS, FONTS, SPACING
from i18n import t

APP_VERSION = "1.0.0"


class AboutView(ft.Container):
    """Tela 'Acerca de' com a logo e dados do sistema."""

    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Image(src="saneo.png", width=260),
                    ft.Container(height=SPACING["sm"]),
                    ft.Text(
                        t("about.tagline"),
                        size=FONTS["size_lg"],
                        weight=ft.FontWeight.W_500,
                        color=COLORS["text_primary"],
                    ),
                    ft.Text(
                        t("about.description"),
                        size=FONTS["size_sm"],
                        color=COLORS["text_secondary"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=SPACING["md"]),
                    ft.Divider(height=1, color=COLORS["border"]),
                    ft.Container(height=SPACING["md"]),
                    ft.Text(
                        t("about.version", version=APP_VERSION),
                        size=FONTS["size_sm"],
                        color=COLORS["text_secondary"],
                    ),
                    ft.Text(
                        t("about.copyright", year=datetime.now().year),
                        size=FONTS["size_xs"],
                        color=COLORS["text_muted"],
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=SPACING["xl"],
            bgcolor=COLORS["bg_surface"],
            border_radius=12,
            border=ft.Border.all(1, COLORS["border"]),
            width=460,
        )

        self.content = ft.Column(
            [
                ft.Row([card], alignment=ft.MainAxisAlignment.CENTER),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = SPACING["md"]
        self.bgcolor = COLORS["bg_primary"]
        self.expand = True
