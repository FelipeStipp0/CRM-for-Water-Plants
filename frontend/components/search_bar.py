"""
WMApp Frontend - Search Bar Component
Barra de busca unificada com filtros
"""
import flet as ft

from i18n import t
from typing import Callable, Optional
from components.theme import COLORS, FONTS, RADIUS


class SearchBar(ft.Container):
    """Barra de busca com ícone e botão."""
    
    def __init__(
        self,
        placeholder: str = "Buscar...",
        on_search: Optional[Callable] = None,
        on_change: Optional[Callable] = None,
        width: int = None,
    ):
        super().__init__()
        self.placeholder = placeholder
        self.on_search_callback = on_search
        self.on_change_callback = on_change
        
        self.search_field = ft.TextField(
            hint_text=placeholder,
            border=ft.InputBorder.NONE,
            bgcolor="transparent",
            text_style=ft.TextStyle(color=COLORS["text_primary"], size=FONTS["size_base"]),
            hint_style=ft.TextStyle(color=COLORS["text_muted"]),
            expand=True,
            on_change=self._handle_change,
            on_submit=self._handle_submit,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=10),
        )

        self.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=18),
                    self.search_field,
                    ft.IconButton(
                        icon=ft.Icons.CLEAR,
                        icon_color=COLORS["text_muted"],
                        icon_size=14,
                        on_click=self._clear,
                        tooltip=t("search.clear"),
                        style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                    ),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=COLORS["bg_input"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=RADIUS["md"],
            padding=ft.Padding.symmetric(horizontal=12),
        )
        
        self.width = width
    
    def _handle_change(self, e):
        """Chama callback a cada alteração (debounce pode ser adicionado)."""
        if self.on_change_callback:
            self.on_change_callback(e.control.value)
    
    def _handle_submit(self, e):
        """Chama callback ao pressionar Enter."""
        if self.on_search_callback:
            self.on_search_callback(e.control.value)
    
    def _clear(self, e):
        """Limpa o campo de busca."""
        self.search_field.value = ""
        self.search_field.update()
        if self.on_search_callback:
            self.on_search_callback("")
    
    @property
    def value(self) -> str:
        """Retorna valor atual."""
        return self.search_field.value or ""
    
    @value.setter
    def value(self, val: str):
        """Define valor."""
        self.search_field.value = val
        self.search_field.update()
