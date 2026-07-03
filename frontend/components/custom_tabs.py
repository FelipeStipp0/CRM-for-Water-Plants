"""
WMApp Frontend - Custom TabBar Component
Implementação customizada de tabs para Flet 0.80+
"""
import flet as ft
from typing import List, Callable
from components.theme import COLORS, FONTS, SPACING


class TabItem:
    """Representa uma aba."""
    def __init__(self, label: str, content: ft.Control, icon=None):
        self.label = label
        self.content = content
        self.icon = icon


class CustomTabs(ft.Container):
    """Componente de abas customizado que funciona no Flet 0.80+."""
    
    def __init__(self, tabs: List[TabItem], selected_index: int = 0):
        super().__init__()
        self._tabs = tabs
        self._selected_index = selected_index
        self._tab_buttons = []
        self._content_container = ft.Container(expand=True)
        
        self._build()
    
    def _build(self):
        """Constrói o layout."""
        # Tab bar (botões)
        self._tab_buttons = []
        for idx, tab in enumerate(self._tabs):
            is_active = idx == self._selected_index
            
            btn_content = []
            if tab.icon:
                btn_content.append(ft.Icon(tab.icon, size=18, 
                    color=COLORS["accent_primary"] if is_active else COLORS["text_muted"]))
            btn_content.append(ft.Text(
                tab.label,
                size=FONTS["size_sm"],
                color=COLORS["text_primary"] if is_active else COLORS["text_muted"],
                weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
            ))
            
            btn = ft.Container(
                content=ft.Row(btn_content, spacing=6, alignment=ft.MainAxisAlignment.CENTER),
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                border=ft.Border.only(bottom=ft.BorderSide(
                    2, COLORS["accent_primary"] if is_active else "transparent"
                )),
                on_click=lambda e, i=idx: self._on_tab_click(i),
                on_hover=self._on_hover,
            )
            self._tab_buttons.append(btn)
        
        tab_bar = ft.Container(
            content=ft.Row(self._tab_buttons, spacing=0),
            border=ft.Border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )
        
        # Content
        self._update_content()
        
        # Layout
        self.content = ft.Column(
            [tab_bar, self._content_container],
            spacing=0,
            expand=True,
        )
        self.expand = True
    
    def _on_tab_click(self, index: int):
        """Muda para a aba selecionada."""
        self._selected_index = index
        self._build()
        self.update()
    
    def _on_hover(self, e):
        """Efeito hover."""
        if e.data == "true":
            e.control.bgcolor = COLORS["bg_elevated"]
        else:
            e.control.bgcolor = None
        e.control.update()
    
    def _update_content(self):
        """Atualiza conteúdo visível."""
        if 0 <= self._selected_index < len(self._tabs):
            self._content_container.content = self._tabs[self._selected_index].content
