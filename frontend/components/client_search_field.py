"""
WMApp Frontend - Client Search Field
Campo de busca com autocomplete para seleção de cliente por nome, medidor, Manzana ou Lote.
"""
from typing import Callable, List, Optional

import flet as ft

from i18n import t

from components.theme import COLORS, FONTS, SPACING


class ClientSearchField(ft.Column):
    """Campo de busca de cliente com lista de resultados filtrados em tempo real.

    Busca por nome/medidor num campo de texto e por Manzana+Lote em campos separados.
    Os três filtros se combinam (AND): se Mz estiver preenchido, só mostra clientes daquela manzana.

    Uso:
        field = ClientSearchField(clients=lista_de_clientes, width=430)
        field.selected_id      → ID do cliente selecionado (ou None)
        field.selected_client  → dict completo do cliente (ou None)
    """

    MAX_RESULTS = 8

    def __init__(
        self,
        clients: List[dict] = None,
        width: int = 430,
        on_select: Optional[Callable[[dict], None]] = None,
        label: str = "Cliente",
        on_search: Optional[Callable[[str], List[dict]]] = None,
    ):
        super().__init__(spacing=4, tight=True)
        self._clients = clients or []
        self._on_search = on_search  # se fornecido, busca via API em vez de lista local
        self._width = width
        self._on_select = on_select
        self._selected_id: Optional[str] = None
        self._selected_client: Optional[dict] = None

        self._input = ft.TextField(
            label=label,
            width=width,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            label_style=ft.TextStyle(color=COLORS["text_secondary"]),
            text_style=ft.TextStyle(color=COLORS["text_primary"]),
            cursor_color=COLORS["accent_primary"],
            border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=16, vertical=12),
            hint_text="Nome ou número do medidor...",
            hint_style=ft.TextStyle(color=COLORS["text_muted"]),
            on_change=self._on_change,
            suffix=ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=18),
        )

        self._mz_input = ft.TextField(
            label="Mz",
            width=80,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            label_style=ft.TextStyle(color=COLORS["text_secondary"]),
            text_style=ft.TextStyle(color=COLORS["text_primary"]),
            cursor_color=COLORS["accent_primary"],
            border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=12),
            hint_text="—",
            hint_style=ft.TextStyle(color=COLORS["text_muted"]),
            on_change=self._on_change,
        )

        self._lt_input = ft.TextField(
            label="Lt",
            width=80,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            label_style=ft.TextStyle(color=COLORS["text_secondary"]),
            text_style=ft.TextStyle(color=COLORS["text_primary"]),
            cursor_color=COLORS["accent_primary"],
            border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=12),
            hint_text="—",
            hint_style=ft.TextStyle(color=COLORS["text_muted"]),
            on_change=self._on_change,
        )

        self._results_list = ft.Column(spacing=0, tight=True)
        self._results_container = ft.Container(
            content=self._results_list,
            width=width,
            bgcolor=COLORS["bg_elevated"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=ft.border_radius.only(bottom_left=8, bottom_right=8),
            visible=False,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )

        self.controls = [
            self._input,
            ft.Row([self._mz_input, self._lt_input], spacing=8),
            self._results_container,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    @property
    def selected_client(self) -> Optional[dict]:
        return self._selected_client

    def clear_selection(self):
        self._selected_id = None
        self._selected_client = None
        self._input.value = ""
        self._mz_input.value = ""
        self._lt_input.value = ""
        self._hide_results()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _client_label(self, c: dict) -> str:
        name = c.get("nombre_completo") or "-"
        meter = c.get("numero_medidor") or "-"
        mz = c.get("manzana") or "-"
        lt = c.get("lote") or "-"
        return f"{name}  |  Medidor {meter}  |  Mz {mz} / Lt {lt}"

    def _matches(self, c: dict, query: str, mz_q: str, lt_q: str) -> bool:
        if mz_q:
            if (c.get("manzana") or "").lower() != mz_q:
                return False
        if lt_q:
            if (c.get("lote") or "").lower() != lt_q:
                return False
        if query:
            name = (c.get("nombre_completo") or "").lower()
            meter = (c.get("numero_medidor") or "").lower()
            if query not in name and query not in meter:
                return False
        return True

    def _on_change(self, e):
        self._selected_id = None
        self._selected_client = None

        query = (self._input.value or "").strip().lower()
        mz_q = (self._mz_input.value or "").strip().lower()
        lt_q = (self._lt_input.value or "").strip().lower()

        if not query and not mz_q and not lt_q:
            self._hide_results()
            return

        if self._on_search and len(query) >= 2:
            # Modo lazy: delega a busca ao caller (ex: API)
            results = self._on_search(query)
            self._show_results(results[: self.MAX_RESULTS], total=len(results))
        else:
            matches = [c for c in self._clients if self._matches(c, query, mz_q, lt_q)]
            self._show_results(matches[: self.MAX_RESULTS], total=len(matches))

    def _show_results(self, clients: List[dict], total: int):
        self._results_list.controls.clear()

        if not clients:
            self._results_list.controls.append(
                ft.Container(
                    content=ft.Text(
                        t("client_search.none"),
                        color=COLORS["text_muted"],
                        size=FONTS["size_sm"],
                        italic=True,
                    ),
                    padding=ft.padding.symmetric(horizontal=16, vertical=10),
                )
            )
        else:
            for c in clients:
                label = self._client_label(c)

                def make_click(cl):
                    def on_click(e):
                        self._select(cl)
                    return on_click

                item = ft.Container(
                    content=ft.Text(
                        label,
                        size=FONTS["size_sm"],
                        color=COLORS["text_primary"],
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                    padding=ft.padding.symmetric(horizontal=16, vertical=9),
                    on_click=make_click(c),
                    on_hover=self._on_item_hover,
                    border_radius=4,
                    ink=True,
                )
                self._results_list.controls.append(item)

            if total > self.MAX_RESULTS:
                self._results_list.controls.append(
                    ft.Container(
                        content=ft.Text(
                            f"… +{total - self.MAX_RESULTS} resultado(s). Refine a busca.",
                            color=COLORS["text_muted"],
                            size=11,
                            italic=True,
                        ),
                        padding=ft.padding.symmetric(horizontal=16, vertical=6),
                    )
                )

        self._results_container.visible = True
        self._safe_update(self._results_container)

    def _hide_results(self):
        self._results_container.visible = False
        self._safe_update(self._results_container)

    def _select(self, client: dict):
        self._selected_id = str(client.get("id", ""))
        self._selected_client = client
        self._input.value = client.get("nombre_completo") or "-"
        self._mz_input.value = ""
        self._lt_input.value = ""
        self._hide_results()
        self._safe_update(self._input)
        self._safe_update(self._mz_input)
        self._safe_update(self._lt_input)
        if self._on_select:
            self._on_select(client)

    def _on_item_hover(self, e: ft.HoverEvent):
        e.control.bgcolor = COLORS["bg_surface"] if e.data == "true" else None
        self._safe_update(e.control)

    def _safe_update(self, control: ft.Control):
        try:
            control.update()
        except Exception:
            pass
