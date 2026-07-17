"""
WMApp Frontend - Sidebar Component
Menu lateral com navegacao por modulos e controle por escopo.
"""
import flet as ft

from components.theme import COLORS, FONTS, RADIUS, SPACING
from i18n import t


class Sidebar(ft.Container):
    """Menu lateral de navegacao."""

    def __init__(
        self,
        on_navigate,
        current_route: str = "/clients",
        allowed_scopes: list[str] | None = None,
        is_superuser: bool = False,
        on_logout=None,
    ):
        super().__init__()
        self.on_navigate = on_navigate
        self.current_route = current_route
        self.allowed_scopes = allowed_scopes or []
        self.is_superuser = is_superuser
        self.on_logout = on_logout

        self.menu_items = [
            {"icon": ft.Icons.GROUP_OUTLINED, "label_key": "nav.clients", "route": "/clients", "scope": "clients"},
            {"icon": ft.Icons.WATER_DROP_OUTLINED, "label_key": "nav.readings", "route": "/readings", "scope": "readings"},
            {"icon": ft.Icons.RECEIPT_LONG_OUTLINED, "label_key": "nav.invoices", "route": "/invoices", "scope": "invoices"},
            {"icon": ft.Icons.INVENTORY_2_OUTLINED, "label_key": "nav.products", "route": "/products", "scope": "invoices"},
            {"icon": ft.Icons.POINT_OF_SALE_OUTLINED, "label_key": "nav.payments", "route": "/payments", "scope": "payments"},
            {"icon": ft.Icons.CONTENT_CUT, "label_key": "nav.cutoff", "route": "/cutoff", "scope": "cutoff"},
            {"icon": ft.Icons.ACCOUNT_BALANCE_OUTLINED, "label_key": "nav.finance", "route": "/finance", "scope": "finance"},
            {"icon": ft.Icons.VOLUNTEER_ACTIVISM_OUTLINED, "label_key": "nav.sponsors", "route": "/sponsors", "scope": ("sponsors", "finance")},
            {"icon": ft.Icons.MAP_OUTLINED, "label_key": "nav.map", "route": "/map", "scope": "clients"},
            {"icon": ft.Icons.SETTINGS_OUTLINED, "label_key": "nav.settings", "route": "/settings", "scope": "settings"},
        ]

        self._build()

    def _can_access(self, required_scope: str | tuple[str, ...] | list[str] | None) -> bool:
        if required_scope is None:
            return True
        if self.is_superuser:
            return True
        if "*" in self.allowed_scopes:
            return True
        if isinstance(required_scope, (tuple, list)):
            return any(scope in self.allowed_scopes for scope in required_scope)
        return required_scope in self.allowed_scopes

    def _build(self):

        menu_controls = []
        for item in self.menu_items:
            if self._can_access(item["scope"]):
                menu_controls.append(self._create_menu_item(item, item["route"] == self.current_route))

        footer_controls = [ft.Divider(height=1, color=COLORS["border"])]
        footer_controls.append(
            ft.Container(
                data={"route": "/profile", "is_active": self.current_route == "/profile"},
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.MANAGE_ACCOUNTS_OUTLINED, size=19,
                                color=COLORS["accent_secondary"] if self.current_route == "/profile" else COLORS["text_muted"]),
                        ft.Text(t("nav.profile"),
                                color=COLORS["text_primary"] if self.current_route == "/profile" else COLORS["text_secondary"],
                                weight=ft.FontWeight.W_600 if self.current_route == "/profile" else ft.FontWeight.NORMAL),
                    ],
                    spacing=8,
                ),
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                border_radius=RADIUS["md"],
                bgcolor=COLORS["nav_active"] if self.current_route == "/profile" else None,
                on_click=lambda e: self._handle_click("/profile"),
                on_hover=self._hover,
            )
        )
        footer_controls.append(
            ft.Container(
                data={"route": "/about", "is_active": self.current_route == "/about"},
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=18,
                                color=COLORS["accent_secondary"] if self.current_route == "/about" else COLORS["text_muted"]),
                        ft.Text(t("nav.about"),
                                color=COLORS["text_primary"] if self.current_route == "/about" else COLORS["text_secondary"],
                                weight=ft.FontWeight.W_600 if self.current_route == "/about" else ft.FontWeight.NORMAL),
                    ],
                    spacing=8,
                ),
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                border_radius=RADIUS["md"],
                bgcolor=COLORS["nav_active"] if self.current_route == "/about" else None,
                on_click=lambda e: self._handle_click("/about"),
                on_hover=self._hover,
            )
        )
        if self.on_logout is not None:
            footer_controls.append(
                ft.Container(
                    data={"is_active": False},
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.LOGOUT, size=18, color=COLORS["text_secondary"]),
                            ft.Text(t("nav.logout"), color=COLORS["text_secondary"]),
                        ],
                        spacing=8,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                    border_radius=RADIUS["md"],
                    on_click=lambda e: self.on_logout(),
                    on_hover=self._hover,
                )
            )

        self.content = ft.Column(
            [
                ft.Column(menu_controls, spacing=4, expand=True),
                *footer_controls,
            ],
            spacing=0,
        )

        self.width = 232
        self.bgcolor = COLORS["bg_secondary"]
        self.padding = ft.Padding.symmetric(horizontal=10, vertical=SPACING["md"])
        self.border = ft.Border.only(right=ft.BorderSide(1, COLORS["border_subtle"]))

    def _create_menu_item(self, item: dict, is_active: bool) -> ft.Container:
        return ft.Container(
            data={"route": item["route"], "is_active": is_active},
            content=ft.Row(
                [
                    ft.Icon(item["icon"], color=COLORS["accent_secondary"] if is_active else COLORS["text_muted"], size=20),
                    ft.Text(
                        t(item["label_key"]),
                        size=FONTS["size_base"],
                        color=COLORS["text_primary"] if is_active else COLORS["text_secondary"],
                        weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                    ),
                ],
                spacing=12,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=RADIUS["md"],
            bgcolor=COLORS["nav_active"] if is_active else None,
            on_click=lambda e, route=item["route"]: self._handle_click(route),
            on_hover=self._hover,
        )

    def _hover(self, e):
        is_active = bool((e.control.data or {}).get("is_active"))
        if e.data == "true":
            e.control.bgcolor = COLORS["bg_hover"]
        else:
            e.control.bgcolor = COLORS["nav_active"] if is_active else None
        e.control.update()

    def _handle_click(self, route: str):
        if self.on_navigate:
            self.on_navigate(route)

    def set_route(self, route: str):
        self.current_route = route
        self._build()
        self.update()
