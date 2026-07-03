"""
WMApp Frontend - Tema Corporativo/Industrial
Definições de cores, fontes e estilos para toda a aplicação
"""
import flet as ft

# === CORES PRINCIPAIS ===
COLORS = {
    # Background
    "bg_primary": "#1a1a2e",      # Azul escuro principal
    "bg_secondary": "#16213e",     # Azul escuro secundário
    "bg_surface": "#0f3460",       # Superfície cards/panels
    "bg_elevated": "#1f4068",      # Elementos elevados
    
    # Accent
    "accent_primary": "#e94560",   # Vermelho/Rosa vibrante
    "accent_secondary": "#0ea5e9", # Azul claro
    "accent_success": "#10b981",   # Verde
    "accent_warning": "#f59e0b",   # Amarelo/Laranja
    "accent_error": "#ef4444",     # Vermelho erro
    
    # Text
    "text_primary": "#f8fafc",     # Branco principal
    "text_secondary": "#94a3b8",   # Cinza claro
    "text_muted": "#64748b",       # Cinza médio
    
    # Borders
    "border": "#334155",
    "border_focus": "#0ea5e9",
    
    # Status
    "status_active": "#10b981",
    "status_inactive": "#6b7280",
    "status_cut": "#ef4444",
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
}

# === COMPONENTES ESTILIZADOS ===

def create_text_field(
    label: str,
    value: str = "",
    password: bool = False,
    on_change=None,
    on_submit=None,
    width: int = None,
    autofocus: bool = False,
    hint_text: str = None,
) -> ft.TextField:
    """Cria campo de texto estilizado."""
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
        hint_style=ft.TextStyle(color=COLORS["text_muted"]),
        border_color=COLORS["border"],
        focused_border_color=COLORS["border_focus"],
        label_style=ft.TextStyle(color=COLORS["text_secondary"]),
        text_style=ft.TextStyle(color=COLORS["text_primary"]),
        cursor_color=COLORS["accent_primary"],
        border_radius=8,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=12),
    )


def create_button(
    text: str,
    on_click=None,
    icon: str = None,
    primary: bool = True,
    width: int = None,
    disabled: bool = False,
) -> ft.Button:
    """Cria botão estilizado (Flet 0.80+)."""
    # Build content with optional icon
    if icon:
        content = ft.Row(
            [ft.Icon(icon, size=18), ft.Text(text)],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        )
    else:
        content = ft.Text(text)
    
    return ft.Button(
        content=content,
        on_click=on_click,
        width=width,
        disabled=disabled,
        style=ft.ButtonStyle(
            bgcolor=COLORS["accent_primary"] if primary else COLORS["bg_surface"],
            color=COLORS["text_primary"],
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.padding.symmetric(horizontal=24, vertical=12),
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
        hover_color=COLORS["bg_elevated"],
    )


def create_card(content: ft.Control, padding: int = 16) -> ft.Container:
    """Cria card container."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=COLORS["bg_surface"],
        border_radius=12,
        border=ft.Border.all(1, COLORS["border"]),
    )


def create_header(text: str, size: int = None) -> ft.Text:
    """Cria texto de cabeçalho."""
    return ft.Text(
        text,
        size=size or FONTS["size_xl"],
        weight=ft.FontWeight.BOLD,
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
    return ft.Container(
        content=ft.Text(text, size=FONTS["size_xs"], color=COLORS["text_primary"]),
        bgcolor=color or COLORS["accent_secondary"],
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
        border_radius=12,
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
