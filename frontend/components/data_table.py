"""
WMApp Frontend - Data Table Component
Reusable table with responsive columns and error/empty states.
"""

import time
from typing import Callable, List, Optional

import flet as ft

from i18n import t

from components.theme import COLORS, FONTS, RADIUS, SPACING, create_badge, create_button, create_icon_button, get_status_color


class DataTable(ft.Container):
    """Reusable table component.

    Column contract:
    - key: str
    - label: str
    - align: left|center|right (optional, default left)
    - width: fixed width (optional)
    - min_width: fallback width when width not provided (optional)
    - flex: expand weight when width not provided (optional)
    - priority: smaller value = more important (optional, default 1)
    - hideable: can be hidden on small width (optional, default True)
    """

    ACTIONS_WIDTH = 108

    def __init__(
        self,
        columns: List[dict],
        data: Optional[List[dict]] = None,
        on_row_click: Optional[Callable] = None,
        on_edit: Optional[Callable] = None,
        on_delete: Optional[Callable] = None,
        show_actions: bool = True,
        edit_icon: str = ft.Icons.EDIT,
        edit_tooltip: str = None,
        delete_icon: str = ft.Icons.DELETE,
        delete_tooltip: str = None,
        empty_message: str = None,
    ):
        super().__init__()
        self.columns = columns
        self.data = data or []
        self.on_row_click = on_row_click
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.show_actions = show_actions
        self.edit_icon = edit_icon
        self.edit_tooltip = edit_tooltip or t("common.edit")
        self.delete_icon = delete_icon
        self.delete_tooltip = delete_tooltip or t("common.delete")
        self.empty_message = empty_message or t("table.empty")
        self.error_message: Optional[str] = None
        self.error_retry: Optional[Callable] = None
        self._visible_columns: List[dict] = []
        # Numero de linhas-skeleton a renderizar enquanto dados carregam.
        # 0 = sem skeleton (estado vazio normal). > 0 substitui a area de body
        # por linhas placeholder cinza ate set_data() ser chamado.
        self._skeleton_rows: int = 0
        # Timestamp em que o skeleton comecou a ser exibido. Usado para
        # garantir um piso minimo de tempo visivel (senao em respostas
        # rapidas o esqueleto "pisca" e da sensacao de bug).
        self._skeleton_shown_at: float = 0.0

        self._build()

    def _safe_update(self):
        try:
            self.update()
        except Exception:
            # Control may still not be attached to page.
            pass

    def _normalize_align(self, align: str) -> str:
        value = str(align or "left").lower().strip()
        if value in ("center", "right"):
            return value
        return "left"

    def _alignment(self, align: str) -> ft.Alignment:
        if align == "center":
            return ft.Alignment(0, 0)
        if align == "right":
            return ft.Alignment(1, 0)
        return ft.Alignment(-1, 0)

    def _text_align(self, align: str) -> ft.TextAlign:
        if align == "center":
            return ft.TextAlign.CENTER
        if align == "right":
            return ft.TextAlign.RIGHT
        return ft.TextAlign.LEFT

    def _column_width(self, col: dict) -> int:
        width = col.get("width")
        if isinstance(width, (int, float)) and width > 0:
            return int(width)
        min_width = col.get("min_width")
        if isinstance(min_width, (int, float)) and min_width > 0:
            return int(min_width)
        return 120

    def _column_expand(self, col: dict) -> Optional[int]:
        if col.get("width"):
            return None
        flex = col.get("flex")
        if isinstance(flex, (int, float)) and flex > 0:
            return int(flex)
        return None

    def _available_width(self) -> Optional[int]:
        try:
            page = self.page
        except (RuntimeError, Exception):
            return None
        if not page:
            return None
        width = None
        try:
            width = getattr(page, "width", None)
        except Exception:
            width = None
        try:
            window = getattr(page, "window", None)
            if window:
                win_width = getattr(window, "width", None)
                if win_width:
                    width = win_width
        except Exception:
            pass
        if not width:
            return None
        # Sidebar + paddings + safe margin.
        return max(420, int(width) - 360)

    def _select_visible_columns(self) -> List[dict]:
        visible = list(self.columns)
        available = self._available_width()
        if available is None:
            return visible

        required = sum(self._column_width(col) for col in visible)
        if self.show_actions:
            required += self.ACTIONS_WIDTH
        if required <= available:
            return visible

        removable = sorted(
            [col for col in visible if col.get("hideable", True) and int(col.get("priority", 1)) > 1],
            key=lambda col: int(col.get("priority", 1)),
            reverse=True,
        )
        for col in removable:
            if required <= available or len(visible) <= 1:
                break
            if col in visible:
                visible.remove(col)
                required -= self._column_width(col)
        return visible

    def _build_cell(self, col: dict, content: ft.Control, clickable: Optional[Callable]) -> ft.Container:
        align = self._normalize_align(col.get("align", "left"))
        width = col.get("width")
        return ft.Container(
            content=content,
            width=width,
            expand=self._column_expand(col),
            padding=ft.Padding.symmetric(horizontal=14, vertical=9),
            alignment=self._alignment(align),
            on_click=clickable,
        )

    def _build_header(self) -> ft.Container:
        cells: List[ft.Control] = []
        for col in self._visible_columns:
            align = self._normalize_align(col.get("align", "left"))
            cells.append(
                self._build_cell(
                    col,
                    ft.Text(
                        str(col.get("label", "")),
                        size=FONTS["size_sm"],
                        weight=ft.FontWeight.W_600,
                        color=COLORS["text_secondary"],
                        text_align=self._text_align(align),
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    clickable=None,
                )
            )

        if self.show_actions:
            cells.append(
                ft.Container(
                    content=ft.Text(
                        t("table.actions"),
                        size=FONTS["size_sm"],
                        weight=ft.FontWeight.W_600,
                        color=COLORS["text_secondary"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=self.ACTIONS_WIDTH,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=9),
                    alignment=ft.Alignment(0, 0),
                )
            )

        return ft.Container(
            content=ft.Row(cells, spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=COLORS["bg_elevated"],
            border_radius=ft.BorderRadius.only(top_left=RADIUS["md"], top_right=RADIUS["md"]),
            border=ft.Border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )

    def _build_row(self, row: dict, idx: int) -> ft.Container:
        row_bg = COLORS["table_row"] if idx % 2 == 0 else COLORS["table_row_alt"]
        cells: List[ft.Control] = []

        def row_click(_):
            if self.on_row_click:
                self.on_row_click(row)

        for col in self._visible_columns:
            key = str(col.get("key", ""))
            value = row.get(key)
            align = self._normalize_align(col.get("align", "left"))

            if isinstance(value, ft.Control):
                content = value
            elif key == "status":
                display = str(value) if value not in (None, "") else "-"
                content: ft.Control = create_badge(display, get_status_color(display))
            else:
                display = "-" if value in (None, "") else str(value)
                content = ft.Text(
                    display,
                    size=FONTS["size_base"],
                    color=COLORS["text_primary"],
                    text_align=self._text_align(align),
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                )

            # Colunas marcadas com no_row_click (ex.: célula de checkbox) não
            # disparam o clique da linha, para o controle interno tratar o evento.
            cell_click = None if col.get("no_row_click") else row_click
            cells.append(self._build_cell(col, content, cell_click))

        if self.show_actions:

            def handle_edit(_):
                print(f"[DataTable] edit_click row_id={row.get('id')}")
                if self.on_edit:
                    self.on_edit(row)
                else:
                    print("[DataTable] edit_click without on_edit handler")

            def handle_delete(_):
                print(f"[DataTable] delete_click row_id={row.get('id')}")
                if self.on_delete:
                    self.on_delete(row)
                else:
                    print("[DataTable] delete_click without on_delete handler")

            actions = ft.Row(
                [
                    create_icon_button(
                        self.edit_icon,
                        on_click=handle_edit,
                        tooltip=self.edit_tooltip,
                        color=COLORS["accent_secondary"],
                    ),
                    create_icon_button(
                        self.delete_icon,
                        on_click=handle_delete,
                        tooltip=self.delete_tooltip,
                        color=COLORS["accent_error"],
                    ),
                ],
                spacing=2,
                alignment=ft.MainAxisAlignment.CENTER,
            )
            cells.append(
                ft.Container(
                    content=actions,
                    width=self.ACTIONS_WIDTH,
                    padding=ft.Padding.symmetric(horizontal=4),
                    alignment=ft.Alignment(0, 0),
                )
            )

        return ft.Container(
            content=ft.Row(cells, spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=row_bg,
            data=row_bg,
            on_hover=self._handle_hover,
        )

    # Altura aproximada de uma linha real (padding 8 vertical + ~18 de texto).
    SKELETON_ROW_HEIGHT = 44

    def _build_skeleton_bar(self, width_pct: float = 0.6, opacity: float = 0.55) -> ft.Container:
        """Barrinha cinza arredondada que simula um valor de celula."""
        return ft.Container(
            height=10,
            bgcolor=COLORS["bg_elevated"],
            border_radius=4,
            opacity=opacity,
            # Largura proporcional dentro de uma Row que tambem segura o "vazio".
            expand=int(max(1, round(width_pct * 10))),
        )

    def _build_skeleton_cell(self, col: dict, idx: int, col_idx: int) -> ft.Container:
        align = self._normalize_align(col.get("align", "left"))
        # Variacao pseudo-aleatoria pra parecer dado real, nao linhas iguais.
        seed = (idx * 7 + col_idx * 3) % 5
        width_pct = (0.4, 0.55, 0.65, 0.5, 0.75)[seed]
        opacity = 0.45 + (seed % 3) * 0.08

        bar = self._build_skeleton_bar(width_pct=width_pct, opacity=opacity)
        filler_weight = max(1, round((1 - width_pct) * 10))
        filler = ft.Container(expand=filler_weight)

        if align == "right":
            controls = [filler, bar]
        elif align == "center":
            half = ft.Container(expand=max(1, filler_weight // 2))
            controls = [half, bar, half]
        else:
            controls = [bar, filler]

        cell_content = ft.Row(
            controls,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return self._build_cell(col, cell_content, clickable=None)

    def _build_skeleton_row(self, idx: int) -> ft.Container:
        """Linha placeholder com mesma altura das linhas reais."""
        row_bg = COLORS["table_row"] if idx % 2 == 0 else COLORS["table_row_alt"]
        cells: List[ft.Control] = [
            self._build_skeleton_cell(col, idx, col_idx)
            for col_idx, col in enumerate(self._visible_columns)
        ]
        if self.show_actions:
            cells.append(
                ft.Container(
                    content=ft.Container(
                        height=10,
                        bgcolor=COLORS["bg_elevated"],
                        border_radius=4,
                        width=60,
                        opacity=0.4,
                    ),
                    width=self.ACTIONS_WIDTH,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=8),
                    alignment=ft.Alignment(0, 0),
                )
            )
        return ft.Container(
            content=ft.Row(
                cells,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=row_bg,
            height=self.SKELETON_ROW_HEIGHT,
        )

    def _build_skeleton_body(self) -> ft.Control:
        # Renderiza linhas suficientes para preencher visualmente a area de
        # dados — quem nao couber fica fora da scrollview, sem deixar "buraco"
        # vazio embaixo. _skeleton_rows funciona como minimo solicitado.
        count = max(self._skeleton_rows, 25)
        rows = [self._build_skeleton_row(i) for i in range(count)]
        return ft.Column(
            rows,
            spacing=0,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    def _build_empty_state(self) -> ft.Control:
        return ft.Container(
            content=ft.Text(
                self.empty_message,
                size=FONTS["size_base"],
                color=COLORS["text_muted"],
                text_align=ft.TextAlign.CENTER,
            ),
            alignment=ft.Alignment(0, 0),
            padding=SPACING["xl"],
            expand=True,
        )

    def _build_error_state(self) -> ft.Control:
        controls: List[ft.Control] = [
            ft.Icon(ft.Icons.ERROR_OUTLINE, color=COLORS["accent_warning"], size=24),
            ft.Text(
                self.error_message or t("table.error"),
                color=COLORS["text_secondary"],
                text_align=ft.TextAlign.CENTER,
            ),
        ]
        if self.error_retry:
            controls.append(
                create_button(
                    t("table.retry"),
                    icon=ft.Icons.REFRESH,
                    on_click=lambda e: self.error_retry() if self.error_retry else None,
                    primary=False,
                )
            )
        return ft.Container(
            content=ft.Column(
                controls,
                spacing=SPACING["sm"],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            alignment=ft.Alignment(0, 0),
            padding=SPACING["xl"],
            expand=True,
        )

    def _build(self):
        self._visible_columns = self._select_visible_columns()
        header = self._build_header()

        if self.error_message:
            body = self._build_error_state()
        elif self._skeleton_rows > 0 and not self.data:
            body = self._build_skeleton_body()
        elif not self.data:
            body = self._build_empty_state()
        else:
            body = ft.Column(
                [self._build_row(row, idx) for idx, row in enumerate(self.data)],
                spacing=0,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            )

        self.content = ft.Column(
            [
                header,
                ft.Container(content=body, expand=True),
            ],
            spacing=0,
            expand=True,
        )
        self.bgcolor = COLORS["table_row"]
        self.border_radius = RADIUS["md"]
        self.border = ft.Border.all(1, COLORS["border_subtle"])
        self.expand = True

    def _handle_hover(self, e):
        if e.data == "true":
            e.control.bgcolor = COLORS["bg_hover"]
        else:
            e.control.bgcolor = e.control.data
        try:
            e.control.update()
        except Exception:
            pass

    # Tempo minimo (ms) em que o skeleton fica visivel apos show_skeleton.
    # Em respostas rapidas (cache hit, lista pequena), garante que o esqueleto
    # nao "pisque" — fica visivel ao menos esse tempo antes de set_data
    # substituir pelo dado real.
    SKELETON_MIN_VISIBLE_MS = 500

    def set_data(self, data: List[dict]):
        # Se o skeleton apareceu ha menos que o piso, dorme aqui pra completar.
        # set_data normalmente roda de page.run_thread (background) - segurar
        # essa thread por algumas centenas de ms nao bloqueia a UI principal.
        # Evitamos threading.Timer porque o callback dele rodava fora do ciclo
        # de update do Flet e em algumas situacoes o skeleton ficava
        # eternamente em tela.
        if self._skeleton_rows > 0 and self._skeleton_shown_at > 0:
            elapsed_ms = (time.monotonic() - self._skeleton_shown_at) * 1000
            remaining_ms = self.SKELETON_MIN_VISIBLE_MS - elapsed_ms
            if remaining_ms > 0:
                time.sleep(remaining_ms / 1000.0)

        self.data = data or []
        self.error_message = None
        self.error_retry = None
        self._skeleton_rows = 0
        self._skeleton_shown_at = 0.0
        self._build()
        self._safe_update()

    def show_skeleton(self, rows: int = 8):
        """Renderiza N linhas placeholder ate set_data() chegar."""
        self._skeleton_rows = max(0, int(rows))
        self._skeleton_shown_at = time.monotonic()
        self.error_message = None
        self.error_retry = None
        self._build()
        self._safe_update()

    def hide_skeleton(self):
        if self._skeleton_rows == 0:
            return
        self._skeleton_rows = 0
        self._skeleton_shown_at = 0.0
        self._build()
        self._safe_update()

    def set_error(self, message: str, on_retry: Optional[Callable] = None):
        self.error_message = message
        self.error_retry = on_retry
        self.data = []
        self._build()
        self._safe_update()

    def clear_error(self):
        self.error_message = None
        self.error_retry = None
        self._build()
        self._safe_update()

    def refresh_layout(self):
        self._build()
        self._safe_update()
