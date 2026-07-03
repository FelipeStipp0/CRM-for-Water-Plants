"""
Campo de busca compacto de cliente para uso em painéis estreitos (ex: painel do mapa).
Sem campos Mz/Lt — apenas busca por nome/CI.
"""
from typing import Callable, List, Optional

import flet as ft

from components.theme import COLORS, FONTS


class MiniClientSearch(ft.Column):
    """
    TextField + dropdown de sugestões compacto.
    Ocupa apenas a largura do container pai (expand=True).
    """

    MAX_RESULTS = 6

    def __init__(
        self,
        clients: List[dict],
        on_select: Optional[Callable[[Optional[dict]], None]] = None,
        initial_client: Optional[dict] = None,
        placeholder: str = "Buscar cliente...",
    ):
        super().__init__(spacing=0, tight=True)
        self._clients = clients
        self._on_select = on_select
        self._selected: Optional[dict] = initial_client

        initial_text = initial_client.get("nombre_completo", "") if initial_client else ""

        self._input = ft.TextField(
            value=initial_text,
            hint_text=placeholder,
            hint_style=ft.TextStyle(color=COLORS["text_muted"], size=11),
            text_style=ft.TextStyle(color=COLORS["text_primary"], size=11),
            border_color=COLORS["border"],
            focused_border_color=COLORS["accent_primary"],
            border_radius=6,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            expand=True,
            on_change=self._on_change,
            suffix=ft.Icon(ft.Icons.CLOSE, color=COLORS["text_muted"], size=14) if initial_client else ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=14),
        )
        self._input.on_focus = self._on_focus

        self._results_list = ft.Column(spacing=0, tight=True)
        self._results_container = ft.Container(
            content=self._results_list,
            bgcolor=COLORS["bg_elevated"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=ft.border_radius.only(bottom_left=6, bottom_right=6),
            visible=False,
            shadow=ft.BoxShadow(
                blur_radius=6,
                color=ft.Colors.with_opacity(0.2, ft.Colors.BLACK),
                offset=ft.Offset(0, 3),
            ),
        )

        self.controls = [
            ft.Row([self._input], spacing=0),
            self._results_container,
        ]

    @property
    def selected(self) -> Optional[dict]:
        return self._selected

    @property
    def selected_id(self) -> str:
        return str(self._selected["id"]) if self._selected else ""

    def set_initial(self, client: Optional[dict]):
        self._selected = client
        self._input.value = client.get("nombre_completo", "") if client else ""
        self._input.suffix = ft.Icon(
            ft.Icons.CLOSE if client else ft.Icons.SEARCH,
            color=COLORS["text_muted"], size=14,
        )
        self._results_container.visible = False
        try:
            self.update()
        except Exception:
            pass

    def _on_focus(self, e):
        # Ao focar, mostra sugestões com base no texto atual (permite substituir o vínculo)
        q = (self._input.value or "").strip().lower()
        if q:
            self._filter(q)
        else:
            # Campo vazio: mostra primeiros clientes sem filtro
            self._show(self._clients[: self.MAX_RESULTS], total=len(self._clients))

    def _on_change(self, e):
        self._selected = None
        self._input.suffix = ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=14)
        q = (self._input.value or "").strip().lower()
        if not q:
            self._hide()
            if self._on_select:
                self._on_select(None)
            return
        self._filter(q)

    def _filter(self, q: str):
        matches = [
            c for c in self._clients
            if q in (c.get("nombre_completo") or "").lower()
            or q in (c.get("ci_ruc") or "").lower()
        ]
        self._show(matches[: self.MAX_RESULTS], total=len(matches))

    def _show(self, clients: List[dict], total: int):
        self._results_list.controls.clear()

        if not clients:
            self._results_list.controls.append(
                ft.Container(
                    content=ft.Text("Sem resultados", color=COLORS["text_muted"], size=11, italic=True),
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                )
            )
        else:
            # Opção para remover vínculo
            clear_item = ft.Container(
                content=ft.Text("— Sem cliente —", color=COLORS["text_muted"], size=11, italic=True),
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                on_click=self._clear_selection,
                ink=True,
            )
            self._results_list.controls.append(clear_item)

            for c in clients:
                name = c.get("nombre_completo") or "-"
                ci = c.get("ci_ruc") or ""
                mz = c.get("manzana") or ""
                lt = c.get("lote") or ""
                tag = f"  Mz{mz}/Lt{lt}" if mz else ""

                def make_click(cl):
                    def on_click(ev):
                        self._select(cl)
                    return on_click

                item = ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(name, size=11, color=COLORS["text_primary"], overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                            ft.Text(f"{ci}{tag}", size=10, color=COLORS["text_secondary"], overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                        ],
                        spacing=1,
                        tight=True,
                    ),
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    on_click=make_click(c),
                    on_hover=lambda ev: setattr(ev.control, 'bgcolor', COLORS["bg_surface"] if ev.data == "true" else None) or ev.control.update(),
                    ink=True,
                )
                self._results_list.controls.append(item)

            if total > self.MAX_RESULTS:
                self._results_list.controls.append(
                    ft.Container(
                        content=ft.Text(f"+{total - self.MAX_RESULTS} mais. Refine a busca.", color=COLORS["text_muted"], size=10, italic=True),
                        padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    )
                )

        self._results_container.visible = True
        self._safe_update(self._results_container)

    def _hide(self):
        self._results_container.visible = False
        self._safe_update(self._results_container)

    def _select(self, client: dict):
        self._selected = client
        self._input.value = client.get("nombre_completo") or "-"
        self._input.suffix = ft.Icon(ft.Icons.CLOSE, color=COLORS["text_muted"], size=14)
        self._hide()
        self._safe_update(self._input)
        if self._on_select:
            self._on_select(client)

    def _clear_selection(self, e):
        self._selected = None
        self._input.value = ""
        self._input.suffix = ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=14)
        self._hide()
        self._safe_update(self._input)
        if self._on_select:
            self._on_select(None)

    def _safe_update(self, control: ft.Control):
        try:
            control.update()
        except Exception:
            pass
