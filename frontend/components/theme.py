"""
WMApp Frontend - Tema Corporativo/Industrial
Definições de cores, fontes e estilos para toda a aplicação
"""
from typing import Any, Optional

import flet as ft

# === CORES PRINCIPAIS ===
COLORS = {
    # Paleta original da marca: azul profundo com destaque vermelho/rosa.
    "bg_primary": "#1A1A2E",
    "bg_secondary": "#16213E",
    "bg_surface": "#0F3460",
    "bg_elevated": "#1F4068",
    "bg_input": "#16213E",
    "bg_input_focus": "#1F4068",
    "bg_hover": "#1F4068",
    "nav_active": "#0F3460",
    "table_row": "#16213E",
    "table_row_alt": "#192746",
    
    # Accent
    "accent_primary": "#E94560",
    "accent_primary_hover": "#D63853",
    "accent_secondary": "#0EA5E9",
    "accent_success": "#10B981",
    "accent_warning": "#F59E0B",
    "accent_error": "#EF4444",
    
    # Text
    "text_primary": "#F8FAFC",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
    
    # Borders
    "border": "#334155",
    "border_subtle": "#27364E",
    "border_focus": "#0EA5E9",
    
    # Status
    "status_active": "#10B981",
    "status_inactive": "#6B7280",
    "status_cut": "#EF4444",
}

# === TIPOGRAFIA ===
FONTS = {
    "family": "Segoe UI",
    "size_xs": 11,
    "size_sm": 12,
    "size_base": 14,
    "size_lg": 16,
    "size_xl": 20,
    "size_2xl": 24,
    "size_3xl": 30,
}

# === ESPAÇAMENTO ===
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 16,
    "lg": 24,
    "xl": 32,
    "2xl": 40,
}

RADIUS = {
    "sm": 8,
    "md": 10,
    "lg": 14,
    "xl": 18,
    "pill": 999,
}

# === COMPONENTES ESTILIZADOS ===

def create_app_theme() -> ft.Theme:
    """Tema Material 3 compartilhado por toda a aplicação."""
    return ft.Theme(
        use_material3=True,
        color_scheme=ft.ColorScheme(
            primary=COLORS["accent_primary"],
            secondary=COLORS["accent_secondary"],
            surface=COLORS["bg_surface"],
            on_surface=COLORS["text_primary"],
            on_surface_variant=COLORS["text_secondary"],
            error=COLORS["accent_error"],
            outline=COLORS["border"],
            outline_variant=COLORS["border_subtle"],
        ),
        font_family=FONTS["family"],
        scaffold_bgcolor=COLORS["bg_primary"],
        canvas_color=COLORS["bg_primary"],
        divider_color=COLORS["border_subtle"],
        hover_color=ft.Colors.with_opacity(0.10, COLORS["accent_secondary"]),
        focus_color=ft.Colors.with_opacity(0.16, COLORS["accent_secondary"]),
        filled_button_theme=ft.FilledButtonTheme(
            style=ft.ButtonStyle(
                bgcolor=COLORS["accent_primary"],
                color=COLORS["text_primary"],
                shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
                padding=ft.Padding.symmetric(horizontal=18, vertical=11),
                elevation=0,
                overlay_color=ft.Colors.with_opacity(0.12, COLORS["text_primary"]),
            )
        ),
        outlined_button_theme=ft.OutlinedButtonTheme(
            style=ft.ButtonStyle(
                color=COLORS["text_secondary"],
                side=ft.BorderSide(1, COLORS["border"]),
                shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
                padding=ft.Padding.symmetric(horizontal=18, vertical=11),
                elevation=0,
                overlay_color=ft.Colors.with_opacity(0.10, COLORS["accent_secondary"]),
            )
        ),
        text_button_theme=ft.TextButtonTheme(
            style=ft.ButtonStyle(
                color=COLORS["text_secondary"],
                shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                overlay_color=ft.Colors.with_opacity(0.10, COLORS["accent_secondary"]),
            )
        ),
        icon_button_theme=ft.IconButtonTheme(
            style=ft.ButtonStyle(
                icon_color=COLORS["text_secondary"],
                icon_size=18,
                shape=ft.RoundedRectangleBorder(radius=RADIUS["sm"]),
                padding=8,
                overlay_color=ft.Colors.with_opacity(0.12, COLORS["accent_secondary"]),
            )
        ),
        card_theme=ft.CardTheme(
            color=COLORS["bg_surface"],
            elevation=0,
            shadow_color="transparent",
            shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
        ),
        divider_theme=ft.DividerTheme(color=COLORS["border_subtle"], thickness=1, space=1),
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color=ft.Colors.with_opacity(0.50, COLORS["text_muted"]),
            track_color="transparent",
            thickness=6,
            radius=RADIUS["pill"],
        ),
        snackbar_theme=ft.SnackBarTheme(
            bgcolor=COLORS["bg_elevated"],
            content_text_style=ft.TextStyle(color=COLORS["text_primary"], size=FONTS["size_sm"]),
            shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
            elevation=8,
        ),
        dialog_theme=ft.DialogTheme(
            bgcolor=COLORS["bg_secondary"],
            barrier_color=ft.Colors.with_opacity(0.74, "#020617"),
            elevation=12,
            shadow_color=ft.Colors.with_opacity(0.48, "#000000"),
            shape=ft.RoundedRectangleBorder(radius=RADIUS["xl"]),
            title_text_style=ft.TextStyle(
                color=COLORS["text_primary"],
                size=FONTS["size_xl"],
                weight=ft.FontWeight.W_600,
            ),
            content_text_style=ft.TextStyle(
                color=COLORS["text_secondary"],
                size=FONTS["size_base"],
            ),
            actions_padding=ft.Padding.only(left=24, top=8, right=24, bottom=20),
            inset_padding=ft.Padding.symmetric(horizontal=24, vertical=24),
        ),
    )

