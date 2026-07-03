"""
WMApp Frontend - Loading Overlay Component
Overlay padronizado para estados de carregamento.
"""
import flet as ft

from components.theme import COLORS


class LoadingOverlay(ft.Container):
    """Indicador de carregamento em barra no topo."""

    def __init__(self, message: str = "Carregando..."):
        self.progress = ft.ProgressBar(
            value=None,  # indeterminado
            color=COLORS["accent_secondary"],
            bgcolor=COLORS["bg_elevated"],
            bar_height=3,
            border_radius=0,
            expand=True,
        )
        super().__init__(
            content=ft.Container(
                content=self.progress,
                height=3,
                expand=True,
            ),
            alignment=ft.Alignment(0, -1),
            expand=True,
            visible=False,
            padding=0,
        )

    def show(self, message: str | None = None):
        """Exibe indicador de carregamento."""
        self.visible = True
        self._safe_update()

    def hide(self):
        """Oculta overlay."""
        self.visible = False
        self._safe_update()

    def _safe_update(self):
        try:
            self.update()
            return
        except Exception:
            pass
        try:
            page = self.page
        except Exception:
            page = None
        if page:
            try:
                page.update()
            except Exception:
                pass
