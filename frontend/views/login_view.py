"""
WMApp Frontend - Login View
Tela de autenticação com suporte a must_change_password
"""
import re
import flet as ft
from datetime import datetime
from components.theme import (
    COLORS, FONTS, SPACING,
    create_text_field, create_button
)
from services.auth_service import auth_service
from services.api_client import APIError
from config.local_settings import get_org_slug
from i18n import t


def get_greeting() -> str:
    """Saudação conforme a hora, traduzida (es/pt)."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return t("login.greeting.morning")
    elif 12 <= hour < 18:
        return t("login.greeting.afternoon")
    else:
        return t("login.greeting.evening")


class LoginView(ft.Container):
    """Tela de login com fluxo de primeiro acesso."""
    
    def __init__(self, on_login_success):
        super().__init__()
        self.on_login_success_callback = on_login_success
        self._pending_result = None  # Guarda resultado do login para uso após troca de senha
        
        self.org_slug_field = ft.TextField(
            label="Organización (RUC)",
            value=get_org_slug(),
            on_submit=lambda e: self.username_field.focus(),
            hint_text="ej: 80012345-6",
            width=400,
            height=56,
            text_size=16,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            label_style=ft.TextStyle(color=COLORS["text_secondary"], size=14),
            text_style=ft.TextStyle(color=COLORS["text_primary"], size=16),
            cursor_color=COLORS["accent_primary"],
            border_radius=8,
        )

        self.username_field = ft.TextField(
            label=t("login.field.user"),
            on_submit=lambda e: self.password_field.focus(),
            autofocus=not bool(get_org_slug()),
            width=400,
            height=56,
            text_size=16,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            label_style=ft.TextStyle(color=COLORS["text_secondary"], size=14),
            text_style=ft.TextStyle(color=COLORS["text_primary"], size=16),
            cursor_color=COLORS["accent_primary"],
            border_radius=8,
        )

        self.password_field = ft.TextField(
            label=t("login.field.password"),
            password=True,
            can_reveal_password=True,
            on_submit=lambda e: self._do_login(e),
            width=400,
            height=56,
            text_size=16,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            label_style=ft.TextStyle(color=COLORS["text_secondary"], size=14),
            text_style=ft.TextStyle(color=COLORS["text_primary"], size=16),
            cursor_color=COLORS["accent_primary"],
            border_radius=8,
        )
        
        self.error_text = ft.Text("", size=13, color=COLORS["accent_error"], visible=False)
        
        self.loading = ft.Row(
            [
                ft.ProgressRing(width=20, height=20, stroke_width=3, color=COLORS["accent_primary"]),
                ft.Text(t("login.signing_in"), size=14, color=COLORS["text_secondary"]),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
            visible=False,
        )
        
        self.login_button = ft.Button(
            content=ft.Text(t("login.btn.enter"), size=16, weight=ft.FontWeight.W_500),
            on_click=self._do_login,
            width=400,
            height=48,
            style=ft.ButtonStyle(
                bgcolor=COLORS["accent_primary"],
                color=COLORS["text_primary"],
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        
        self._build()
    
    def _build(self):
        """Constrói o layout."""
        greeting = get_greeting()
        
        self.content = ft.Column(
            [
                ft.Image(src="saneo.png", width=220),
                ft.Container(height=24),
                ft.Text(f"{greeting}!", size=28, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                ft.Text(t("login.subtitle"), size=14, color=COLORS["text_secondary"]),
                ft.Container(height=32),
                self.org_slug_field,
                ft.Container(height=8),
                self.username_field,
                ft.Container(height=8),
                self.password_field,
                self.error_text,
                ft.Container(height=16),
                ft.Stack([self.login_button, self.loading]),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )
        self.bgcolor = COLORS["bg_primary"]
        self.expand = True
    
    def _do_login(self, e):
        """Valida e dispara o login fora da thread da UI."""
        # O slug é o RUC normalizado (sem hífen/espaços), igual ao gerado no painel.
        org_slug = re.sub(r"[^a-z0-9_]", "", (self.org_slug_field.value or "").strip().lower())
        username = self.username_field.value.strip() if self.username_field.value else ""
        password = self.password_field.value.strip() if self.password_field.value else ""

        if not org_slug:
            self._show_error(t("login.err.no_org"))
            self.org_slug_field.focus()
            return

        if not username or not password:
            self._show_error(t("login.err.no_credentials"))
            return

        self._hide_error()
        self._set_loading(True)

        # Roda a chamada de rede fora da thread da UI: assim o spinner realmente
        # aparece/anima e a janela não congela durante a requisição.
        if self.page:
            try:
                self.page.run_thread(self._login_worker, org_slug, username, password)
                return
            except Exception:
                pass
        self._login_worker(org_slug, username, password)

    def _login_worker(self, org_slug: str, username: str, password: str):
        try:
            result = auth_service.login(username, password, org_slug=org_slug)

            # Primeiro acesso: precisa trocar senha.
            if result.get("must_change_password"):
                self._pending_result = result
                self._set_loading(False)
                self._show_change_password_modal(username, password)
                return

            user = auth_service.get_current_user()
            self._set_loading(False)
            self.on_login_success_callback(user)

        except APIError as err:
            self._set_loading(False)
            self._show_error(self._friendly_error(err))
        except Exception:
            self._set_loading(False)
            self._show_error(t("login.err.generic"))

    @staticmethod
    def _friendly_error(err: APIError) -> str:
        """Mapeia o erro técnico para uma mensagem amigável (sem URL/detalhes)."""
        code = getattr(err, "status_code", None)
        if code in (0, None):
            return t("login.err.no_connection")
        if code == 401:
            return t("login.err.invalid_credentials")
        if code == 403:
            return t("login.err.forbidden")
        return t("login.err.generic")
    
    def _show_change_password_modal(self, username: str, current_password: str):
        """Mostra modal para trocar senha no primeiro acesso."""
        new_pwd_field = ft.TextField(
            label=t("login.cp.new"),
            password=True,
            can_reveal_password=True,
            width=300,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            autofocus=True,
        )
        
        confirm_pwd_field = ft.TextField(
            label=t("login.cp.confirm"),
            password=True,
            can_reveal_password=True,
            width=300,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )
        
        modal_error = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
        
        def do_change(e):
            new_pwd = new_pwd_field.value or ""
            confirm_pwd = confirm_pwd_field.value or ""
            
            if len(new_pwd) < 6:
                modal_error.value = t("login.cp.err_min")
                modal_error.visible = True
                modal_error.update()
                return
            
            if new_pwd != confirm_pwd:
                modal_error.value = t("login.cp.err_mismatch")
                modal_error.visible = True
                modal_error.update()
                return
            
            if new_pwd == current_password:
                modal_error.value = t("login.cp.err_same")
                modal_error.visible = True
                modal_error.update()
                return
            
            try:
                auth_service.change_password(current_password, new_pwd)
                dialog.open = False
                self.page.update()
                
                # Faz novo login com nova senha
                org_slug = self.org_slug_field.value.strip() if self.org_slug_field.value else ""
                auth_service.login(username, new_pwd, org_slug=org_slug)
                user = auth_service.get_current_user()
                self.on_login_success_callback(user)
                
            except APIError as err:
                modal_error.value = str(err.detail)
                modal_error.visible = True
                modal_error.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text(t("login.cp.title")),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(t("login.cp.body"), 
                           size=13, color=COLORS["text_secondary"]),
                    ft.Container(height=12),
                    new_pwd_field,
                    ft.Container(height=8),
                    confirm_pwd_field,
                    modal_error,
                ], spacing=0, tight=True),
                width=320,
            ),
            actions=[
                ft.Button(content=ft.Text(t("login.cp.submit")), on_click=do_change),
            ],
        )
        
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()
    
    def _show_error(self, message: str):
        self.error_text.value = message
        self.error_text.visible = True
        self.error_text.update()
    
    def _hide_error(self):
        self.error_text.visible = False
        self.error_text.update()
    
    def _set_loading(self, loading: bool):
        self.loading.visible = loading
        self.login_button.visible = not loading
        self.login_button.update()
        self.loading.update()
