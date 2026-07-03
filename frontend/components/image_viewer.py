"""
WMApp Frontend - Image Viewer Component
Reusable image preview with optional GPS info.
"""

import webbrowser

import flet as ft
from i18n import t

from components.theme import COLORS, SPACING


class ImageViewer(ft.Container):
    """Reusable image viewer panel."""

    def __init__(
        self,
        image_url: str,
        title: str = "Imagem",
        gps_latitude: float | None = None,
        gps_longitude: float | None = None,
        width: int = 560,
        height: int = 360,
    ):
        rows: list[ft.Control] = [
            ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
            ft.Image(
                src=image_url,
                width=width,
                height=height,
                fit=ft.BoxFit.CONTAIN,
            ),
        ]

        if gps_latitude is not None and gps_longitude is not None:
            rows.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.LOCATION_ON, size=16, color=COLORS["accent_secondary"]),
                        ft.Text(
                            f"GPS: {gps_latitude:.6f}, {gps_longitude:.6f}",
                            size=12,
                            color=COLORS["text_secondary"],
                        ),
                        ft.IconButton(
                            icon=ft.Icons.MAP,
                            tooltip=t("viewer.open_maps"),
                            icon_color=COLORS["accent_secondary"],
                            on_click=lambda e: self._open_maps(gps_latitude, gps_longitude),
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        else:
            rows.append(ft.Text("GPS nao disponivel", size=12, color=COLORS["text_muted"]))

        super().__init__(
            content=ft.Column(rows, spacing=SPACING["sm"], tight=True),
            padding=SPACING["sm"],
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
        )

    @staticmethod
    def _open_maps(lat: float, lon: float):
        webbrowser.open(f"https://www.google.com/maps?q={lat},{lon}")
