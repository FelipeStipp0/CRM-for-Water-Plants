"""
WMApp Frontend - Settings View
System settings screen.
"""

from typing import List

import flet as ft

from components.loading_overlay import LoadingOverlay
from components.app_modal import AppModal, ModalAction
from components.sifen_config import SifenConfigPanel
from components.theme import (
    COLORS,
    FONTS,
    RADIUS,
    SPACING,
    create_button,
    create_header,
    create_integer_field,
    create_money_field,
    create_percent_field,
    create_phone_field,
    create_text_field,
)
from config.local_settings import (
    get_invoice_print_format,
    get_printer,
    save_preferences,
    set_invoice_print_format,
    set_printer,
)
from i18n import t
from services.api_client import APIError
from utils.errors import friendly_error
from services.auth_service import auth_service
from services.settings_service import settings_service


def get_system_printers() -> List[str]:
    """Return available local/connected printers on Windows."""
    try:
        import win32print

        printers = []
        for printer in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        ):
            printers.append(printer[2])
        return printers
    except ImportError:
        return [t("settings.printers.not_installed")]
    except Exception as err:
        print(f"[SettingsView] get_system_printers_error err={err}")
        return []


class SettingsView(ft.Container):
    """Settings screen aligned with backend API fields."""

    _printers_cache: List[str] | None = None

    def __init__(self, show_snackbar, on_printer_change=None, current_user: dict | None = None):
        super().__init__()
        self.show_snackbar = show_snackbar
        self.on_printer_change = on_printer_change
        self.current_user = current_user or {}
        self.settings = {}
        self.printers = []
        self._loading_settings = False
        self._loading_printers = False

        self._logo_b64: str = ""   # cache local do base64 carregado do backend

        # painel de facturación electrónica (creds + dispositivos)
        self._sifen_panel = SifenConfigPanel(show_snackbar, current_user=self.current_user)

        self._build()

        self.on_visible = self._on_visible

    def _is_master(self) -> bool:
        return self.current_user.get("role") == "master"

    def _on_visible(self, e):
        # Registra FilePicker nos serviços da página (Flet 0.84) na primeira vez.
        if self.page and self._logo_picker not in self.page.services:
            self.page.services.append(self._logo_picker)
        # Operational rule: refresh whenever user opens/returns to this view.
        if self.page:
            try:
                self.page.run_thread(self.trigger_initial_load)
                return
            except Exception as err:
                print(f"[SettingsView] on_visible_run_thread_error err={err}")
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._load_settings_safe()
        self._load_printers()
        self._sifen_panel.load()
        if self._is_master():
            self._load_users()

    def _safe_update(self, control: ft.Control | None):
        if control is None:
            return
        try:
            control.update()
        except Exception:
            try:
                if self.page:
                    self.page.update()
            except Exception:
                pass

    def _load_settings_safe(self):
        if self._loading_settings:
            return
        self._loading_settings = True
        print("[SettingsView] load_start")
        self.loading_overlay.show("Carregando configuracoes...")
        try:
            self.settings = settings_service.get()
            self.load_status.visible = False
            self._safe_update(self.load_status)
            self._populate_fields()
        except APIError as err:
            print(f"[SettingsView] load_api_error detail={err.detail}")
            self.load_status.value = t("settings.load_failed", detail=err.detail)
            self.load_status.color = COLORS["accent_error"]
            self._safe_update(self.load_status)
            self.show_snackbar(t("common.error", detail=err.detail), error=True)
        except Exception as err:
            print(f"[SettingsView] load_unexpected_error err={err}")
            self.load_status.value = t("settings.load_error_unexpected")
            self.load_status.color = COLORS["accent_error"]
            self._safe_update(self.load_status)
        finally:
            self.loading_overlay.hide()
            self._loading_settings = False
            try:
                if self.page:
                    self.page.update()
            except Exception:
                pass
            print("[SettingsView] load_end")

    def _populate_fields(self):
        for key, field in self.junta_fields.items():
            field.value = str(self.settings.get(key, "") or "")
        for key, field in self.tarifa_fields.items():
            field.value = str(self.settings.get(key, "") or "")
        for key, field in self.faturamento_fields.items():
            field.value = str(self.settings.get(key, "") or "")
        for key, field in self.corte_fields.items():
            field.value = str(self.settings.get(key, "") or "")

        # Atención y datos bancarios
        for key, field in self.banco_fields.items():
            field.value = str(self.settings.get(key, "") or "")
        self.alias_tipo_dd.value = self.settings.get("alias_tipo") or "CI"

        # Novos campos de faturamento
        self.gerar_sem_leitura_cb.value = bool(self.settings.get("gerar_sem_leitura_valor_minimo", False))
        prioridade = self.settings.get("matching_prioridade") or ["numero_medidor", "ci_ruc", "nombre_completo"]
        self.matching_prioridade_dd.value = self._prioridade_to_key(prioridade)

        # Logo
        b64 = self.settings.get("logo_base64") or ""
        mime = self.settings.get("logo_mime") or "image/png"
        self._logo_b64 = b64
        if b64:
            self._logo_preview.src = f"data:{mime};base64,{b64}"
            self._logo_preview.visible = True
            self._logo_status.value = t("settings.logo.configured")
            self._logo_status.color = COLORS["accent_success"]
        else:
            self._logo_preview.src = ""
            self._logo_preview.visible = False
            self._logo_status.value = t("settings.logo.none")
            self._logo_status.color = COLORS["text_muted"]

        self._safe_update(self)

    def _build(self):
        header = ft.Row([create_header(t("settings.title"))])
        self.load_status = ft.Text("", size=12, color=COLORS["text_secondary"], visible=False)

        # --- Logo ---
        self._logo_preview = ft.Image(
            src="",
            width=72,
            height=72,
            fit=ft.BoxFit.CONTAIN,
            visible=False,
        )
        self._logo_status = ft.Text(
            t("settings.logo.none"),
            size=FONTS["size_sm"],
            color=COLORS["text_muted"],
        )

        async def _pick_logo(e):
            # Flet 0.84: pick_files é async e retorna a lista de arquivos.
            files = await self._logo_picker.pick_files(
                allowed_extensions=["png", "jpg", "jpeg", "webp"],
                dialog_title=t("settings.logo.pick_title"),
            )
            if not files:
                return
            path = files[0].path
            self._logo_status.value = t("settings.logo.sending")
            self._logo_status.color = COLORS["text_muted"]
            self._safe_update(self._logo_status)
            try:
                result = settings_service.upload_logo(path)
                b64 = result.get("logo_base64") or ""
                mime = result.get("logo_mime") or "image/png"
                self._logo_b64 = b64
                self._logo_preview.src = f"data:{mime};base64,{b64}"
                self._logo_preview.visible = True
                self._logo_status.value = t("settings.logo.updated")
                self._logo_status.color = COLORS["accent_success"]
                self.settings = result
            except APIError as err:
                self._logo_status.value = t("common.error", detail=err.detail)
                self._logo_status.color = COLORS["accent_error"]
            except Exception as err:
                self._logo_status.value = t("common.error_unexpected", err=err)
                self._logo_status.color = COLORS["accent_error"]
            self._safe_update(self._logo_preview)
            self._safe_update(self._logo_status)

        def _remove_logo(e):
            self._logo_status.value = t("settings.logo.removing")
            self._logo_status.color = COLORS["text_muted"]
            self._safe_update(self._logo_status)
            try:
                result = settings_service.delete_logo()
                self._logo_b64 = ""
                self._logo_preview.src = ""
                self._logo_preview.visible = False
                self._logo_status.value = t("settings.logo.removed")
                self._logo_status.color = COLORS["text_muted"]
                self.settings = result
            except APIError as err:
                self._logo_status.value = t("common.error", detail=err.detail)
                self._logo_status.color = COLORS["accent_error"]
            except Exception as err:
                self._logo_status.value = t("common.error_unexpected", err=err)
                self._logo_status.color = COLORS["accent_error"]
            self._safe_update(self._logo_preview)
            self._safe_update(self._logo_status)

        self._logo_picker = ft.FilePicker()

        # Section: Junta/company data
        self.junta_fields = {
            "nombre_junta": create_text_field(t("settings.junta.name"), width=420),
            "ruc_junta": create_text_field(t("settings.junta.ruc"), width=220, max_length=20),
            "direccion_junta": create_text_field(t("settings.junta.address"), width=420),
            "telefono_junta": create_phone_field(t("settings.junta.phone"), width=220, max_length=30),
            "actividad": create_text_field(t("settings.junta.activity"), width=420),
        }
        logo_section_content = ft.Row(
            [
                self._logo_preview,
                ft.Column(
                    [
                        self._logo_status,
                        ft.Row(
                            [
                                create_button(
                                    t("settings.logo.select"),
                                    icon=ft.Icons.UPLOAD_FILE,
                                    on_click=_pick_logo,
                                    primary=False,
                                ),
                                create_button(
                                    t("common.remove"),
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    on_click=_remove_logo,
                                    primary=False,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            t("settings.logo.hint"),
                            size=11,
                            color=COLORS["text_muted"],
                        ),
                    ],
                    spacing=6,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        junta_section = self._section(
            t("settings.junta.section"),
            ft.Icons.BUSINESS,
            [
                ft.Row([self.junta_fields["nombre_junta"], self.junta_fields["ruc_junta"]], spacing=12, run_spacing=12, wrap=True),
                ft.Row([self.junta_fields["direccion_junta"], self.junta_fields["telefono_junta"]], spacing=12, run_spacing=12, wrap=True),
                ft.Row([self.junta_fields["actividad"]], spacing=8),
                ft.Divider(height=1, color=COLORS["border"]),
                logo_section_content,
            ],
        )

        # Section: Global tariff/subsidy
        self.tarifa_fields = {
            "tarifa_base": create_money_field(t("settings.tarifa.base"), col={"sm": 12, "md": 6, "lg": 4, "xl": 2}),
            "consumo_minimo": create_integer_field(t("settings.tarifa.franchise"), suffix="m³", col={"sm": 12, "md": 6, "lg": 4, "xl": 2}),
            "valor_excedente_m3": create_money_field(t("settings.tarifa.excess"), col={"sm": 12, "md": 6, "lg": 4, "xl": 3}),
            "valor_minimo_emissao": create_money_field(t("settings.tarifa.min_emission"), col={"sm": 12, "md": 6, "lg": 4, "xl": 3}),
            "subsidio_porcentagem_padrao": create_percent_field(t("settings.tarifa.subsidy"), col={"sm": 12, "md": 6, "lg": 4, "xl": 2}),
        }
        tarifas_section = self._section(
            t("settings.tarifa.section"),
            ft.Icons.ATTACH_MONEY,
            [
                ft.ResponsiveRow(
                    [
                        self.tarifa_fields["tarifa_base"],
                        self.tarifa_fields["consumo_minimo"],
                        self.tarifa_fields["valor_excedente_m3"],
                        self.tarifa_fields["valor_minimo_emissao"],
                        self.tarifa_fields["subsidio_porcentagem_padrao"],
                    ],
                    columns=12,
                    spacing=12,
                    run_spacing=12,
                ),
                ft.Text(
                    t("settings.tarifa.hint"),
                    size=11,
                    color=COLORS["text_muted"],
                ),
            ],
        )

        self.faturamento_fields = {
            "dia_geracao_faturas": create_integer_field(t("settings.billing.gen_day"), width=220, max_length=2),
            "dias_vencimiento": create_integer_field(t("settings.billing.due_days"), width=220, max_length=3),
        }
        self.gerar_sem_leitura_cb = ft.Checkbox(
            label=t("settings.billing.gen_without_reading"),
            value=False,
        )
        self.matching_prioridade_dd = ft.Dropdown(
            label=t("settings.billing.matching"),
            width=320,
            value="medidor_ci_nome",
            options=[
                ft.dropdown.Option("medidor_ci_nome", t("settings.billing.matching_medidor")),
                ft.dropdown.Option("ci_medidor_nome", t("settings.billing.matching_ci")),
                ft.dropdown.Option("nome_medidor_ci", t("settings.billing.matching_nome")),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )
        faturamento_section = self._section(
            t("settings.billing.section"),
            ft.Icons.RECEIPT_LONG,
            [
                ft.Row(
                    [
                        self.faturamento_fields["dia_geracao_faturas"],
                        self.faturamento_fields["dias_vencimiento"],
                    ],
                    spacing=12,
                    run_spacing=12,
                    wrap=True,
                ),
                self.gerar_sem_leitura_cb,
                ft.Row(
                    [self.matching_prioridade_dd],
                    spacing=8,
                ),
                ft.Text(
                    t("settings.billing.hint"),
                    size=11,
                    color=COLORS["text_muted"],
                ),
            ],
        )

        # Section: Cutoff parameters
        self.corte_fields = {
            "meses_atraso_corte": create_integer_field(t("settings.cutoff.months"), width=210, max_length=2),
            "dias_prazo_aviso": create_integer_field(t("settings.cutoff.notice_days"), width=210, max_length=3),
            "taxa_reativacao": create_money_field(t("settings.cutoff.reactivation_fee"), width=230),
            "multa": create_money_field(t("settings.cutoff.multa"), width=220),
        }
        corte_section = self._section(
            t("settings.cutoff.section"),
            ft.Icons.CONTENT_CUT,
            [
                ft.Row(
                    [
                        self.corte_fields["meses_atraso_corte"],
                        self.corte_fields["dias_prazo_aviso"],
                        self.corte_fields["taxa_reativacao"],
                        self.corte_fields["multa"],
                    ],
                    spacing=12,
                    run_spacing=12,
                    wrap=True,
                ),
            ],
        )

        # Section: Atención y datos bancarios (campos que aparecen en las notificaciones)
        self.banco_fields = {
            "horario_atencion": create_text_field(
                t("settings.bank.hours"), width=420,
            ),
            "banco_nombre": create_text_field(t("settings.bank.bank"), width=320),
            "alias_valor": create_text_field(t("settings.bank.alias"), width=260),
        }
        self.alias_tipo_dd = ft.Dropdown(
            label=t("settings.bank.alias_type"),
            width=200,
            value="CI",
            options=[
                ft.dropdown.Option("CI", t("settings.bank.alias_ci")),
                ft.dropdown.Option("CELULAR", t("settings.bank.alias_celular")),
                ft.dropdown.Option("EMAIL", t("settings.bank.alias_email")),
                ft.dropdown.Option("RUC", t("settings.bank.alias_ruc")),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )
        banco_section = self._section(
            t("settings.bank.section"),
            ft.Icons.ACCOUNT_BALANCE,
            [
                ft.Row([self.banco_fields["horario_atencion"]], spacing=8),
                ft.Row(
                    [
                        self.banco_fields["banco_nombre"],
                        self.alias_tipo_dd,
                        self.banco_fields["alias_valor"],
                    ],
                    spacing=8,
                    wrap=True,
                ),
                ft.Text(
                    t("settings.bank.hint"),
                    size=11,
                    color=COLORS["text_muted"],
                ),
            ],
        )

        # System save section (clear separation from printer settings)
        save_system_section = ft.Container(
            padding=16,
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border_subtle"]),
            border_radius=RADIUS["lg"],
            content=ft.Row(
                [
                    ft.Text(
                        t("settings.save.title"),
                        color=COLORS["text_primary"],
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Container(expand=True),
                    create_button(
                        t("settings.save.button"),
                        icon=ft.Icons.SAVE,
                        on_click=self._save_settings,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        # Section: Local printers only
        self.printer_thermal_dropdown = ft.Dropdown(
            label=t("settings.printers.thermal"),
            options=[],
            width=320,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )
        self.printer_a4_dropdown = ft.Dropdown(
            label=t("settings.printers.a4"),
            options=[],
            width=320,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )
        self.invoice_format_dropdown = ft.Dropdown(
            label=t("settings.printers.invoice_format"),
            width=320,
            value="p80",
            options=[
                ft.dropdown.Option("p80", t("settings.printers.thermal")),
                ft.dropdown.Option("a4", t("settings.printers.a4")),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )
        impressoras_section = self._section(
            t("settings.printers.section"),
            ft.Icons.PRINT,
            [
                ft.Row([self.printer_thermal_dropdown, self.printer_a4_dropdown], spacing=12, run_spacing=12, wrap=True),
                ft.Row([self.invoice_format_dropdown], spacing=8),
                ft.Row(
                    [
                        create_button(
                            t("settings.printers.save"),
                            icon=ft.Icons.SAVE,
                            on_click=self._save_printers,
                            primary=False,
                        ),
                        create_button(
                            t("common.update"),
                            icon=ft.Icons.REFRESH,
                            on_click=lambda e: self._refresh_printers(),
                            primary=False,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Text(
                    t("settings.printers.hint"),
                    size=11,
                    color=COLORS["text_muted"],
                ),
            ],
        )

        self._users_list_column = ft.Column([], spacing=4)
        users_admin_section = None
        if self._is_master():
            users_admin_section = self._section(
                t("settings.users.section"),
                ft.Icons.ADMIN_PANEL_SETTINGS,
                [
                    ft.Row(
                        [
                            ft.Text(
                                t("settings.users.subtitle"),
                                size=11,
                                color=COLORS["text_secondary"],
                                expand=True,
                            ),
                            create_button(
                                t("settings.users.invite"),
                                icon=ft.Icons.PERSON_ADD,
                                on_click=self._open_create_user_modal,
                                primary=False,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._users_list_column,
                ],
            )

        sifen_section = self._section(
            "Facturación Electrónica",
            ft.Icons.RECEIPT_LONG,
            [self._sifen_panel],
        )

        sections = [
            junta_section,
            tarifas_section,
            faturamento_section,
            corte_section,
            banco_section,
            save_system_section,
            impressoras_section,
            sifen_section,
        ]
        if users_admin_section is not None:
            sections.append(users_admin_section)
        main_content = ft.Column(
            [
                header,
                self.load_status,
                ft.Container(height=SPACING["sm"]),
                ft.Column(
                    sections,
                    spacing=SPACING["md"],
                    expand=True,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self.loading_overlay = LoadingOverlay("Carregando configuracoes...")
        self.content = ft.Stack(
            [
                main_content,
                self.loading_overlay,
            ],
            expand=True,
        )
        self.padding = ft.Padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"])
        self.expand = True

    def _section(self, title: str, icon, content_rows: list) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=18, color=COLORS["accent_secondary"]),
                            ft.Text(
                                title,
                                size=FONTS["size_base"],
                                weight=ft.FontWeight.BOLD,
                                color=COLORS["text_primary"],
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Column(content_rows, spacing=10),
                ],
                spacing=12,
            ),
            padding=18,
            bgcolor=COLORS["bg_surface"],
            border_radius=RADIUS["lg"],
            border=ft.Border.all(1, COLORS["border_subtle"]),
        )

    _PRIORIDADE_MAP = {
        "medidor_ci_nome": ["numero_medidor", "ci_ruc", "nombre_completo"],
        "ci_medidor_nome": ["ci_ruc", "numero_medidor", "nombre_completo"],
        "nome_medidor_ci": ["nombre_completo", "numero_medidor", "ci_ruc"],
    }

    def _prioridade_to_key(self, prioridade: list) -> str:
        for key, val in self._PRIORIDADE_MAP.items():
            if val == prioridade:
                return key
        return "medidor_ci_nome"

    def _prioridade_from_key(self, key: str) -> list:
        return self._PRIORIDADE_MAP.get(key, ["numero_medidor", "ci_ruc", "nombre_completo"])

    def _load_printers(self):
        if self._loading_printers:
            return
        self._loading_printers = True
        try:
            if SettingsView._printers_cache is None:
                SettingsView._printers_cache = get_system_printers()
            self.printers = list(SettingsView._printers_cache or [])
            options = [ft.dropdown.Option("(Nenhuma)")] + [ft.dropdown.Option(p) for p in self.printers]

            self.printer_thermal_dropdown.options = options
            self.printer_a4_dropdown.options = options

            saved_thermal = get_printer("thermal")
            saved_a4 = get_printer("a4")

            self.printer_thermal_dropdown.value = saved_thermal if saved_thermal in self.printers else "(Nenhuma)"
            self.printer_a4_dropdown.value = saved_a4 if saved_a4 in self.printers else "(Nenhuma)"
            self.invoice_format_dropdown.value = get_invoice_print_format()
            self._safe_update(self.printer_thermal_dropdown)
            self._safe_update(self.printer_a4_dropdown)
            self._safe_update(self.invoice_format_dropdown)
        finally:
            self._loading_printers = False
            try:
                if self.page:
                    self.page.update()
            except Exception:
                pass

    def _save_printers(self, e):
        thermal = self.printer_thermal_dropdown.value
        a4 = self.printer_a4_dropdown.value

        set_printer("thermal", thermal if thermal != "(Nenhuma)" else None)
        set_printer("a4", a4 if a4 != "(Nenhuma)" else None)
        set_invoice_print_format(self.invoice_format_dropdown.value or "p80")

        self.show_snackbar(t("settings.printers.saved"))
        if self.on_printer_change:
            self.on_printer_change("thermal", thermal)
            self.on_printer_change("a4", a4)

    def _refresh_printers_cache(self):
        SettingsView._printers_cache = get_system_printers()

    def _refresh_printers(self):
        self._refresh_printers_cache()
        self._load_printers()
        self._safe_update(self)

    def _save_settings(self, e):
        data = {}

        for key, field in self.junta_fields.items():
            if field.value and field.value.strip():
                data[key] = field.value.strip()

        for key, field in self.tarifa_fields.items():
            if field.value and field.value.strip():
                try:
                    if key in {"subsidio_porcentagem_padrao", "consumo_minimo"}:
                        data[key] = int(field.value.strip())
                    else:
                        data[key] = float(field.value.strip())
                except ValueError:
                    pass

        for key, field in self.faturamento_fields.items():
            if field.value and field.value.strip():
                try:
                    data[key] = int(field.value.strip())
                except ValueError:
                    pass

        for key, field in self.corte_fields.items():
            if field.value and field.value.strip():
                try:
                    if key in ("taxa_reativacao", "multa"):
                        data[key] = float(field.value.strip())
                    else:
                        data[key] = int(field.value.strip())
                except ValueError:
                    pass

        # Atención y datos bancarios (strings; se vacío se envía "" para limpiar)
        for key, field in self.banco_fields.items():
            data[key] = (field.value or "").strip()
        data["alias_tipo"] = self.alias_tipo_dd.value or "CI"

        # Novos campos de faturamento
        data["gerar_sem_leitura_valor_minimo"] = bool(self.gerar_sem_leitura_cb.value)
        data["matching_prioridade"] = self._prioridade_from_key(
            self.matching_prioridade_dd.value or "medidor_ci_nome"
        )

        try:
            result = settings_service.update(data)
            self.settings = result
            self.load_status.visible = False
            self._safe_update(self.load_status)
            self.show_snackbar(t("settings.saved"))
        except APIError as err:
            self.load_status.value = t("settings.save_failed", detail=err.detail)
            self.load_status.color = COLORS["accent_error"]
            self._safe_update(self.load_status)
            self.show_snackbar(t("common.error", detail=err.detail), error=True)

    def _load_users(self):
        """Carrega lista de usuarios da org e atualiza a coluna de usuarios."""
        try:
            users = auth_service.list_users()
            self._users_list_column.controls.clear()
            current_username = self.current_user.get("username", "")
            for u in users:
                is_self = u["username"] == current_username
                is_active = u.get("is_active", True)
                role_label = "Master" if u.get("role") == "master" else "Operador"
                scopes_text = ", ".join(u.get("scopes") or []) or "—"

                toggle_btn = create_button(
                    "Desactivar" if is_active else "Activar",
                    icon=ft.Icons.BLOCK if is_active else ft.Icons.CHECK_CIRCLE_OUTLINE,
                    on_click=lambda ev, uname=u["username"]: self._toggle_user(uname),
                    primary=False,
                ) if not is_self else ft.Container()

                row = ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.PERSON if is_active else ft.Icons.PERSON_OFF,
                                size=18,
                                color=COLORS["accent_primary"] if is_active else COLORS["text_muted"],
                            ),
                            ft.Column(
                                [
                                    ft.Row([
                                        ft.Text(u["full_name"], size=13, weight=ft.FontWeight.W_500, color=COLORS["text_primary"]),
                                        ft.Container(
                                            content=ft.Text(role_label, size=10, color=COLORS["text_primary"]),
                                            bgcolor=COLORS["accent_primary"] if u.get("role") == "master" else COLORS["bg_elevated"],
                                            border_radius=4,
                                            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                        ),
                                        ft.Container(
                                            content=ft.Text("Cambio pendiente", size=10, color=COLORS["accent_warning"]),
                                            visible=bool(u.get("must_change_password")),
                                        ),
                                    ], spacing=6),
                                    ft.Text(f"@{u['username']} · {u['email']}", size=11, color=COLORS["text_secondary"]),
                                    ft.Text(f"Módulos: {scopes_text}", size=11, color=COLORS["text_muted"]),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            toggle_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                    bgcolor=COLORS["bg_elevated"] if not is_active else COLORS["bg_surface"],
                    border_radius=6,
                    border=ft.Border.all(1, COLORS["border"]),
                )
                self._users_list_column.controls.append(row)
            self._safe_update(self._users_list_column)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            print(f"[SettingsView] load_users_error err={err}")

    def _toggle_user(self, username: str):
        try:
            auth_service.toggle_user_active(username)
            self._load_users()
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)

    def _open_create_user_modal(self, e=None):
        if not self._is_master():
            self.show_snackbar("Solo el master puede crear usuarios.", error=True)
            return

        username_field = create_text_field("Usuario", width=220)
        full_name_field = create_text_field("Nombre completo", width=320)
        email_field = create_text_field("Email", width=320)
        password_field = create_text_field("Contraseña", password=True, width=220)
        confirm_field = create_text_field("Confirmar contraseña", password=True, width=220)
        role_dd = ft.Dropdown(
            label="Rol",
            value="operator",
            width=180,
            options=[
                ft.dropdown.Option("operator", "Operador"),
                ft.dropdown.Option("master", "Master"),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )

        scope_options = [
            ("clients", "Clientes"),
            ("readings", "Lecturas"),
            ("invoices", "Facturación"),
            ("payments", "Caja"),
            ("cutoff", "Corte"),
            ("finance", "Finanzas"),
            ("sponsors", "Subsidios"),
            ("settings", "Configuración"),
            ("*", "Acceso total (*)"),
        ]
        scope_checks: dict[str, ft.Checkbox] = {}
        for scope, label in scope_options:
            scope_checks[scope] = ft.Checkbox(label=label, value=False)

        scopes_container = ft.ResponsiveRow(
            [
                ft.Container(content=cb, col={"sm": 6, "md": 4, "lg": 3})
                for cb in scope_checks.values()
            ],
            run_spacing=4,
        )
        scopes_label = ft.Text("Módulos de acceso (para operadores):", color=COLORS["text_secondary"], size=12)

        def on_role_change(ev):
            is_op = role_dd.value == "operator"
            scopes_label.visible = is_op
            scopes_container.visible = is_op
            self._safe_update(scopes_label)
            self._safe_update(scopes_container)

        role_dd.on_change = on_role_change

        def on_scope_change(ev):
            wildcard = bool(scope_checks["*"].value)
            for key, cb in scope_checks.items():
                if key == "*":
                    continue
                cb.disabled = wildcard
                cb.value = False if wildcard else cb.value
                self._safe_update(cb)

        scope_checks["*"].on_change = on_scope_change

        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def save_user(ev):
            username = (username_field.value or "").strip()
            full_name = (full_name_field.value or "").strip()
            email = (email_field.value or "").strip()
            password = (password_field.value or "").strip()
            confirm = (confirm_field.value or "").strip()
            role = role_dd.value or "operator"

            selected_scopes = [scope for scope, cb in scope_checks.items() if cb.value]
            if role == "master":
                selected_scopes = ["*"]

            if not username or not full_name or not email or not password:
                error_text.value = "Complete todos los campos obligatorios."
                error_text.visible = True
                self._safe_update(error_text)
                return
            if password != confirm:
                error_text.value = "Las contraseñas no coinciden."
                error_text.visible = True
                self._safe_update(error_text)
                return
            if role == "operator" and not selected_scopes:
                error_text.value = "Seleccione al menos un módulo de acceso."
                error_text.visible = True
                self._safe_update(error_text)
                return

            try:
                auth_service.register(
                    username=username,
                    email=email,
                    password=password,
                    full_name=full_name,
                    role=role,
                    scopes=selected_scopes,
                )
                if _modal_ref:
                    _modal_ref[0].close()
                self.show_snackbar(f"Usuario {username} creado. Debe cambiar su contraseña al ingresar.")
                self._load_users()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                self._safe_update(error_text)
            except Exception as err:
                error_text.value = friendly_error(err)
                error_text.visible = True
                self._safe_update(error_text)

        _modal_ref: list[AppModal] = []
        modal = AppModal(
            page=self.page,
            title="Invitar usuario",
            content=ft.Column(
                [
                    ft.Row([username_field, role_dd], spacing=8, wrap=True),
                    ft.Row([full_name_field], spacing=8),
                    ft.Row([email_field], spacing=8),
                    ft.Row([password_field, confirm_field], spacing=8, wrap=True),
                    ft.Text("La contraseña es temporal — el usuario deberá cambiarla al ingresar.", size=11, color=COLORS["text_muted"]),
                    scopes_label,
                    scopes_container,
                    error_text,
                ],
                spacing=8,
                tight=True,
            ),
            actions=[
                ModalAction("Cancelar", on_click=lambda ev: modal.close()),
                ModalAction("Invitar", on_click=save_user, primary=True),
            ],
            width_pct=0.6,
        )
        _modal_ref.append(modal)
        modal.open()
