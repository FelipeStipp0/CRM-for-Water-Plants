"""
WMApp Frontend - Mapa de Manzanas
Visualização geoespacial dos lotes com status de pagamento e cadastro.
"""
import threading
from typing import Optional

import flet as ft
from utils.errors import friendly_error
import flet_map as ftm

from components.loading_overlay import LoadingOverlay
from components.mini_client_search import MiniClientSearch
from components.theme import COLORS, FONTS, create_button
from config.local_settings import get_api_url, get_mapbox_tile_url
from services.api_client import APIError, api as api_client
from i18n import t


def _hex_opacity(hex_color: str, opacity: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(opacity * 255)
    return f"#{a:02X}{r:02X}{g:02X}{b:02X}"


def _lote_color(has_client: bool, meses_atraso: int, threshold: int) -> str:
    """
    Cor do lote baseada em dados reais do BD:
    - Sem cliente vinculado → cinza
    - Cliente em dia (ou sem fatura vencida) → verde
    - Cliente com atraso < threshold → amarelo
    - Cliente com atraso >= threshold → vermelho
    """
    if not has_client:
        return "#546E7A"  # cinza-azulado: sem cadastro
    if meses_atraso == 0:
        return "#66BB6A"  # verde: em dia
    if meses_atraso < threshold:
        return "#FFCA28"  # amarelo: atrasado mas abaixo do corte
    return "#EF5350"      # vermelho: atrasado acima do corte


class MapView(ft.Column):
    """Aba Mapa — manzanas com overlay GeoJSON e status de pagamento."""

    def __init__(self):
        super().__init__(expand=True, spacing=0)

        self._geojson: Optional[dict] = None
        self._client_map: dict = {}
        self._all_clients: list = []
        self._threshold = 3
        self._selected_feat_id: Optional[int] = None

        # Modo de atribuição em massa: {feat_id: client_id}
        self._assign_mode = False
        self._assign_selections: dict = {}  # feat_id → client_id

        self._overlay = LoadingOverlay()
        self._status_text = ft.Text(
            "Carregando mapa...", size=FONTS["size_sm"], color=COLORS["text_secondary"]
        )

        self._tile_url = get_mapbox_tile_url()

        self._map = ftm.Map(
            expand=True,
            initial_center=ftm.MapLatitudeLongitude(-25.2228, -54.7029),
            initial_zoom=15.0,
            bgcolor="#0D1B2A",
            interaction_configuration=ftm.InteractionConfiguration(
                flags=ftm.InteractionFlag.ALL,
            ),
            on_tap=self._on_map_tap,
            layers=self._build_layers([], []),
        )

        self._detail_panel = self._build_empty_panel()

        self._side_col = ft.Column(
            [
                self._build_legend(),
                ft.Divider(height=1, color=COLORS["border"]),
                self._build_tools_section(),
                ft.Divider(height=1, color=COLORS["border"]),
                self._detail_panel,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # Layout completo do mapa — montado só depois de confirmar que há GeoJSON
        # (ver _show_map_ui). Assim o Mapbox não é carregado quando a org não tem mapa.
        self._map_layout = [
            self._overlay,
            ft.Row(
                expand=True,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(content=self._map, expand=True),
                    ft.Container(
                        content=self._side_col,
                        width=280,
                        bgcolor=COLORS["bg_surface"],
                        border=ft.Border(left=ft.BorderSide(1, COLORS["border"])),
                        padding=ft.padding.all(12),
                    ),
                ],
            ),
            ft.Container(
                content=ft.Row(
                    [ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=COLORS["text_secondary"]),
                     self._status_text],
                    spacing=6,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                bgcolor=COLORS["bg_elevated"],
                border=ft.Border(top=ft.BorderSide(1, COLORS["border"])),
            ),
        ]

        # Conteúdo inicial: apenas carregamento (sem o mapa). O mapa só entra na
        # árvore em _show_map_ui, evitando o load do Mapbox sem GeoJSON.
        self.controls = [
            self._overlay,
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=ft.Column(
                    [
                        ft.ProgressRing(width=28, height=28, color=COLORS["accent_primary"]),
                        ft.Text(t("map.loading"), size=FONTS["size_sm"], color=COLORS["text_secondary"]),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=12,
                ),
            ),
        ]

    def _show_map_ui(self):
        """Monta o layout do mapa (Mapbox) — chamado só quando há GeoJSON."""
        if self.controls is self._map_layout:
            return
        self.controls = self._map_layout
        try:
            self.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def _build_layers(self, polygons, markers) -> list:
        layers = [
            ftm.TileLayer(
                url_template=self._tile_url,
                on_image_error=lambda e: None,
            ),
        ]
        if polygons:
            layers.append(ftm.PolygonLayer(polygons=polygons))
        if markers:
            layers.append(ftm.MarkerLayer(markers=markers))
        return layers

    def _refresh_map(self, polygons, markers=None):
        if markers is None:
            markers = self._current_markers()
        self._map.layers = self._build_layers(polygons, markers)
        try:
            self._map.update()
        except Exception:
            pass

    def _current_markers(self):
        for layer in self._map.layers:
            if isinstance(layer, ftm.MarkerLayer):
                return layer.markers
        return []

    def _current_polygons(self):
        for layer in self._map.layers:
            if isinstance(layer, ftm.PolygonLayer):
                return layer.polygons
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def did_mount(self):
        threading.Thread(target=self._load_all, daemon=True).start()

    def _load_all(self):
        self._set_loading(True, t("map.loading"))
        try:
            try:
                # GeoJSON primeiro: se a org não tem mapa, vamos direto para a
                # tela "sem mapa" sem montar o Mapbox nem chamar mais nada.
                self._geojson = api_client.get("/map/geojson")
                bounds = api_client.get("/map/bounds")
            except APIError as e:
                if e.status_code == 404 and "no_geojson" in str(e.detail):
                    self._set_loading(False)
                    self._show_no_geojson_screen()
                    return
                raise

            self._map.initial_center = ftm.MapLatitudeLongitude(
                bounds["center_lat"], bounds["center_lon"]
            )

            # Tiles direto do Mapbox (CDN) em vez do proxy do backend — elimina o
            # salto duplo que deixava o carregamento lento. Fallback: proxy.
            try:
                cfg = api_client.get("/map/tile-config")
                if cfg.get("url_template"):
                    self._tile_url = cfg["url_template"]
            except Exception:
                pass

            try:
                settings = api_client.get("/settings/")
                self._threshold = settings.get("meses_atraso_corte", 3)
            except Exception:
                pass

            try:
                overdue = api_client.get("/map/overdue-by-code")
                self._client_map = {}
                for item in overdue:
                    raw = item.get("code") or ""
                    if "-" in raw:
                        mz, lt = raw.split("-", 1)
                        norm = f"{mz.lstrip('0') or '0'}-{lt.lstrip('0') or '0'}"
                    else:
                        norm = raw
                    self._client_map[norm] = item
            except Exception:
                self._client_map = {}

            try:
                self._all_clients = api_client.get("/clients/?limit=500")
            except Exception:
                self._all_clients = []

            # Confirmado que há GeoJSON: agora sim monta o mapa (Mapbox) na árvore.
            polygons = self._make_polygons()
            self._map.layers = self._build_layers(polygons, [])
            self._show_map_ui()
            self._set_status(f"{len(self._geojson['features'])} lotes cargados")
        except APIError as e:
            self._show_map_ui()
            self._set_status(t("common.error", detail=e.detail), error=True)
        except Exception as e:
            self._show_map_ui()
            self._set_status(t("common.error_unexpected", err=e), error=True)
        finally:
            self._set_loading(False)

    def _show_no_geojson_screen(self):
        """Substitui o conteúdo pelo painel de propaganda quando a org não tem GeoJSON."""
        no_geojson_view = ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.MAP_OUTLINED, size=72, color=COLORS["text_muted"]),
                    ft.Text(
                        t("map.no_map_title"),
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color=COLORS["text_primary"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        t("map.no_map_desc"),
                        size=13,
                        color=COLORS["text_secondary"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=16),
                    ft.Row(
                        [
                            create_button(
                                t("map.upload_geojson"),
                                icon=ft.Icons.UPLOAD_FILE,
                                on_click=self._open_geojson_upload,
                                primary=True,
                            ),
                            create_button(
                                t("map.request_survey"),
                                icon=ft.Icons.SUPPORT_AGENT,
                                on_click=lambda e: None,
                                primary=False,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=12,
                    ),
                    ft.Text(
                        "¿No tenés el archivo? Contactanos y hacemos el relevamiento de tu ciudad.",
                        size=11,
                        color=COLORS["text_muted"],
                        text_align=ft.TextAlign.CENTER,
                        italic=True,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=12,
            ),
        )

        self.controls = [
            self._overlay,
            no_geojson_view,
        ]
        try:
            self.update()
        except Exception:
            pass

    async def _open_geojson_upload(self, e):
        # Flet 0.84: FilePicker é serviço; pick_files é async e retorna os arquivos.
        if not hasattr(self, "_geojson_picker"):
            self._geojson_picker = ft.FilePicker()
        if self.page and self._geojson_picker not in self.page.services:
            self.page.services.append(self._geojson_picker)
        files = await self._geojson_picker.pick_files(
            allowed_extensions=["geojson", "json"],
            dialog_title=t("map.dialog_geojson"),
        )
        if not files:
            return
        path = files[0].path
        self._set_loading(True, "Subiendo GeoJSON...")
        try:
            result = api_client.post_file("/map/geojson/upload", file_path=path, field="file")
            features = result.get("features", 0)
            self._set_loading(False)
            # Recarrega o mapa
            threading.Thread(target=self._load_all, daemon=True).start()
            self._set_status(f"GeoJSON subido — {features} lotes.")
        except APIError as err:
            self._set_loading(False)
            self._set_status(friendly_error(err), error=True)
        except Exception as err:
            self._set_loading(False)
            self._set_status(friendly_error(err), error=True)

    # ------------------------------------------------------------------
    # Polígonos
    # ------------------------------------------------------------------

    def _build_client_lookup(self) -> set[str]:
        """Retorna set de codes (mz-lt normalizados) com cliente vinculado no BD."""
        codes = set()
        for c in self._all_clients:
            mz = str(c.get("manzana") or "").strip()
            lt = str(c.get("lote") or "").strip()
            if mz and lt:
                # Normaliza zeros à esquerda para bater com o CODE do GeoJSON
                codes.add(f"{mz.lstrip('0') or '0'}-{lt.lstrip('0') or '0'}")
        return codes

    def _norm_code(self, code: str) -> str:
        if "-" not in code:
            return code
        mz, lt = code.split("-", 1)
        return f"{mz.lstrip('0') or '0'}-{lt.lstrip('0') or '0'}"

    def _make_polygons(self):
        linked_codes = self._build_client_lookup()
        polygons = []
        for feature in self._geojson["features"]:
            props = feature["properties"]
            code = props.get("CODE") or ""
            norm = self._norm_code(code)
            has_client = norm in linked_codes
            client_data = self._client_map.get(norm, self._client_map.get(code, {}))
            meses_atraso = client_data.get("meses_atraso", 0)
            color = _lote_color(has_client, meses_atraso, self._threshold)

            for polygon in feature["geometry"]["coordinates"]:
                points = [ftm.MapLatitudeLongitude(pt[1], pt[0]) for pt in polygon[0]]
                polygons.append(
                    ftm.PolygonMarker(
                        coordinates=points,
                        color=_hex_opacity(color, 0.50),
                        border_color=_hex_opacity(color, 0.90),
                        border_stroke_width=1.5,
                        label=code if code else None,
                        label_text_style=ft.TextStyle(
                            size=8, color="#FFFFFF", weight=ft.FontWeight.BOLD,
                        ),
                    )
                )
        return polygons

    # ------------------------------------------------------------------
    # Interação com o mapa
    # ------------------------------------------------------------------

    def _on_map_tap(self, e: ftm.MapTapEvent):
        lat, lon = e.coordinates.latitude, e.coordinates.longitude
        clicked = self._find_feature_at(lat, lon)
        if clicked:
            if self._assign_mode:
                self._show_manzana_assign(clicked)
            else:
                self._show_detail(clicked)
        else:
            self._place_pin(lat, lon)

    def _find_feature_at(self, lat: float, lon: float):
        if not self._geojson:
            return None
        best, best_area = None, float("inf")
        for feature in self._geojson["features"]:
            for polygon in feature["geometry"]["coordinates"]:
                ring = polygon[0]
                lats = [p[1] for p in ring]
                lons = [p[0] for p in ring]
                if min(lats) <= lat <= max(lats) and min(lons) <= lon <= max(lons):
                    area = (max(lats) - min(lats)) * (max(lons) - min(lons))
                    if area < best_area:
                        best_area = area
                        best = feature
        return best

    # ------------------------------------------------------------------
    # Painel de detalhe (modo normal)
    # ------------------------------------------------------------------

    def _show_detail(self, feature: dict):
        props = feature["properties"]
        code = props.get("CODE") or "—"
        feat_id = props.get("FeatId1", 0)

        norm = self._norm_code(code) if code != "—" else ""
        linked_codes = self._build_client_lookup()
        has_client = norm in linked_codes

        client_data = self._client_map.get(norm, self._client_map.get(code, {}))
        meses_atraso = client_data.get("meses_atraso", 0)
        color = _lote_color(has_client, meses_atraso, self._threshold)

        # Cliente vinculado a este lote
        linked_client = next(
            (c for c in self._all_clients
             if self._norm_code(f"{c.get('manzana','')}-{c.get('lote','')}") == norm),
            None,
        )

        cad_label = t("map.linked") if has_client else t("map.no_record")
        pag_label = t("map.payment.up_to_date") if meses_atraso == 0 else t("map.payment.pending", m=meses_atraso)

        coords = feature["geometry"]["coordinates"][0][0]
        avg_lat = sum(p[1] for p in coords) / len(coords)
        avg_lon = sum(p[0] for p in coords) / len(coords)
        self._place_pin(avg_lat, avg_lon)

        code_field = ft.TextField(
            value=code if code != "—" else "",
            hint_text=t("map.hint.mz_lt"),
            dense=True,
            expand=True,
            border_color=COLORS["border"],
            focused_border_color=COLORS["accent_primary"],
            text_style=ft.TextStyle(size=FONTS["size_sm"]),
        )
        self._selected_code_field = code_field
        self._selected_feat_id = feat_id

        client_info_rows = []
        if linked_client:
            client_info_rows = [
                _info_row(t("map.info.client"), linked_client.get("nombre_completo") or "—"),
                _info_row(t("map.info.ci_ruc"), linked_client.get("ci_ruc") or "—"),
            ]
        else:
            client_info_rows = [
                ft.Text("Nenhum cliente vinculado.", size=FONTS["size_xs"], color=COLORS["text_muted"], italic=True),
            ]

        panel = ft.Column(
            [
                ft.Container(
                    content=ft.Text(code, size=FONTS["size_lg"], weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                    bgcolor=color,
                    border_radius=6,
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    width=float("inf"),
                ),
                ft.Divider(height=1, color=COLORS["border"]),
                _info_row(t("map.info.status"), cad_label),
                _info_row(t("map.info.payment"), pag_label),
                ft.Divider(height=1, color=COLORS["border"]),
                *client_info_rows,
                ft.Divider(height=1, color=COLORS["border"]),
                ft.Text("Manzana/Lote", size=FONTS["size_xs"], color=COLORS["text_secondary"]),
                ft.Row([code_field]),
                create_button(
                    t("common.save"),
                    icon=ft.Icons.SAVE_OUTLINED,
                    on_click=lambda e, fid=feat_id: self._save_code(fid, e),
                    primary=True,
                ),
            ],
            spacing=8,
            tight=True,
        )
        self._set_detail(panel)

    # ------------------------------------------------------------------
    # Modo atribuição em massa
    # ------------------------------------------------------------------

    def _show_manzana_assign(self, feature: dict):
        """Abre painel de atribuição para todos os lotes da manzana clicada."""
        props = feature["properties"]
        code = props.get("CODE") or ""
        if not code or "-" not in code:
            self._set_status("Lote sem CODE definido. Gere CODEs primeiro.", error=True)
            return

        manzana = code.split("-")[0]

        # Todos os lotes dessa manzana
        lotes = []
        for f in self._geojson["features"]:
            c = f["properties"].get("CODE") or ""
            if c.startswith(f"{manzana}-"):
                lotes.append(f)
        lotes.sort(key=lambda f: f["properties"].get("CODE") or "")

        # Clientes já atribuídos nessa manzana (pelo campo manzana/lote do BD).
        # Normaliza lote removendo zeros à esquerda para comparar com o CODE do GeoJSON.
        assigned_by_code: dict[str, dict] = {}
        for c in self._all_clients:
            mz = str(c.get("manzana") or "").strip().lstrip("0") or "0"
            lt = str(c.get("lote") or "").strip().lstrip("0") or ""
            if mz == manzana.lstrip("0") and lt:
                # Chave normalizada: sem zeros à esquerda
                assigned_by_code[f"{mz}-{lt}"] = c

        # Clientes ordenados para o search field
        sorted_clients = sorted(self._all_clients, key=lambda x: x.get("nombre_completo", ""))

        def _norm_code(code: str) -> str:
            """Normaliza CODE removendo zeros à esquerda de ambas as partes."""
            if "-" not in code:
                return code
            mz_part, lt_part = code.split("-", 1)
            return f"{mz_part.lstrip('0') or '0'}-{lt_part.lstrip('0') or '0'}"

        self._assign_selections = {}
        # Pré-popula com vínculos existentes
        for f in lotes:
            lote_code = _norm_code(f["properties"].get("CODE") or "")
            feat_id = f["properties"].get("FeatId1")
            existing = assigned_by_code.get(lote_code)
            if existing:
                self._assign_selections[feat_id] = existing["id"]

        rows = []
        for f in lotes:
            raw_code = f["properties"].get("CODE") or ""
            lote_code = _norm_code(raw_code)
            lote_num = raw_code.split("-")[1] if "-" in raw_code else raw_code
            feat_id = f["properties"].get("FeatId1")
            initial_client = assigned_by_code.get(lote_code)

            search = MiniClientSearch(
                clients=sorted_clients,
                initial_client=initial_client,
                placeholder=t("map.search_placeholder"),
                on_select=lambda cl, fid=feat_id: self._assign_selections.update(
                    {fid: cl["id"] if cl else ""}
                ),
            )

            linked_text = None
            if initial_client:
                linked_text = ft.Text(
                    f"✓ Vinculado via importação",
                    size=9,
                    color=COLORS.get("accent_success", "#66BB6A"),
                    italic=True,
                )

            rows.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                f"Lote {lote_num}",
                                size=FONTS["size_xs"],
                                weight=ft.FontWeight.BOLD,
                                color=COLORS["text_primary"],
                            ),
                            *(([linked_text]) if linked_text else []),
                            search,
                        ],
                        spacing=3,
                        tight=True,
                    ),
                    padding=ft.padding.symmetric(vertical=8),
                    border=ft.Border(bottom=ft.BorderSide(1, COLORS["border"])),
                )
            )

        linked_count = len(assigned_by_code)
        panel = ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.EDIT_LOCATION_ALT, size=16, color=COLORS["accent_primary"]),
                        ft.Text(f"Manzana {manzana}", size=FONTS["size_base"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    ],
                    spacing=6,
                ),
                ft.Text(
                    f"{len(lotes)} lote(s)  ·  {linked_count} já vinculado(s)",
                    size=FONTS["size_xs"],
                    color=COLORS["text_secondary"],
                ),
                ft.Divider(height=1, color=COLORS["border"]),
                ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO, expand=True),
                ft.Divider(height=1, color=COLORS["border"]),
                create_button(
                    t("map.save_assignments"),
                    icon=ft.Icons.SAVE_OUTLINED,
                    on_click=lambda e, mz=manzana, ls=lotes: self._save_assignments(mz, ls),
                    primary=True,
                ),
            ],
            spacing=8,
            expand=True,
        )
        self._set_detail(panel)
        self._set_status(f"Manzana {manzana} — {len(lotes)} lotes, {linked_count} já vinculados.")

    def _save_assignments(self, manzana: str, lotes: list):
        assignments = []
        for f in lotes:
            feat_id = f["properties"].get("FeatId1")
            client_id = self._assign_selections.get(feat_id, "")
            if not client_id:
                continue
            code = f["properties"].get("CODE") or ""
            lote_num = (code.split("-")[1] if "-" in code else code).lstrip("0") or "0"
            assignments.append({
                "client_id": client_id,
                "manzana": manzana.lstrip("0") or "0",
                "lote": lote_num,
            })

        if not assignments:
            self._set_status("Nenhum cliente selecionado.", error=True)
            return

        try:
            result = api_client.post("/clients/bulk/assign-lote", data=assignments)
            updated = result.get("updated", 0)
            errors = result.get("errors", [])
            # Recarrega lista de clientes
            try:
                self._all_clients = api_client.get("/clients/?limit=500")
            except Exception:
                pass
            msg = f"{updated} cliente(s) atribuído(s) à manzana {manzana}."
            if errors:
                msg += f" {len(errors)} erro(s)."
            self._set_status(msg, error=bool(errors))
        except APIError as err:
            self._set_status(friendly_error(err), error=True)

    # ------------------------------------------------------------------
    # Ferramentas (painel lateral fixo)
    # ------------------------------------------------------------------

    def _build_tools_section(self) -> ft.Column:
        self._gen_mz_field = ft.TextField(
            hint_text=t("map.hint.mz"),
            dense=True,
            border_color=COLORS["border"],
            focused_border_color=COLORS["accent_primary"],
            text_style=ft.TextStyle(size=FONTS["size_sm"]),
        )

        self._assign_btn_label = ft.Text("Atribuir clientes", size=FONTS["size_sm"])
        self._assign_btn = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.EDIT_LOCATION_ALT, size=16),
                self._assign_btn_label,
            ], spacing=6, tight=True),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=8,
            border=ft.Border.all(1, COLORS["border"]),
            bgcolor=COLORS["bg_elevated"],
            on_click=self._toggle_assign_mode,
            ink=True,
        )

        return ft.Column(
            [
                ft.Text("Ferramentas", size=FONTS["size_sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                self._assign_btn,
                ft.Text("Gerar numeração de lotes:", size=FONTS["size_xs"], color=COLORS["text_secondary"]),
                self._gen_mz_field,
                create_button("Gerar lotes", icon=ft.Icons.AUTO_FIX_HIGH, on_click=self._generate_codes, primary=False),
            ],
            spacing=6,
            tight=True,
        )

    def _toggle_assign_mode(self, e):
        self._assign_mode = not self._assign_mode
        if self._assign_mode:
            self._assign_btn_label.value = t("map.exit_assign")
            self._assign_btn.bgcolor = COLORS["accent_primary"]
            self._set_status("Modo atribuição: clique numa manzana no mapa.")
            self._set_detail(ft.Column([
                ft.Text("Clique em qualquer lote no mapa para atribuir clientes à manzana.", size=FONTS["size_sm"], color=COLORS["text_secondary"]),
            ], tight=True))
        else:
            self._assign_btn_label.value = t("map.assign_clients")
            self._assign_btn.bgcolor = COLORS["bg_elevated"]
            self._set_status("Modo normal.")
            self._set_detail(self._build_empty_panel())
        try:
            self._assign_btn.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers de UI
    # ------------------------------------------------------------------

    def _set_detail(self, panel: ft.Control):
        try:
            self._detail_panel.controls.clear()
            self._detail_panel.controls.append(panel)
            self._detail_panel.update()
        except Exception:
            pass

    def _place_pin(self, lat: float, lon: float):
        markers = [ftm.Marker(
            coordinates=ftm.MapLatitudeLongitude(lat, lon),
            content=ft.Icon(ft.Icons.LOCATION_PIN, color=COLORS["accent_error"], size=28),
            alignment=ft.Alignment(0, -1),
        )]
        self._refresh_map(self._current_polygons(), markers)

    def _save_code(self, feat_id: int, e):
        if not self._selected_code_field:
            return
        new_code = self._selected_code_field.value.strip()
        if not new_code:
            return
        try:
            api_client.put(f"/map/geojson/feature/{feat_id}/code", params={"code": new_code})
            for feature in self._geojson["features"]:
                if feature["properties"].get("FeatId1") == feat_id:
                    feature["properties"]["CODE"] = new_code
                    break
            self._refresh_map(self._make_polygons())
            self._set_status(f"CODE {new_code} salvo.")
        except APIError as err:
            self._set_status(friendly_error(err), error=True)

    def _generate_codes(self, e):
        manzana = (self._gen_mz_field.value or "").strip()
        if not manzana:
            self._set_status("Informe o número da manzana.", error=True)
            return
        try:
            result = api_client.post(f"/map/geojson/manzana/{manzana}/generate-codes")
            updated = result.get("updated", [])
            if not updated:
                self._set_status(f"Manzana {manzana}: nenhum lote sem CODE.")
            else:
                feat_map = {u["feat_id"]: u["code"] for u in updated}
                for feature in self._geojson["features"]:
                    fid = feature["properties"].get("FeatId1")
                    if fid in feat_map:
                        feature["properties"]["CODE"] = feat_map[fid]
                self._refresh_map(self._make_polygons())
                self._set_status(f"Manzana {manzana}: {len(updated)} lote(s) numerado(s).")
        except APIError as err:
            self._set_status(friendly_error(err), error=True)

    def _build_empty_panel(self) -> ft.Column:
        return ft.Column(
            [ft.Text("Clique num lote para ver detalhes", size=FONTS["size_sm"], color=COLORS["text_secondary"])],
            spacing=8, tight=True,
        )

    def _build_legend(self) -> ft.Column:
        items = [
            ("#66BB6A", t("map.legend.active")),
            ("#FFCA28", t("map.legend.pending")),
            ("#EF5350", t("map.legend.cuttable")),
            ("#FF7043", t("map.legend.incomplete")),
            ("#42A5F5", t("map.legend.own_well")),
            ("#9E9E9E", t("map.legend.empty_lot")),
            ("#546E7A", t("map.legend.inactive")),
        ]
        rows = [ft.Text("Legenda", size=FONTS["size_sm"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])]
        for color, label in items:
            rows.append(ft.Row([
                ft.Container(width=14, height=14, bgcolor=color, border_radius=3),
                ft.Text(label, size=FONTS["size_xs"], color=COLORS["text_secondary"]),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        return ft.Column(rows, spacing=4, tight=True)

    def _set_loading(self, loading: bool, msg: str = ""):
        try:
            if loading:
                self._overlay.show(msg)
            else:
                self._overlay.hide()
        except Exception:
            pass

    def _set_status(self, msg: str, error: bool = False):
        try:
            self._status_text.value = msg
            self._status_text.color = COLORS["accent_error"] if error else COLORS["text_secondary"]
            self._status_text.update()
        except Exception:
            pass


def _info_row(label: str, value: str) -> ft.Row:
    return ft.Row([
        ft.Text(label + ":", size=FONTS["size_xs"], color=COLORS["text_secondary"], width=80),
        ft.Text(value, size=FONTS["size_xs"], color=COLORS["text_primary"], expand=True),
    ], spacing=4)
