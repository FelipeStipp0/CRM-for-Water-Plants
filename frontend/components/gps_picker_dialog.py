"""
WMApp Frontend - GPS Picker Dialog
Modal reutilizável para seleção visual de coordenadas via mapa.
"""
from typing import Callable, Optional

import flet as ft
from i18n import t

from components.map_picker import MapPicker
from components.theme import COLORS


def open_gps_picker_dialog(
    page: ft.Page,
    initial_lat: Optional[float] = None,
    initial_lon: Optional[float] = None,
    on_confirm: Optional[Callable[[float, float], None]] = None,
    title: str = "Selecionar localização no mapa",
):
    """Abre modal com mapa Mapbox para seleção de coordenadas GPS.

    Args:
        page: instância da página Flet
        initial_lat/lon: coordenadas iniciais (posiciona pin e centraliza)
        on_confirm: callback chamado com (lat, lon) ao confirmar
        title: título do modal
    """
    picker = MapPicker(
        initial_lat=initial_lat,
        initial_lon=initial_lon,
        width=660,
        height=440,
    )

    hint = ft.Text(
        t("gpspicker.hint"),
        size=12,
        color=COLORS["text_muted"],
        italic=True,
    )

    def confirm(e):
        lat = picker.selected_lat
        lon = picker.selected_lon
        if lat is None or lon is None:
            return
        page.pop_dialog()
        if on_confirm:
            on_confirm(lat, lon)

    def cancel(e):
        page.pop_dialog()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title or t("gpspicker.title")),
        content=ft.Container(
            width=680,
            content=ft.Column(
                [hint, picker],
                spacing=8,
                tight=True,
            ),
        ),
        actions=[
            ft.TextButton(content=ft.Text(t("common.cancel")), on_click=cancel),
            ft.FilledButton(
                content=ft.Text(t("gpspicker.confirm")),
                on_click=confirm,
                style=ft.ButtonStyle(
                    bgcolor=COLORS["accent_primary"],
                    color=COLORS["text_primary"],
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        scrollable=True,
    )

    page.show_dialog(dialog)