def create_text_field(
    label: str,
    value: str = "",
    password: bool = False,
    on_change=None,
    on_submit=None,
    width: int = None,
    autofocus: bool = False,
    hint_text: str = None,
    helper: str | ft.Control | None = None,
    error: str | ft.Control | None = None,
    prefix: str | ft.Control | None = None,
    suffix: str | ft.Control | None = None,
    prefix_icon: Any = None,
    suffix_icon: Any = None,
    keyboard_type: Optional[ft.KeyboardType] = None,
    input_filter: Optional[ft.InputFilter] = None,
    multiline: bool = False,
    min_lines: Optional[int] = None,
    max_lines: Optional[int] = None,
    max_length: Optional[int] = None,
    read_only: bool = False,
    capitalization: Optional[ft.TextCapitalization] = None,
    text_size: Optional[int] = None,
    dense: bool = True,
    col: Any = None,
) -> ft.TextField:
    """Cria um campo Material consistente, com suporte a semântica e erro inline."""
    kwargs: dict[str, Any] = {}
    if col is not None:
        kwargs["col"] = col

    if multiline:
        min_lines = min_lines or 2
        max_lines = max_lines or 4

    return ft.TextField(
        label=label,
        value=value,
        password=password,
        can_reveal_password=password,
        on_change=on_change,
        on_submit=on_submit,
        width=width,
        autofocus=autofocus,
        hint_text=hint_text,
        helper=helper,
        error=error,
        prefix=prefix,
        suffix=suffix,
        prefix_icon=prefix_icon,
        suffix_icon=suffix_icon,
        keyboard_type=keyboard_type or ft.KeyboardType.TEXT,
        input_filter=input_filter,
        multiline=multiline,
        min_lines=min_lines,
        max_lines=max_lines,
        max_length=max_length,
        read_only=read_only,
        capitalization=capitalization,
        dense=dense,
        text_size=text_size or FONTS["size_base"],
        filled=True,
        fill_color=COLORS["bg_input"],
        focused_bgcolor=COLORS["bg_input_focus"],
        hover_color=ft.Colors.with_opacity(0.08, COLORS["accent_secondary"]),
        hint_style=ft.TextStyle(color=COLORS["text_muted"]),
        helper_style=ft.TextStyle(color=COLORS["text_muted"], size=FONTS["size_xs"]),
        error_style=ft.TextStyle(color=COLORS["accent_error"], size=FONTS["size_xs"]),
        border_color=COLORS["border"],
        border_width=1,
        focused_border_color=COLORS["border_focus"],
        focused_border_width=2,
        label_style=ft.TextStyle(color=COLORS["text_secondary"]),
        text_style=ft.TextStyle(color=COLORS["text_primary"]),
        cursor_color=COLORS["accent_secondary"],
        cursor_error_color=COLORS["accent_error"],
        selection_color=ft.Colors.with_opacity(0.32, COLORS["accent_secondary"]),
        border_radius=RADIUS["md"],
        content_padding=ft.Padding.symmetric(horizontal=14, vertical=12),
        enable_ime_personalized_learning=not password,
        **kwargs,
    )


def create_integer_field(label: str, **kwargs) -> ft.TextField:
    """Campo para números inteiros."""
    kwargs.setdefault("keyboard_type", ft.KeyboardType.NUMBER)
    kwargs.setdefault("input_filter", ft.NumbersOnlyInputFilter())
    return create_text_field(label, **kwargs)


def create_money_field(label: str, **kwargs) -> ft.TextField:
    """Campo monetário em guaranis."""
    kwargs.setdefault("keyboard_type", ft.KeyboardType.NUMBER)
    kwargs.setdefault(
        "input_filter",
        ft.InputFilter(regex_string=r"^[0-9.,]*$", allow=True, replacement_string=""),
    )
    kwargs.setdefault("prefix", "Gs. ")
    return create_text_field(label, **kwargs)


