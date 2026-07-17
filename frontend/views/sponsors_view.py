"""
WMApp Frontend - Subsidios View
Tela de gestao de subsidios, dividas e faturas agregadas.
"""
from datetime import datetime

import flet as ft

from components.custom_tabs import CustomTabs, TabItem
from components.data_table import DataTable
from components.loading_overlay import LoadingOverlay
from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, SPACING, create_button, create_header, create_text_field
from services.api_client import APIError
from utils.errors import friendly_error
from services.client_service import client_service
from services.sponsor_service import sponsor_service
from i18n import t
from utils.formatters import format_currency, format_date


class SponsorsView(ft.Container):
    """Tela de subsidios."""

    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self._loaded = False
        self.selected_sponsor = None
        self._loading_sponsors = False
        self._loading_details = False

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._run_load_sponsors()

    def _run_load_sponsors(self):
        try:
            if not self.sponsors_table.data:
                self.sponsors_table.show_skeleton(rows=8)
        except Exception:
            pass
        if self.page:
            try:
                self.page.run_thread(self._load_sponsors)
                return
            except Exception as err:
                print(f"[SponsorsView] run_thread_sponsors_error err={err}")
        self._load_sponsors()

    def _run_load_sponsor_details(self):
        for table in ("clients_table", "debts_table", "invoices_table"):
            try:
                t_ref = getattr(self, table, None)
                if t_ref and not t_ref.data:
                    t_ref.show_skeleton(rows=6)
            except Exception:
                pass
        if self.page:
            try:
                self.page.run_thread(self._load_sponsor_details)
                return
            except Exception as err:
                print(f"[SponsorsView] run_thread_details_error err={err}")
        self._load_sponsor_details()

    def _safe_update(self, control: ft.Control | None):
        if control is None:
            return
        try:
            control.update()
        except Exception as err:
            print(f"[SponsorsView] safe_update_error control={type(control).__name__} err={err}")
            if self.page:
                try:
                    self.page.update()
                except Exception as page_err:
                    print(f"[SponsorsView] page_update_fallback_error err={page_err}")

    def _build(self):
        header = ft.Row(
            [
                create_header(t("sponsors.title")),
                ft.Container(expand=True),
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_load_sponsors(), primary=False),
            ]
        )

        self.sponsors_table = DataTable(
            columns=[
                {"key": "nombre_completo", "label": t("sponsors.col.responsible"), "min_width": 210, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "ci_ruc", "label": "CI/RUC", "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
                {"key": "telefono", "label": t("sponsors.col.phone"), "min_width": 110, "flex": 1, "priority": 3, "align": "center"},
                {"key": "manzana", "label": t("sponsors.col.mz"), "min_width": 48, "flex": 1, "priority": 4, "align": "center"},
                {"key": "lote", "label": t("sponsors.col.lt"), "min_width": 48, "flex": 1, "priority": 4, "align": "center"},
            ],
            data=[],
            on_row_click=self._select_sponsor,
            show_actions=False,
        )

        self.summary_title = ft.Text(t("sponsors.summary.select_prompt"), color=COLORS["text_secondary"])
        self.summary_period_info = ft.Text(t("sponsors.summary.no_period"), color=COLORS["text_secondary"], size=12)
        self.metric_pendente = ft.Text("Gs. 0", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=16)
        self.metric_faturado = ft.Text("Gs. 0", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=16)
        self.metric_pago = ft.Text("Gs. 0", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=16)
        self.metric_debitos = ft.Text("0", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=16)

        self.clients_table = DataTable(
            columns=[
                {"key": "nombre_completo", "label": t("sponsors.col.client"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "ci_ruc", "label": "CI/RUC", "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
                {"key": "subsidio_label", "label": t("sponsors.col.subsidy"), "min_width": 100, "flex": 1, "priority": 3, "align": "center"},
                {"key": "status", "label": "Status", "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
            ],
            data=[],
            show_actions=False,
        )

        self.debt_status = ft.Dropdown(
            label=t("sponsors.filter.debt_status"),
            width=140,
            value="",
            options=[
                ft.dropdown.Option("", t("sponsors.filter.all_m")),
                ft.dropdown.Option("PENDENTE"),
                ft.dropdown.Option("FATURADO"),
                ft.dropdown.Option("PAGO"),
            ],
        )
        self.debt_mes = create_text_field(t("sponsors.field.month"), width=80)
        self.debt_ano = create_text_field(t("sponsors.field.year"), width=100)

        self.debts_table = DataTable(
            columns=[
                {"key": "periodo", "label": "Período", "min_width": 90, "flex": 1, "priority": 2, "align": "center"},
                {"key": "client_original_name", "label": t("sponsors.col.client"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "porcentagem_label", "label": t("sponsors.col.pct"), "min_width": 56, "flex": 1, "priority": 3, "align": "center"},
                {"key": "valor_subsidio_fmt", "label": t("sponsors.col.value"), "min_width": 110, "flex": 1, "priority": 2, "align": "right"},
                {"key": "status", "label": "Status", "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
            ],
            data=[],
            show_actions=False,
        )

        self.invoice_status = ft.Dropdown(
            label=t("sponsors.filter.invoice_status"),
            width=150,
            value="",
            options=[
                ft.dropdown.Option("", t("sponsors.filter.all_f")),
                ft.dropdown.Option("PENDENTE"),
                ft.dropdown.Option("PAGA"),
                ft.dropdown.Option("PARCIAL"),
            ],
        )

        self.invoices_table = DataTable(
            columns=[
                {"key": "periodo", "label": "Período", "min_width": 90, "flex": 1, "priority": 2, "align": "center"},
                {"key": "status", "label": "Status", "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
                {"key": "valor_total_fmt", "label": t("sponsors.col.value"), "min_width": 110, "flex": 1, "priority": 2, "align": "right"},
                {"key": "saldo_devedor_fmt", "label": t("sponsors.col.balance_due"), "min_width": 110, "flex": 1, "priority": 3, "align": "right"},
                {"key": "fecha_emision_fmt", "label": t("sponsors.col.emission"), "min_width": 100, "flex": 1, "priority": 4, "align": "center"},
            ],
            data=[],
            on_edit=self._pay_invoice_modal,
            on_row_click=self._show_invoice_details,
            show_actions=True,
        )

        tabs = CustomTabs(
            tabs=[
                TabItem(t("sponsors.tab.clients"), self._build_clients_tab()),
                TabItem(t("sponsors.tab.debts"), self._build_debts_tab()),
                TabItem(t("sponsors.tab.invoices"), self._build_invoices_tab()),
            ],
            selected_index=0,
        )

        summary_cards = ft.Row(
            [
                self._build_metric_card(t("sponsors.metric.pending"), self.metric_pendente, ft.Icons.WARNING_AMBER, COLORS["accent_warning"]),
                self._build_metric_card(t("sponsors.metric.invoiced"), self.metric_faturado, ft.Icons.RECEIPT_LONG, COLORS["accent_secondary"]),
                self._build_metric_card(t("sponsors.metric.paid"), self.metric_pago, ft.Icons.TASK_ALT, COLORS["accent_success"]),
                self._build_metric_card(t("sponsors.metric.debits"), self.metric_debitos, ft.Icons.FORMAT_LIST_NUMBERED, COLORS["text_secondary"]),
            ],
            spacing=SPACING["sm"],
            run_spacing=SPACING["sm"],
            wrap=True,
        )

        details = ft.Container(
            expand=6,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PEOPLE, size=18, color=COLORS["accent_secondary"]),
                            self.summary_title,
                            ft.Container(expand=True),
                            self.summary_period_info,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "Resumo financeiro e operacao mensal de subsidios por responsavel.",
                        color=COLORS["text_secondary"],
                        size=12,
                    ),
                    ft.Container(height=SPACING["xs"]),
                    summary_cards,
                    ft.Divider(color=COLORS["border"]),
                    tabs,
                ],
                spacing=8,
                expand=True,
            ),
            padding=12,
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
        )

        sponsors_panel = ft.Container(
            expand=4,
            padding=12,
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PEOPLE, size=18, color=COLORS["accent_secondary"]),
                            ft.Text(t("sponsors.registered_title"), color=COLORS["text_primary"], weight=ft.FontWeight.BOLD),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "Selecione um responsavel na tabela para abrir clientes, dividas e faturas.",
                        color=COLORS["text_secondary"],
                        size=12,
                    ),
                    ft.Container(height=SPACING["sm"]),
                    self.sponsors_table,
                ],
                spacing=8,
                expand=True,
            ),
        )

        main_content = ft.Column(
            [
                header,
                ft.Container(height=SPACING["sm"]),
                ft.Row(
                    [
                        sponsors_panel,
                        details,
                    ],
                    spacing=SPACING["sm"],
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    expand=True,
                ),
            ],
            expand=True,
        )
        self.loading_overlay = LoadingOverlay(t("sponsors.loading"))
        self.content = ft.Stack(
            [
                main_content,
                self.loading_overlay,
            ],
            expand=True,
        )
        self.bgcolor = COLORS["bg_primary"]
        self.padding = ft.Padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"])
        self.expand = True

    def _build_action_bar(self, controls: list[ft.Control]) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                controls,
                wrap=True,
                spacing=SPACING["sm"],
                run_spacing=SPACING["sm"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_elevated"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
        )

    def _build_metric_card(self, title: str, value_control: ft.Control, icon: str, icon_color: str) -> ft.Control:
        return ft.Container(
            width=165,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=14, color=icon_color),
                            ft.Text(title, color=COLORS["text_secondary"], size=12),
                        ],
                        spacing=6,
                    ),
                    value_control,
                ],
                spacing=4,
                tight=True,
            ),
        )

    def _build_clients_tab(self) -> ft.Control:
        return ft.Column(
            [
                ft.Container(height=SPACING["md"]),
                ft.Text(
                    "Clientes vinculados ao responsavel selecionado.",
                    color=COLORS["text_secondary"],
                    size=12,
                ),
                ft.Container(height=SPACING["sm"]),
                ft.Container(
                    expand=True,
                    bgcolor=COLORS["bg_surface"],
                    border=ft.Border.all(1, COLORS["border"]),
                    border_radius=10,
                    padding=8,
                    content=self.clients_table,
                ),
            ],
            expand=True,
        )

    def _build_debts_tab(self) -> ft.Control:
        actions = self._build_action_bar(
            [
                self.debt_status,
                self.debt_mes,
                self.debt_ano,
                create_button("Aplicar", icon=ft.Icons.FILTER_ALT, on_click=lambda e: self._run_load_sponsor_details(), primary=False),
            ]
        )

        return ft.Column(
            [
                ft.Container(height=SPACING["md"]),
                actions,
                ft.Container(height=SPACING["md"]),
                ft.Container(
                    expand=True,
                    bgcolor=COLORS["bg_surface"],
                    border=ft.Border.all(1, COLORS["border"]),
                    border_radius=10,
                    padding=8,
                    content=self.debts_table,
                ),
            ],
            expand=True,
        )

    def _build_invoices_tab(self) -> ft.Control:
        actions = self._build_action_bar(
            [
                self.invoice_status,
                create_button("Filtrar", icon=ft.Icons.FILTER_ALT, on_click=lambda e: self._run_load_sponsor_details(), primary=False),
                create_button("Gerar Fatura Mensal", icon=ft.Icons.POST_ADD, on_click=self._generate_invoice_modal),
            ]
        )

        return ft.Column(
            [
                ft.Container(height=SPACING["md"]),
                actions,
                ft.Container(height=SPACING["md"]),
                ft.Container(
                    expand=True,
                    bgcolor=COLORS["bg_surface"],
                    border=ft.Border.all(1, COLORS["border"]),
                    border_radius=10,
                    padding=8,
                    content=self.invoices_table,
                ),
            ],
            expand=True,
        )

    def _load_sponsors(self):
        if self._loading_sponsors:
            return
        self._loading_sponsors = True
        print("[SponsorsView] load_sponsors_start")
        try:
            sponsors = sponsor_service.list_sponsors()
            if not sponsors:
                sponsors = client_service.search(is_sponsor=True, limit=200)

            self.sponsors_table.set_data(sponsors)

            if not sponsors:
                self.selected_sponsor = None
                self.summary_title.value = t("sponsors.summary.none_found")
                self.summary_title.color = COLORS["text_secondary"]
                self.summary_period_info.value = t("sponsors.summary.no_data")
                self.metric_pendente.value = "Gs. 0"
                self.metric_faturado.value = "Gs. 0"
                self.metric_pago.value = "Gs. 0"
                self.metric_debitos.value = "0"
                self._safe_update(self.summary_title)
                self._safe_update(self.summary_period_info)
                self._safe_update(self.metric_pendente)
                self._safe_update(self.metric_faturado)
                self._safe_update(self.metric_pago)
                self._safe_update(self.metric_debitos)
                self.clients_table.set_data([])
                self.debts_table.set_data([])
                self.invoices_table.set_data([])
                return

            if self.selected_sponsor:
                selected_id = self.selected_sponsor.get("id")
                self.selected_sponsor = next((s for s in sponsors if s.get("id") == selected_id), None)

            if self.selected_sponsor is None:
                self._select_sponsor(sponsors[0])
            else:
                self._run_load_sponsor_details()
        except APIError as err:
            print(f"[SponsorsView] load_sponsors_api_error detail={err.detail}")
            self.sponsors_table.set_error(t("sponsors.load_failed"), on_retry=self._run_load_sponsors)
            self.show_snackbar(friendly_error(err), error=True)
        finally:
            self._loading_sponsors = False
            if self.page:
                try:
                    self.page.update()
                except Exception as err:
                    print(f"[SponsorsView] load_sponsors_final_page_update_error err={err}")
            print("[SponsorsView] load_sponsors_end")

    def _select_sponsor(self, sponsor_row: dict):
        self.selected_sponsor = sponsor_row
        self._run_load_sponsor_details()

    def _load_sponsor_details(self):
        if not self.selected_sponsor or self._loading_details:
            return
        self._loading_details = True
        print(f"[SponsorsView] load_details_start sponsor_id={self.selected_sponsor.get('id')}")
        sponsor_id = self.selected_sponsor["id"]
        try:
            summary = sponsor_service.get_summary(sponsor_id)
            clients = sponsor_service.list_clients(sponsor_id)
            debt_status = self.debt_status.value or None
            debt_mes = int((self.debt_mes.value or "").strip()) if (self.debt_mes.value or "").strip() else None
            debt_ano = int((self.debt_ano.value or "").strip()) if (self.debt_ano.value or "").strip() else None
            debts = sponsor_service.list_debts(sponsor_id, status=debt_status, mes=debt_mes, ano=debt_ano)
            inv_status = self.invoice_status.value or None
            invoices = sponsor_service.list_invoices(sponsor_id, status=inv_status)

            self.summary_title.value = f"Responsavel: {summary.get('sponsor_name', '-')}"
            self.summary_title.color = COLORS["text_primary"]
            if debt_mes and debt_ano:
                self.summary_period_info.value = f"Filtro de dividas: {debt_mes:02d}/{debt_ano}"
            elif debt_ano:
                self.summary_period_info.value = f"Filtro de dividas: ano {debt_ano}"
            elif debt_mes:
                self.summary_period_info.value = f"Filtro de dividas: mes {debt_mes:02d}"
            else:
                self.summary_period_info.value = t("sponsors.summary.no_period")
            self.metric_pendente.value = format_currency(summary.get("total_pendente", 0), "Gs.")
            self.metric_faturado.value = format_currency(summary.get("total_faturado", 0), "Gs.")
            self.metric_pago.value = format_currency(summary.get("total_pago", 0), "Gs.")
            self.metric_debitos.value = str(summary.get("count_debts", 0))
            self._safe_update(self.summary_period_info)
            self._safe_update(self.metric_pendente)
            self._safe_update(self.metric_faturado)
            self._safe_update(self.metric_pago)
            self._safe_update(self.metric_debitos)
            self._safe_update(self.summary_title)

            clients_rows = []
            for c in clients:
                row = dict(c)
                sub = c.get("subsidio_porcentagem")
                row["subsidio_label"] = f"{sub}%" if sub is not None else "Padrao"
                clients_rows.append(row)
            self.clients_table.set_data(clients_rows)

            debt_rows = []
            for d in debts:
                row = dict(d)
                row["periodo"] = f"{d.get('mes_referencia', 0):02d}/{d.get('ano_referencia', '')}"
                row["porcentagem_label"] = f"{d.get('porcentagem_aplicada', 0)}%"
                row["valor_subsidio_fmt"] = format_currency(d.get("valor_subsidio", 0), "Gs.")
                debt_rows.append(row)
            self.debts_table.set_data(debt_rows)

            inv_rows = []
            for inv in invoices:
                row = dict(inv)
                row["periodo"] = f"{inv.get('mes_referencia', 0):02d}/{inv.get('ano_referencia', '')}"
                row["valor_total_fmt"] = format_currency(inv.get("valor_total", 0), "Gs.")
                row["saldo_devedor_fmt"] = format_currency(inv.get("saldo_devedor", 0), "Gs.")
                row["fecha_emision_fmt"] = format_date(inv.get("fecha_emision"))
                inv_rows.append(row)
            self.invoices_table.set_data(inv_rows)

        except ValueError:
            self.debts_table.set_error(t("sponsors.err.invalid_period"), on_retry=self._run_load_sponsor_details)
            self.show_snackbar(t("sponsors.err.invalid_period"), error=True)
        except APIError as err:
            print(f"[SponsorsView] load_details_api_error detail={err.detail}")
            self.clients_table.set_error(t("sponsors.load_failed.clients"), on_retry=self._run_load_sponsor_details)
            self.debts_table.set_error(t("sponsors.load_failed.debts"), on_retry=self._run_load_sponsor_details)
            self.invoices_table.set_error(t("sponsors.load_failed.invoices"), on_retry=self._run_load_sponsor_details)
            self.show_snackbar(friendly_error(err), error=True)
        finally:
            self._loading_details = False
            if self.page:
                try:
                    self.page.update()
                except Exception as err:
                    print(f"[SponsorsView] load_details_final_page_update_error err={err}")
            print("[SponsorsView] load_details_end")

    def _generate_invoice_modal(self, e):
        if not self.selected_sponsor:
            self.show_snackbar(t("sponsors.select_first"), error=True)
            return

        mes_field = create_text_field(t("sponsors.field.month"), value=str(datetime.now().month), width=100)
        ano_field = create_text_field(t("sponsors.field.year"), value=str(datetime.now().year), width=120)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def run_generate(ev):
            try:
                result = sponsor_service.generate_invoice(
                    self.selected_sponsor["id"],
                    int((mes_field.value or "").strip()),
                    int((ano_field.value or "").strip()),
                )
                if _modal_ref:
                    _modal_ref[0].close()
                self.show_snackbar(
                    t("sponsors.gen.generated",
                      period=f"{result.get('mes_referencia', 0):02d}/{result.get('ano_referencia', '')}")
                )
                self._run_load_sponsor_details()
            except ValueError:
                error_text.value = t("sponsors.err.invalid_month_year")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref: list[AppModal] = []
        modal = AppModal(
            page=self.page,
            title=t("sponsors.gen.title"),
            content=ft.Column([ft.Row([mes_field, ano_field]), error_text], spacing=8, tight=True),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal.close()),
                ModalAction(t("invoices.btn.generate"), on_click=run_generate, primary=True),
            ],
            width_pct=0.3,
        )
        _modal_ref.append(modal)
        modal.open()

    def _pay_invoice_modal(self, invoice_row: dict):
        saldo = float(invoice_row.get("saldo_devedor", 0) or 0)
        valor_field = create_text_field(t("sponsors.pay.value"), value=str(saldo), width=180)
        recibido_field = create_text_field(t("sponsors.pay.receiver"), width=220)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def run_pay(ev):
            try:
                result = sponsor_service.pay_invoice(
                    invoice_row["id"],
                    valor=float((valor_field.value or "").strip().replace(",", ".")),
                    recibido_por=(recibido_field.value or "").strip() or None,
                )
                if _modal_ref_pay:
                    _modal_ref_pay[0].close()
                self.show_snackbar(
                    t("sponsors.pay.registered",
                      value=format_currency(result.get('saldo_restante', 0), 'Gs.'))
                )
                self._run_load_sponsor_details()
            except ValueError:
                error_text.value = t("sponsors.err.invalid_value")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_pay: list[AppModal] = []
        modal_pay = AppModal(
            page=self.page,
            title=t("sponsors.pay.title"),
            content=ft.Column(
                [
                    ft.Text(f"Periodo: {invoice_row.get('periodo', '-')}"),
                    ft.Text(f"Saldo: {format_currency(invoice_row.get('saldo_devedor', 0), 'Gs.')}"),
                    valor_field,
                    recibido_field,
                    error_text,
                ],
                spacing=8,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_pay.close()),
                ModalAction(t("finance.btn.pay"), on_click=run_pay, primary=True),
            ],
            width_pct=0.35,
        )
        _modal_ref_pay.append(modal_pay)
        modal_pay.open()

    def _show_invoice_details(self, invoice_row: dict):
        modal = AppModal(
            page=self.page,
            title=t("sponsors.aggregate.title"),
            content=ft.Column(
                [
                    ft.Text(f"Periodo: {invoice_row.get('periodo', '-')}"),
                    ft.Text(f"Status: {invoice_row.get('status', '-')}"),
                    ft.Text(f"Valor: {format_currency(invoice_row.get('valor_total', 0), 'Gs.')}"),
                    ft.Text(f"Saldo: {format_currency(invoice_row.get('saldo_devedor', 0), 'Gs.')}"),
                    ft.Text(f"Emissao: {invoice_row.get('fecha_emision_fmt', '-')}"),
                    ft.Text(
                        f"Debitos incluidos: {len(invoice_row.get('debts_included', []))}",
                        color=COLORS["text_secondary"],
                    ),
                ],
                spacing=6,
            ),
            actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
            width_pct=0.35,
        )
        modal.open()
