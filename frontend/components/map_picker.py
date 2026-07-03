"""
WMApp Frontend - Map Picker
Componente de seleção visual de coordenadas GPS via Mapbox + flet-map.
Exibe os polígonos GeoJSON das manzanas por cima dos tiles.
"""
import threading
from typing import Callable, Optional

import flet as ft
import flet_map as ftm

from components.theme import COLORS, FONTS
from config.local_settings import get_mapbox_tile_url
from services.api_client import api as api_client


def _hex_opacity(hex_color: str, opacity: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(opacity * 255)
    return f"#{a:02X}{r:02X}{g:02X}{b:02X}"


class MapPicker(ft.Column):
    """Mapa interativo para seleção de coordenadas GPS com overlay GeoJSON."""

    def __init__(
        self,
        initial_lat: Optional[float] = None,
        initial_lon: Optional[float] = None,
        on_select: Optional[Callable[[float, float], None]] = None,
        width: int = 640,
        height: int = 420,
    ):
        super().__init__(spacing=8, tight=True)

        self._lat = initial_lat
        self._lon = initial_lon
        self._has_initial = initial_lat is not None and initial_lon is not None
        self._on_select = on_select
        self._has_pin = self._has_initial

        self._tile_url = get_mapbox_tile_url()

        coord_val = self._fmt(self._lat, self._lon) if self._has_initial else "Clique no mapa para selecionar"
        self._coord_text = ft.Text(
            coord_val,
            size=FONTS["size_sm"],
            color=COLORS["text_secondary"],
            font_family="monospace",
        )

        # Centro e pin iniciais — serão ajustados pelo bounds se não tiver coordenada
        init_center_lat = self._lat if self._has_initial else 0.0
        init_center_lon = self._lon if self._has_initial else 0.0
        init_markers = [self._make_pin(self._lat, self._lon)] if self._has_initial else []

        self._map = ftm.Map(
            width=width,
            height=height,
            initial_center=ftm.MapLatitudeLongitude(init_center_lat, init_center_lon),
            initial_zoom=15.0 if self._has_initial else 5.0,
            bgcolor="#0D1B2A",
            interaction_configuration=ftm.InteractionConfiguration(
                flags=ftm.InteractionFlag.ALL,
            ),
            on_tap=self._on_tap,
            layers=self._build_layers([], init_markers),
        )

        self.controls = [
            ft.Container(
                content=self._map,
                border=ft.Border.all(1, COLORS["border"]),
                border_radius=8,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ),
            ft.Row(
                [
                    ft.Icon(ft.Icons.LOCATION_ON, size=16, color=COLORS["accent_secondary"]),
                    self._coord_text,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ]

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def _build_layers(self, polygons: list, markers: list) -> list:
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

    def _refresh_layers(self, polygons: list, markers: list):
        self._map.layers = self._build_layers(polygons, markers)
        try:
            self._map.update()
        except Exception:
            pass

    def _current_polygons(self) -> list:
        for layer in self._map.layers:
            if isinstance(layer, ftm.PolygonLayer):
                return layer.polygons
        return []

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def did_mount(self):
        threading.Thread(target=self._load_geojson, daemon=True).start()

    def _load_geojson(self):
        try:
            bounds = api_client.get("/map/bounds")
            geojson = api_client.get("/map/geojson")

            # Tiles direto do Mapbox (CDN), igual ao mapa principal.
            try:
                cfg = api_client.get("/map/tile-config")
                if cfg.get("url_template"):
                    self._tile_url = cfg["url_template"]
            except Exception:
                pass

            # Destino da câmera: a coordenada já existente ou o centro da região.
            if self._has_initial:
                dest = ftm.MapLatitudeLongitude(self._lat, self._lon)
            else:
                dest = ftm.MapLatitudeLongitude(bounds["center_lat"], bounds["center_lon"])

            polygons = []
            for feature in geojson.get("features", []):
                cad_ok = feature["properties"].get("CAD_OK") or 0
                color = "#4CAF50" if cad_ok == 1 else "#9E9E9E"
                for polygon in feature["geometry"]["coordinates"]:
                    points = [ftm.MapLatitudeLongitude(pt[1], pt[0]) for pt in polygon[0]]
                    polygons.append(
                        ftm.PolygonMarker(
                            coordinates=points,
                            color=_hex_opacity(color, 0.20),
                            border_color=_hex_opacity(color, 0.65),
                            border_stroke_width=1.0,
                        )
                    )
            current_markers = [self._make_pin(self._lat, self._lon)] if self._has_pin else []
            self._refresh_layers(polygons, current_markers)

            # Move a câmera de fato para a região (initial_* não reposiciona um
            # mapa já montado no flet_map 0.84). move_to é async -> run_task.
            try:
                if self.page:
                    async def _go():
                        await self._map.move_to(dest, zoom=16)
                    self.page.run_task(_go)
            except Exception:
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def selected_lat(self) -> Optional[float]:
        return self._lat if self._has_pin else None

    @property
    def selected_lon(self) -> Optional[float]:
        return self._lon if self._has_pin else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fmt(self, lat: Optional[float], lon: Optional[float]) -> str:
        if lat is None or lon is None:
            return "—"
        return f"{lat:.6f}, {lon:.6f}"

    def _make_pin(self, lat: float, lon: float) -> ftm.Marker:
        return ftm.Marker(
            coordinates=ftm.MapLatitudeLongitude(lat, lon),
            content=ft.Icon(ft.Icons.LOCATION_PIN, color=COLORS["accent_error"], size=32),
            alignment=ft.Alignment(0, -1),
        )

    def _on_tap(self, e: ftm.MapTapEvent):
        lat = e.coordinates.latitude
        lon = e.coordinates.longitude
        self._lat = lat
        self._lon = lon
        self._has_pin = True

        self._coord_text.value = self._fmt(lat, lon)
        try:
            self._coord_text.update()
        except Exception:
            pass

        polygons = self._current_polygons()
        self._refresh_layers(polygons, [self._make_pin(lat, lon)])

        if self._on_select:
            self._on_select(lat, lon)
