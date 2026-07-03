"""
Componente de paginação reutilizável.
"""
import flet as ft

from i18n import t
from components.theme import COLORS, SPACING


class Pagination(ft.Container):
    """
    Barra de paginação com botões Anterior/Próximo e indicador de página.

    Uso:
        self.pagination = Pagination(page_size=50, on_change=self._on_page_change)
        # após carregar dados:
        self.pagination.update_state(current_page=0, total_items=426)

    Callback on_change(skip: int) é chamado quando o usuário muda de página.
    """

    def __init__(self, page_size: int = 50, on_change=None):
        super().__init__()
        self._page_size = page_size
        self._current_page = 0
        self._total_items = 0
        self._on_change = on_change

        self._prev_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            icon_color=COLORS["text_secondary"],
            icon_size=16,
            tooltip=t("pagination.prev"),
            on_click=self._go_prev,
            disabled=True,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        self._next_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            icon_color=COLORS["text_secondary"],
            icon_size=16,
            tooltip=t("pagination.next"),
            on_click=self._go_next,
            disabled=True,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        self._label = ft.Text(
            "",
            size=11,
            color=COLORS["text_secondary"],
        )

        self._row = ft.Row(
            [self._prev_btn, self._label, self._next_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=2,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = self._row
        self.padding = ft.padding.symmetric(vertical=4)
        self.visible = False

    @property
    def current_skip(self) -> int:
        return self._current_page * self._page_size

    def update_state(self, current_page: int, total_items: int):
        self._current_page = current_page
        self._total_items = total_items
        total_pages = max(1, -(-total_items // self._page_size))  # ceil division
        start = self._current_page * self._page_size + 1
        end = min((self._current_page + 1) * self._page_size, total_items)

        self._label.value = t("pagination.page", current=self._current_page + 1, total=total_pages, start=start, end=end, items=total_items)
        self._prev_btn.disabled = self._current_page == 0
        self._next_btn.disabled = (self._current_page + 1) >= total_pages
        self.visible = total_items > self._page_size

        try:
            self.update()
        except Exception:
            pass

    def reset(self):
        self._current_page = 0

    def _go_prev(self, e):
        if self._current_page > 0:
            self._current_page -= 1
            self._fire()

    def _go_next(self, e):
        total_pages = max(1, -(-self._total_items // self._page_size))
        if self._current_page + 1 < total_pages:
            self._current_page += 1
            self._fire()

    def _fire(self):
        if self._on_change:
            self._on_change(self.current_skip)
