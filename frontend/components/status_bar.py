"""
WMApp Frontend - Status Bar Component
Barra de status inferior com info de usuário, impressora e relógio
"""
import threading
import time
from datetime import datetime

import flet as ft
from components.theme import COLORS, FONTS, SPACING
from config.local_settings import get_printer
from i18n import t


class StatusBar(ft.Container):
    """Barra de status inferior."""

    def __init__(self, username: str = "", printer_thermal: str = None, printer_a4: str = None):
        super().__init__()
        self.username = username
        self.printer_thermal = printer_thermal or get_printer("thermal")
        self.printer_a4 = printer_a4 or get_printer("a4")
        # Relógio (data + hora), atualizado a cada segundo enquanto montado.
        self._clock_text = ft.Text(
            datetime.now().strftime("%d/%m/%Y · %H:%M:%S"),
            size=FONTS["size_xs"],
            color=COLORS["text_secondary"],
        )
        self._clock_running = False

        self._build()
    
    def _build(self):
        """Constrói a barra de status."""
        # Impressora térmica
        thermal_text = self.printer_thermal or t("status.not_configured")
        thermal_color = COLORS["accent_success"] if self.printer_thermal else COLORS["text_muted"]

        # Impressora A4
        a4_text = self.printer_a4 or t("status.not_configured")
        a4_color = COLORS["accent_success"] if self.printer_a4 else COLORS["text_muted"]
        
        self.content = ft.Row(
            [
                # Impressora Térmica
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PRINT, size=16, color=thermal_color),
                        ft.Text(t("status.thermal", value=thermal_text), size=FONTS["size_xs"], color=COLORS["text_secondary"]),
                    ],
                    spacing=4,
                ),
                ft.VerticalDivider(width=1, color=COLORS["border"]),
                # Impressora A4
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PRINT, size=16, color=a4_color),
                        ft.Text(t("status.a4", value=a4_text), size=FONTS["size_xs"], color=COLORS["text_secondary"]),
                    ],
                    spacing=4,
                ),
                # Spacer
                ft.Container(expand=True),
                # Usuário
                ft.Row(
                    [
                        ft.Icon(ft.Icons.PERSON, size=16, color=COLORS["text_secondary"]),
                        ft.Text(self.username or t("status.not_logged"), size=FONTS["size_xs"], color=COLORS["text_secondary"]),
                    ],
                    spacing=4,
                ),
                ft.VerticalDivider(width=1, color=COLORS["border"]),
                # Relógio
                ft.Row(
                    [
                        ft.Icon(ft.Icons.SCHEDULE, size=16, color=COLORS["text_secondary"]),
                        self._clock_text,
                    ],
                    spacing=4,
                ),
            ],
            spacing=SPACING["md"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        
        self.bgcolor = COLORS["bg_secondary"]
        self.padding = ft.padding.symmetric(horizontal=SPACING["md"], vertical=SPACING["sm"])
        self.border = ft.border.only(top=ft.BorderSide(1, COLORS["border"]))
    
    def update_user(self, username: str):
        """Atualiza nome do usuário."""
        self.username = username
        self._build()
        self.update()
    
    def update_printers(self, thermal: str = None, a4: str = None):
        """Atualiza impressoras."""
        if thermal is not None:
            self.printer_thermal = thermal
        if a4 is not None:
            self.printer_a4 = a4
        self._build()
        self.update()

    def did_mount(self):
        """Inicia o relógio quando a barra entra na árvore."""
        if self._clock_running:
            return
        self._clock_running = True
        threading.Thread(target=self._tick_clock, daemon=True).start()

    def will_unmount(self):
        """Para o relógio quando a barra sai da árvore."""
        self._clock_running = False

    def _tick_clock(self):
        while self._clock_running:
            self._clock_text.value = datetime.now().strftime("%d/%m/%Y · %H:%M:%S")
            try:
                self._clock_text.update()
            except Exception:
                # Controle ainda não está na página ou já foi removido.
                break
            time.sleep(1)
