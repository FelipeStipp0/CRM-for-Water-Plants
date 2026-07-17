"""
WMApp Frontend - Profile View
Tela de perfil do usuario autenticado.
"""
import flet as ft

from components.loading_overlay import LoadingOverlay
from components.theme import COLORS, FONTS, SPACING, create_button, create_header, create_text_field
from services.api_client import APIError
from utils.errors import friendly_error
from services.auth_service import auth_service
from i18n import t


class ProfileView(ft.Container):
    """Tela de perfil: dados pessoais, avatar e troca de senha."""

    def __init__(self, show_snackbar, current_user: dict | None = None, on_user_update=None):
        super().__init__()
        self.show_snackbar = show_snackbar
        self.current_user = current_user or {}
        self.on_user_update = on_user_update  # callback para atualizar sidebar/header

        self._avatar_picker = ft.FilePicker()
        self._build()
        self.on_visible = self._on_visible

    def trigger_initial_load(self):
        """Chamado pela navegação (em thread) para popular o perfil ao abrir."""
        if self.page and self._avatar_picker not in self.page.services:
            self.page.services.append(self._avatar_picker)
        self._load_profile()

    def _on_visible(self, e):
        if self.page and self._avatar_picker not in self.page.services:
            self.page.services.append(self._avatar_picker)
        if self.page:
            try:
                self.page.run_thread(self._load_profile)
                return
            except Exception:
                pass
        self._load_profile()

    def _safe_update(self, control):
        try:
            control.update()
        except Exception:
            try:
                if self.page:
                    self.page.update()
            except Exception:
                pass

    def _load_profile(self):
        try:
            user = auth_service.get_current_user()
            self.current_user = user
            self._populate(user)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            print(f"[ProfileView] load_error err={err}")

    def _populate(self, user: dict):
        self._full_name_field.value = user.get("full_name") or ""
        self._email_field.value = user.get("email") or ""
        self._phone_field.value = user.get("phone") or ""
        self._position_field.value = user.get("position") or ""
        self._language_dd.value = user.get("language") or "es"

        b64 = user.get("avatar_base64") or ""
        mime = user.get("avatar_mime") or "image/png"
        if b64:
            self._avatar_img.src = f"data:{mime};base64,{b64}"
            self._avatar_img.visible = True
            self._avatar_placeholder.visible = False
        else:
            self._avatar_img.src = ""
            self._avatar_img.visible = False
            self._avatar_placeholder.visible = True

        username = user.get("username", "")
        full_name = (user.get("full_name") or "").strip()
        self._name_text.value = full_name or username or "—"

        role_label = t("profile.role.master") if user.get("role") == "master" else t("profile.role.operator")
        self._role_text.value = role_label
        self._role_chip.visible = bool(role_label)
        self._username_text.value = f"@{username}" if username else ""

        # self.update() rodando de worker thread (trigger_initial_load via
        # page.run_thread) as vezes nao propaga pra cada filho individual no
        # Flet 0.84 — campos ficam com o valor antigo em tela. Update por
        # filho garante que cada TextField/Image vira pintado, e o page.update
        # finaliza a propagacao para qualquer container intermediario.
        for ctrl in (
            self._full_name_field,
            self._email_field,
            self._phone_field,
            self._position_field,
            self._language_dd,
            self._avatar_img,
            self._avatar_placeholder,
            self._name_text,
            self._role_text,
            self._role_chip,
            self._username_text,
        ):
            try:
                ctrl.update()
            except Exception:
                pass
        try:
            if self.page:
                self.page.update()
        except Exception:
            pass

    def _build(self):
        # --- Avatar ---
        self._avatar_img = ft.Image(
            src="",
            width=96,
            height=96,
            fit=ft.BoxFit.COVER,
            visible=False,
            border_radius=ft.BorderRadius.all(48),
        )
        self._avatar_placeholder = ft.Container(
            width=96,
            height=96,
            bgcolor=COLORS["bg_elevated"],
            border_radius=ft.BorderRadius.all(48),
            content=ft.Icon(ft.Icons.PERSON, size=48, color=COLORS["text_muted"]),
            alignment=ft.Alignment.CENTER,
            visible=True,
        )
        avatar_stack = ft.Stack(
            [self._avatar_placeholder, self._avatar_img],
            width=96,
            height=96,
        )

        self._name_text = ft.Text(
            "",
            size=18,
            weight=ft.FontWeight.BOLD,
            color=COLORS["text_primary"],
        )
        self._role_text = ft.Text(
            "",
            size=11,
            color=COLORS["text_primary"],
        )
        self._username_text = ft.Text(
            "",
            size=13,
            color=COLORS["text_secondary"],
        )
        # Chip de cargo — oculto enquanto não houver texto (evita um retângulo
        # vermelho vazio antes de os dados carregarem).
        self._role_chip = ft.Container(
            content=self._role_text,
            bgcolor=COLORS["accent_primary"],
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            visible=False,
        )

        avatar_section = ft.Container(
            content=ft.Row(
                [
                    avatar_stack,
                    ft.Column(
                        [
                            self._name_text,
                            self._username_text,
                            self._role_chip,
                            ft.Row(
                                [
                                    create_button(
                                        t("profile.change_photo"),
                                        icon=ft.Icons.UPLOAD_FILE,
                                        on_click=self._pick_avatar,
                                        primary=False,
                                    ),
                                    create_button(
                                        t("profile.remove_photo"),
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        on_click=self._remove_avatar,
                                        primary=False,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                t("profile.photo_hint"),
                                size=11,
                                color=COLORS["text_muted"],
                            ),
                        ],
                        spacing=6,
                    ),
                ],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
            bgcolor=COLORS["bg_surface"],
            border_radius=8,
            border=ft.Border.all(1, COLORS["border"]),
        )

        # --- Datos personales (campos sem largura fixa = preenchem a coluna) ---
        self._full_name_field = create_text_field(t("profile.field.full_name"))
        self._email_field = create_text_field(t("profile.field.email"))
        self._phone_field = create_text_field(t("profile.field.phone"))
        self._position_field = create_text_field(t("profile.field.position"))
        self._language_dd = ft.Dropdown(
            label=t("profile.field.language"),
            value="es",
            expand=True,
            options=[
                ft.dropdown.Option("es", t("profile.lang.es")),
                ft.dropdown.Option("pt", t("profile.lang.pt")),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )

        datos_section = self._section(
            t("profile.section.personal"),
            ft.Icons.PERSON_OUTLINE,
            [
                ft.ResponsiveRow(
                    [
                        ft.Container(self._full_name_field, col={"sm": 12, "md": 6}),
                        ft.Container(self._email_field, col={"sm": 12, "md": 6}),
                        ft.Container(self._phone_field, col={"sm": 12, "md": 4}),
                        ft.Container(self._position_field, col={"sm": 12, "md": 4}),
                        ft.Container(self._language_dd, col={"sm": 12, "md": 4}),
                    ],
                    run_spacing=8,
                    spacing=8,
                ),
                ft.Row(
                    [
                        create_button(
                            t("profile.save"),
                            icon=ft.Icons.SAVE,
                            on_click=self._save_profile,
                        ),
                    ],
                ),
            ],
        )

        # --- Cambio de contraseña ---
        self._cur_pwd_field = create_text_field(t("profile.field.current_password"), password=True)
        self._new_pwd_field = create_text_field(t("profile.field.new_password"), password=True)
        self._confirm_pwd_field = create_text_field(t("profile.field.confirm_password"), password=True)
        self._pwd_error = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)

        pwd_section = self._section(
            t("profile.section.password"),
            ft.Icons.LOCK_OUTLINE,
            [
                ft.ResponsiveRow(
                    [
                        ft.Container(self._cur_pwd_field, col=12),
                        ft.Container(self._new_pwd_field, col={"sm": 12, "md": 6}),
                        ft.Container(self._confirm_pwd_field, col={"sm": 12, "md": 6}),
                    ],
                    run_spacing=8,
                    spacing=8,
                ),
                self._pwd_error,
                ft.Row(
                    [
                        create_button(
                            t("profile.change_password"),
                            icon=ft.Icons.LOCK_RESET,
                            on_click=self._change_password,
                        ),
                    ],
                ),
            ],
        )

        self.loading_overlay = LoadingOverlay(t("profile.loading"))
        # Corpo rolável (sem o título). Fica dentro de um Stack que, por estar
        # dentro de um Column (Flex), recebe altura definida e preenche a área a
        # partir do topo — `expand` não funciona como filho direto de um Stack,
        # por isso o conteúdo antes ficava centralizado.
        body = ft.Column(
            [
                avatar_section,
                ft.Container(height=8),
                # Duas colunas lado a lado preenchem a largura da tela.
                ft.ResponsiveRow(
                    [
                        ft.Container(datos_section, col={"sm": 12, "md": 7}),
                        ft.Container(pwd_section, col={"sm": 12, "md": 5}),
                    ],
                    run_spacing=8,
                    spacing=8,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.content = ft.Column(
            [
                ft.Row([create_header(t("profile.title"))]),
                ft.Container(height=SPACING["sm"]),
                ft.Stack([body, self.loading_overlay], expand=True),
            ],
            spacing=0,
            expand=True,
        )
        self.padding = SPACING["md"]
        self.bgcolor = COLORS["bg_primary"]
        self.expand = True

    def _section(self, title: str, icon, content_rows: list) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=18, color=COLORS["accent_primary"]),
                            ft.Text(
                                title,
                                size=FONTS["size_base"],
                                weight=ft.FontWeight.BOLD,
                                color=COLORS["text_primary"],
                            ),
                        ],
                        spacing=6,
                    ),
                    ft.Column(content_rows, spacing=6),
                ],
                spacing=8,
            ),
            padding=12,
            bgcolor=COLORS["bg_surface"],
            border_radius=8,
            border=ft.Border.all(1, COLORS["border"]),
        )

    async def _pick_avatar(self, e):
        # Flet 0.84: pick_files é async e retorna a lista de arquivos.
        files = await self._avatar_picker.pick_files(
            allowed_extensions=["png", "jpg", "jpeg", "webp"],
            dialog_title="Seleccionar foto de perfil",
        )
        if not files:
            return
        path = files[0].path
        try:
            result = auth_service.upload_avatar(path)
            self._populate(result)
            self.current_user = result
            if self.on_user_update:
                self.on_user_update(result)
            self.show_snackbar(t("profile.photo_updated"))
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            self.show_snackbar(friendly_error(err), error=True)

    def _remove_avatar(self, e):
        try:
            result = auth_service.delete_avatar()
            self._populate(result)
            self.current_user = result
            if self.on_user_update:
                self.on_user_update(result)
            self.show_snackbar(t("profile.photo_removed"))
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)

    def _save_profile(self, e):
        fields = {
            "full_name": (self._full_name_field.value or "").strip() or None,
            "email": (self._email_field.value or "").strip() or None,
            "phone": (self._phone_field.value or "").strip() or None,
            "position": (self._position_field.value or "").strip() or None,
            "language": self._language_dd.value,
        }
        try:
            result = auth_service.update_profile(**fields)
            self._populate(result)
            self.current_user = result
            if self.on_user_update:
                self.on_user_update(result)
            self.show_snackbar(t("profile.saved"))
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            self.show_snackbar(friendly_error(err), error=True)

    def _change_password(self, e):
        cur = (self._cur_pwd_field.value or "").strip()
        new = (self._new_pwd_field.value or "").strip()
        confirm = (self._confirm_pwd_field.value or "").strip()

        if not cur or not new or not confirm:
            self._pwd_error.value = t("profile.err.fields_required")
            self._pwd_error.visible = True
            self._safe_update(self._pwd_error)
            return
        if len(new) < 6:
            self._pwd_error.value = t("profile.err.password_min")
            self._pwd_error.visible = True
            self._safe_update(self._pwd_error)
            return
        if new != confirm:
            self._pwd_error.value = t("profile.err.password_mismatch")
            self._pwd_error.visible = True
            self._safe_update(self._pwd_error)
            return
        if new == cur:
            self._pwd_error.value = t("profile.err.password_same")
            self._pwd_error.visible = True
            self._safe_update(self._pwd_error)
            return

        try:
            auth_service.change_password(cur, new)
            self._cur_pwd_field.value = ""
            self._new_pwd_field.value = ""
            self._confirm_pwd_field.value = ""
            self._pwd_error.visible = False
            self._safe_update(self)
            self.show_snackbar(t("profile.password_changed"))
        except APIError as err:
            self._pwd_error.value = str(err.detail)
            self._pwd_error.visible = True
            self._safe_update(self._pwd_error)