def create_percent_field(label: str, **kwargs) -> ft.TextField:
    """Campo percentual inteiro entre 0 e 100; o limite é validado no formulário."""
    kwargs.setdefault("keyboard_type", ft.KeyboardType.NUMBER)
    kwargs.setdefault("input_filter", ft.NumbersOnlyInputFilter())
    kwargs.setdefault("suffix", "%")
    return create_text_field(label, **kwargs)


def create_phone_field(label: str, **kwargs) -> ft.TextField:
    """Campo de telefone com teclado e filtro apropriados."""
    kwargs.setdefault("keyboard_type", ft.KeyboardType.PHONE)
    kwargs.setdefault(
        "input_filter",
        ft.InputFilter(
            regex_string=r"^[0-9+() -]*$",
            allow=True,
            replacement_string="",
        ),
    )
    kwargs.setdefault("prefix_icon", ft.Icons.PHONE_OUTLINED)
    return create_text_field(label, **kwargs)


def create_button(
    text: str,
    on_click=None,
    icon: str = None,
    primary: bool = True,
    width: int = None,
    disabled: bool = False,
) -> ft.Control:
    """Cria botão estilizado (Flet 0.80+)."""
    # Build content with optional icon
    if icon:
        content = ft.Row(
            [ft.Icon(icon, size=18), ft.Text(text)],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )
    else:
        content = ft.Text(text)
    
    button_cls = ft.FilledButton if primary else ft.OutlinedButton
    return button_cls(
        content=content,
        on_click=on_click,
        width=width,
        disabled=disabled,
        style=ft.ButtonStyle(
            bgcolor=COLORS["accent_primary"] if primary else "transparent",
            color=COLORS["text_primary"] if primary else COLORS["text_secondary"],
            side=None if primary else ft.BorderSide(1, COLORS["border"]),
            shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]),
            padding=ft.Padding.symmetric(horizontal=18, vertical=11),
            elevation=0,
            overlay_color=ft.Colors.with_opacity(
                0.12,
                COLORS["text_primary"] if primary else COLORS["accent_secondary"],
            ),
        ),
    )


def create_icon_button(
    icon: str,
    on_click=None,
    tooltip: str = None,
    color: str = None,
) -> ft.IconButton:
    """Cria botão de ícone."""
    return ft.IconButton(
        icon=icon,
        on_click=on_click,
        tooltip=tooltip,
        icon_color=color or COLORS["text_secondary"],
        icon_size=18,
        style=ft.ButtonStyle(
            padding=8,
            shape=ft.RoundedRectangleBorder(radius=RADIUS["sm"]),
            overlay_color=ft.Colors.with_opacity(0.14, color or COLORS["accent_secondary"]),
        ),
    )


def create_card(content: ft.Control, padding: int = 16) -> ft.Container:
    """Cria card container."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=COLORS["bg_surface"],
        border_radius=RADIUS["lg"],
        border=ft.Border.all(1, COLORS["border_subtle"]),
    )


def create_header(text: str, size: int = None) -> ft.Text:
    """Cria texto de cabeçalho."""
    return ft.Text(
        text,
        size=size or FONTS["size_xl"],
        weight=ft.FontWeight.W_700,
        color=COLORS["text_primary"],
    )


def create_label(text: str, muted: bool = False) -> ft.Text:
    """Cria texto de label."""
    return ft.Text(
        text,
        size=FONTS["size_sm"],
        color=COLORS["text_muted"] if muted else COLORS["text_secondary"],
    )


def create_badge(text: str, color: str = None) -> ft.Container:
    """Cria badge/chip."""
    badge_color = color or COLORS["accent_secondary"]
    return ft.Container(
        content=ft.Text(
            text,
            size=FONTS["size_xs"],
            color=badge_color,
            weight=ft.FontWeight.W_600,
            no_wrap=True,
        ),
        bgcolor=ft.Colors.with_opacity(0.16, badge_color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.28, badge_color)),
        padding=ft.Padding.symmetric(horizontal=9, vertical=3),
        border_radius=RADIUS["pill"],
    )


def get_status_color(status: str) -> str:
    """Retorna cor baseada no status."""
    status_map = {
        "ATIVO": COLORS["status_active"],
        "INATIVO": COLORS["status_inactive"],
        "CORTADO": COLORS["status_cut"],
        "PENDENTE": COLORS["accent_warning"],
        "PAGADA": COLORS["accent_success"],
        "PARCIAL": COLORS["accent_secondary"],
        "ANULADA": COLORS["text_muted"],
    }
    return status_map.get(status, COLORS["text_secondary"])
