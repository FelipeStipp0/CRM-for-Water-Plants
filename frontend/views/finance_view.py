"""
WMApp Frontend - Finance View
Modulo financeiro com abas de caixa, despesas, funcionarios e folha.
"""
from datetime import datetime

import flet as ft

from components.custom_tabs import CustomTabs, TabItem
from components.data_table import DataTable
from components.loading_overlay import LoadingOverlay
from components.app_modal import AppModal, ModalAction
from components.sifen_emit import open_sifen_emit_modal
from components.theme import COLORS, SPACING, create_button, create_header, create_text_field
from services.api_client import APIError
from utils.errors import friendly_error
from services.finance_service import finance_service
from i18n import t
from services.pdf_generation.finance import EmployeePaymentGenerator, ExpenseReceiptGenerator, FinanceReportGenerator
from services.pdf_generation.printer_manager import printer_manager
from services.settings_service import settings_service
from utils.formatters import format_currency, format_date


class FinanceView(ft.Container):
    """Tela do modulo financeiro."""

    TRANSACTION_TYPES = ["ENTRADA", "SAIDA"]
    # Categorias válidas por tipo — evita marcar uma saída como entrada.
    CATEGORIES_BY_TYPE = {
        "ENTRADA": ["PAGAMENTO_FATURA", "TAXA_REATIVACAO", "VENDA_MATERIAL", "OUTROS_ENTRADA"],
        "SAIDA": ["SALARIO", "ADIANTAMENTO", "DESPESA_MATERIAL", "DESPESA_SERVICO", "DESPESA_MANUTENCAO", "OUTROS_SAIDA"],
    }
    # Rótulos legíveis (ES) — nada de valores com "_" na interface.
    TYPE_LABELS = {"ENTRADA": "Ingreso", "SAIDA": "Egreso"}
    CATEGORY_LABELS = {
        "PAGAMENTO_FATURA": "Pago de factura",
        "TAXA_REATIVACAO": "Tasa de reactivación",
        "VENDA_MATERIAL": "Venta de material",
        "OUTROS_ENTRADA": "Otros (ingreso)",
        "SALARIO": "Salario",
        "ADIANTAMENTO": "Adelanto",
        "DESPESA_MATERIAL": "Gasto de material",
        "DESPESA_SERVICO": "Gasto de servicio",
        "DESPESA_MANUTENCAO": "Gasto de mantenimiento",
        "OUTROS_SAIDA": "Otros (egreso)",
    }
    EXPENSE_CATEGORIES = ["MATERIAL", "SERVICO", "MANUTENCAO", "OUTROS"]
    EMPLOYEE_ROLES = [
        "PRESIDENTE",
        "TESOUREIRO",
        "SECRETARIO",
        "ADMINISTRADOR",
        "LEITURISTA",
        "TECNICO",
        "COBRADOR",
        "OUTROS",
    ]
    EMPLOYEE_STATUS = ["ATIVO", "INATIVO", "LICENCA"]
    PAYROLL_TYPES = ["SALARIO", "ADIANTAMENTO", "BONUS", "DESCONTO"]
    PAYROLL_STATUS = ["PENDENTE", "PAGO", "CANCELADO"]

    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self._loaded = False
        self._loading_all = False
        self._employees_cache = []
        self._payroll_cache = []
        self._company_cache: dict | None = None
        self.finance_report_generator = FinanceReportGenerator()
        self.expense_receipt_generator = ExpenseReceiptGenerator()
        self.employee_payment_generator = EmployeePaymentGenerator()

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._company_cache = None
        self._run_load_all()

    def _run_in_thread(self, fn):
        if self.page:
            try:
                self.page.run_thread(fn)
                return
            except Exception:
                pass
        fn()

    def _run_with_overlay(self, message: str, fn):
        # O nome ficou por compatibilidade — nao mostramos mais loading_overlay
        # nas cargas de tabela porque o skeleton da DataTable ja cobre o vazio
        # e o overlay ficava sobreposto, com sensacao de bug.
        def worker():
            try:
                fn()
            finally:
                if self.page:
                    try:
                        self.page.update()
                    except Exception:
                        pass
        self._run_in_thread(worker)

    def _run_load_all(self):
        self._run_with_overlay("Carregando financeiro...", self._load_all)

    def _run_load_cash(self):
        self._run_with_overlay("Carregando caixa...", self._load_cash)

    def _run_load_expenses(self, pending_only: bool = False):
        try:
            if not self.expenses_table.data:
                self.expenses_table.show_skeleton(rows=8)
        except Exception:
            pass
        self._run_with_overlay(
            "Carregando despesas...",
            lambda: self._load_expenses(pending_only=pending_only),
        )

    def _run_load_employees(self):
        try:
            if not self.employees_table.data:
                self.employees_table.show_skeleton(rows=6)
        except Exception:
            pass
        self._run_with_overlay("Carregando funcionarios...", self._load_employees)

    def _run_load_payroll(self):
        try:
            if not self.payroll_table.data:
                self.payroll_table.show_skeleton(rows=6)
        except Exception:
            pass
        self._run_with_overlay("Carregando folha...", self._load_payroll)

    def _build(self):
        header = ft.Row(
            [
                create_header(t("finance.title")),
                ft.Container(expand=True),
                create_button("Factura electrónica", icon=ft.Icons.RECEIPT_LONG, on_click=self._open_sifen_modal, primary=False),
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_load_all(), primary=False),
            ]
        )

        self.summary_period = ft.Text("Periodo: -", color=COLORS["text_secondary"], size=12)
        self.summary_entradas = ft.Text("Gs. 0", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=18)
        self.summary_saidas = ft.Text("Gs. 0", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=18)
        self.summary_saldo = ft.Text("Gs. 0", color=COLORS["accent_success"], weight=ft.FontWeight.BOLD, size=18)
        self.report_categories = ft.Column(
            [ft.Text("Sem movimento por categoria no periodo.", color=COLORS["text_muted"], size=12)],
            spacing=SPACING["sm"],
        )

        self.transactions_table = DataTable(
            columns=[
                {"key": "fecha_fmt", "label": t("finance.col.date"), "min_width": 120, "flex": 1, "priority": 2, "align": "center"},
                {"key": "tipo", "label": t("finance.col.type"), "min_width": 90, "flex": 1, "priority": 3, "align": "center"},
                {"key": "categoria", "label": t("finance.col.category"), "min_width": 140, "flex": 2, "priority": 2, "align": "left"},
                {"key": "valor_fmt", "label": t("finance.col.value"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
                {"key": "descripcion", "label": t("finance.col.description"), "min_width": 220, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
            ],
            data=[],
            show_actions=False,
        )

        self.expenses_table = DataTable(
            columns=[
                {"key": "fecha_factura_fmt", "label": t("finance.col.date"), "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
                {"key": "proveedor_nombre", "label": t("finance.col.supplier"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "categoria", "label": t("finance.col.category"), "min_width": 120, "flex": 1, "priority": 3, "align": "left"},
                {"key": "status", "label": t("finance.col.status"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
                {"key": "valor_total_fmt", "label": t("finance.col.value"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
            ],
            data=[],
            on_row_click=self._show_expense_details,
            on_edit=self._pay_expense,
            on_delete=self._show_expense_details,
            show_actions=True,
        )

        self.employees_table = DataTable(
            columns=[
                {"key": "nombre_completo", "label": t("finance.col.name"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "ci", "label": t("finance.col.ci"), "min_width": 100, "flex": 1, "priority": 3, "align": "center"},
                {"key": "cargo", "label": t("finance.col.role"), "min_width": 130, "flex": 1, "priority": 2, "align": "left"},
                {"key": "salario_base_fmt", "label": t("finance.col.salary"), "min_width": 120, "flex": 1, "priority": 2, "align": "right"},
                {"key": "status", "label": t("finance.col.status"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
            ],
            data=[],
            on_edit=self._open_update_employee_modal,
            on_delete=self._open_update_employee_modal,
            show_actions=True,
        )

        self.payroll_table = DataTable(
            columns=[
                {"key": "employee_name", "label": t("finance.col.employee"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "periodo", "label": t("finance.col.period"), "min_width": 90, "flex": 1, "priority": 2, "align": "center"},
                {"key": "tipo", "label": t("finance.col.type"), "min_width": 110, "flex": 1, "priority": 3, "align": "center"},
                {"key": "status", "label": t("finance.col.status"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
                {"key": "valor_liquido_fmt", "label": t("finance.col.net"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
            ],
            data=[],
            on_edit=self._pay_payroll,
            on_delete=self._cancel_payroll,
            show_actions=True,
        )

        tabs = CustomTabs(
            tabs=[
                TabItem(t("finance.tab.cash"), self._build_cash_tab()),
                TabItem(t("finance.tab.expenses"), self._build_expenses_tab()),
                TabItem(t("finance.tab.employees"), self._build_employees_tab()),
                TabItem(t("finance.tab.payroll"), self._build_payroll_tab()),
            ],
            selected_index=0,
        )

        self.loading_overlay = LoadingOverlay(t("finance.loading"))
        self.content = ft.Stack(
            [
                ft.Column([header, tabs], spacing=SPACING["md"], expand=True),
                self.loading_overlay,
            ],
            expand=True,
        )
        self.padding = ft.Padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"])
        self.expand = True

    def _open_sifen_modal(self, e):
        open_sifen_emit_modal(self.page, self.show_snackbar)

    def _build_action_bar(self, controls: list[ft.Control]) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                controls,
                wrap=True,
                spacing=SPACING["sm"],
                run_spacing=SPACING["sm"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border_subtle"]),
            border_radius=12,
        )

    def _build_metric_card(self, title: str, value_control: ft.Control, accent_color: str, icon: str) -> ft.Control:
        return ft.Container(
            expand=True,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=16, color=accent_color),
                            ft.Text(title, color=COLORS["text_secondary"], size=12),
                        ],
                        spacing=6,
                    ),
                    value_control,
                ],
                spacing=6,
                tight=True,
            ),
        )

    def _build_cash_report_panel(self) -> ft.Control:
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.INSIGHTS, size=16, color=COLORS["accent_secondary"]),
                            ft.Text("Relatorio Financeiro", color=COLORS["text_primary"], weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            self.summary_period,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "Consolidado por categoria no periodo atual do caixa.",
                        color=COLORS["text_secondary"],
                        size=12,
                    ),
                    self.report_categories,
                ],
                spacing=SPACING["sm"],
                tight=True,
            ),
        )

    def _build_cash_tab(self) -> ft.Control:
        summary_cards = ft.Row(
            [
                self._build_metric_card("Entradas", self.summary_entradas, COLORS["accent_success"], ft.Icons.NORTH_EAST),
                self._build_metric_card("Saidas", self.summary_saidas, COLORS["accent_error"], ft.Icons.SOUTH_EAST),
                self._build_metric_card("Saldo", self.summary_saldo, COLORS["accent_secondary"], ft.Icons.ACCOUNT_BALANCE_WALLET),
            ],
            spacing=SPACING["sm"],
            run_spacing=SPACING["sm"],
            wrap=False,
        )

        actions = self._build_action_bar(
            [
                create_button("Nova Transacao", icon=ft.Icons.ADD_CARD, on_click=self._open_new_transaction_modal),
                create_button("Imprimir Informe", icon=ft.Icons.PRINT, on_click=lambda e: self._print_finance_report(), primary=False),
                create_button("Atualizar Caixa", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_load_cash(), primary=False),
            ]
        )

        return ft.Column(
            [
                ft.Container(height=SPACING["sm"]),
                summary_cards,
                ft.Container(height=SPACING["sm"]),
                actions,
                ft.Container(height=SPACING["sm"]),
                self._build_cash_report_panel(),
                ft.Container(height=SPACING["sm"]),
                self.transactions_table,
            ],
            expand=True,
        )

    def _build_expenses_tab(self) -> ft.Control:
        actions = self._build_action_bar(
            [
                create_button("Nova Despesa", icon=ft.Icons.RECEIPT, on_click=self._open_new_expense_modal),
                create_button(
                    "Pendentes",
                    icon=ft.Icons.HOURGLASS_TOP,
                    on_click=lambda e: self._run_load_expenses(pending_only=True),
                    primary=False,
                ),
                create_button("Todas", icon=ft.Icons.LIST, on_click=lambda e: self._run_load_expenses(pending_only=False), primary=False),
            ]
        )

        return ft.Column(
            [
                ft.Container(height=SPACING["md"]),
                actions,
                ft.Container(height=SPACING["md"]),
                self.expenses_table,
            ],
            expand=True,
        )

    def _build_employees_tab(self) -> ft.Control:
        actions = self._build_action_bar(
            [
                create_button("Novo Funcionario", icon=ft.Icons.PERSON_ADD, on_click=self._open_new_employee_modal),
            ]
        )

        return ft.Column(
            [
                ft.Container(height=SPACING["md"]),
                actions,
                ft.Container(height=SPACING["md"]),
                self.employees_table,
            ],
            expand=True,
        )

    def _build_payroll_tab(self) -> ft.Control:
        actions = self._build_action_bar(
            [
                create_button("Novo Lancamento", icon=ft.Icons.REQUEST_PAGE, on_click=self._open_new_payroll_modal),
            ]
        )

        return ft.Column(
            [
                ft.Container(height=SPACING["md"]),
                actions,
                ft.Container(height=SPACING["md"]),
                self.payroll_table,
            ],
            expand=True,
        )

    def _load_all(self):
        if self._loading_all:
            return
        self._loading_all = True
        try:
            self._load_cash()
            self._load_expenses()
            self._load_employees()
            self._load_payroll()
        finally:
            self._loading_all = False

    def _load_cash(self):
        try:
            summary = finance_service.get_summary()
            self.summary_period.value = (
                f"Periodo: {summary.get('periodo_inicio', '-')}"
                f" a {summary.get('periodo_fim', '-')}"
            )
            self.summary_entradas.value = format_currency(summary.get("total_entradas", 0), "Gs.")
            self.summary_saidas.value = format_currency(summary.get("total_saidas", 0), "Gs.")
            saldo_periodo = float(summary.get("saldo_periodo", 0) or 0)
            self.summary_saldo.value = format_currency(saldo_periodo, "Gs.")
            self.summary_saldo.color = COLORS["accent_success"] if saldo_periodo >= 0 else COLORS["accent_error"]
            self.summary_period.update()
            self.summary_entradas.update()
            self.summary_saidas.update()
            self.summary_saldo.update()

            by_category = finance_service.get_by_category()
            if not by_category:
                self.report_categories.controls = [
                    ft.Text("Sem movimento por categoria no periodo.", color=COLORS["text_muted"], size=12)
                ]
            else:
                max_total = max(float(item.get("total", 0) or 0) for item in by_category) or 1.0
                rows = []
                for item in by_category[:10]:
                    total = float(item.get("total", 0) or 0)
                    ratio = max(0.0, min(1.0, total / max_total))
                    _cat_raw = str(item.get("categoria", "-"))
                    categoria = self.CATEGORY_LABELS.get(_cat_raw, _cat_raw.replace("_", " ").title())
                    count = int(item.get("count", 0) or 0)
                    rows.append(
                        ft.Container(
                            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                            bgcolor=COLORS["bg_elevated"],
                            border_radius=8,
                            border=ft.Border.all(1, COLORS["border"]),
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(categoria, color=COLORS["text_primary"], size=12),
                                            ft.Container(expand=True),
                                            ft.Text(format_currency(total, "Gs."), color=COLORS["text_primary"], size=12),
                                            ft.Text(f"({count})", color=COLORS["text_secondary"], size=11),
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    ft.ProgressBar(
                                        value=ratio,
                                        bgcolor=COLORS["bg_secondary"],
                                        color=COLORS["accent_secondary"],
                                    ),
                                ],
                                spacing=4,
                                tight=True,
                            ),
                        )
                    )
                self.report_categories.controls = rows
            self.report_categories.update()

            tx = finance_service.list_transactions(limit=200)
            rows = []
            for t in tx:
                row = dict(t)
                row["fecha_fmt"] = format_date(t.get("fecha"), "%d/%m/%Y %H:%M")
                row["valor_fmt"] = format_currency(t.get("valor", 0), "Gs.")
                rows.append(row)
            self.transactions_table.set_data(rows)
        except APIError as err:
            self.transactions_table.set_error(t("finance.load_failed.cash"), on_retry=self._run_load_cash)
            self.show_snackbar(friendly_error(err), error=True)

    def _load_expenses(self, pending_only: bool = False):
        try:
            expenses = finance_service.list_pending_expenses() if pending_only else finance_service.list_expenses(limit=200)
            rows = []
            for e in expenses:
                row = dict(e)
                row["fecha_factura_fmt"] = format_date(e.get("fecha_factura"))
                row["valor_total_fmt"] = format_currency(e.get("valor_total", 0), "Gs.")
                rows.append(row)
            self.expenses_table.set_data(rows)
        except APIError as err:
            self.expenses_table.set_error(t("finance.load_failed.expenses"), on_retry=lambda: self._run_load_expenses(pending_only=pending_only))
            self.show_snackbar(friendly_error(err), error=True)

    def _load_employees(self):
        try:
            employees = finance_service.list_employees()
            self._employees_cache = employees
            rows = []
            for emp in employees:
                row = dict(emp)
                row["salario_base_fmt"] = format_currency(emp.get("salario_base", 0), "Gs.")
                rows.append(row)
            self.employees_table.set_data(rows)
        except APIError as err:
            self.employees_table.set_error(t("finance.load_failed.employees"), on_retry=self._run_load_employees)
            self.show_snackbar(friendly_error(err), error=True)

    def _load_payroll(self):
        try:
            payroll = finance_service.list_payroll(limit=200)
            employee_map = {
                str(emp.get("id")): emp.get("nombre_completo", "-")
                for emp in self._employees_cache
                if emp.get("id")
            }
            rows = []
            for p in payroll:
                row = dict(p)
                row["periodo"] = f"{p.get('mes_referencia', 0):02d}/{p.get('ano_referencia', '')}"
                row["valor_liquido_fmt"] = format_currency(p.get("valor_liquido", 0), "Gs.")
                row["employee_name"] = (
                    p.get("employee_name")
                    or p.get("nombre_funcionario")
                    or employee_map.get(str(p.get("employee_id")))
                    or "-"
                )
                rows.append(row)
            self._payroll_cache = rows
            self.payroll_table.set_data(rows)
        except APIError as err:
            self.payroll_table.set_error(t("finance.load_failed.payroll"), on_retry=self._run_load_payroll)
            self.show_snackbar(friendly_error(err), error=True)

    def _open_new_transaction_modal(self, e):
        def _cat_options(tipo: str):
            return [ft.dropdown.Option(c, self.CATEGORY_LABELS[c]) for c in self.CATEGORIES_BY_TYPE[tipo]]

        tipo_dd = ft.Dropdown(
            label=t("finance.field.type"), width=150, value="ENTRADA",
            options=[ft.dropdown.Option(k, self.TYPE_LABELS[k]) for k in self.TRANSACTION_TYPES],
        )
        categoria_dd = ft.Dropdown(
            label=t("finance.field.category"), width=260,
            value=self.CATEGORIES_BY_TYPE["ENTRADA"][-1],
            options=_cat_options("ENTRADA"),
        )

        def _on_tipo_change(ev):
            tipo = tipo_dd.value or "ENTRADA"
            categoria_dd.options = _cat_options(tipo)
            # Reseta para uma categoria válida do novo tipo (a genérica "Otros").
            categoria_dd.value = self.CATEGORIES_BY_TYPE[tipo][-1]
            try:
                categoria_dd.update()
            except Exception:
                pass

        tipo_dd.on_change = _on_tipo_change

        valor_field = create_text_field(t("finance.field.value"), width=140)
        desc_field = create_text_field(t("finance.field.description"), width=420)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def save_tx(ev):
            try:
                payload = {
                    "tipo": tipo_dd.value,
                    "categoria": categoria_dd.value,
                    "valor": float((valor_field.value or "").strip().replace(",", ".")),
                    "descripcion": (desc_field.value or "").strip(),
                }
                finance_service.create_transaction(payload)
                if _modal_ref:
                    _modal_ref[0].close()
                self.show_snackbar(t("finance.tx.saved"))
                self._run_load_cash()
            except ValueError:
                error_text.value = t("finance.err.invalid_value")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                detail = str(err.detail)
                if "cargo" in detail.lower() and "enum" in detail.lower():
                    error_text.value = t("finance.err.role_not_supported")
                else:
                    error_text.value = detail
                error_text.visible = True
                error_text.update()

        _modal_ref: list[AppModal] = []
        modal = AppModal(
            page=self.page,
            title=t("finance.tx.title"),
            content=ft.Column([ft.Row([tipo_dd, categoria_dd]), ft.Row([valor_field]), desc_field, error_text], spacing=10, tight=True),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal.close()),
                ModalAction(t("common.save"), on_click=save_tx, primary=True),
            ],
            width_pct=0.4,
        )
        _modal_ref.append(modal)
        modal.open()

    def _open_new_expense_modal(self, e):
        proveedor_field = create_text_field(t("finance.expense.supplier"), width=260)
        ruc_field = create_text_field(t("finance.expense.ruc"), width=160)
        factura_field = create_text_field(t("finance.expense.invoice_no"), width=160)
        fecha_factura_field = create_text_field(t("finance.expense.invoice_date"), width=196, value=datetime.now().strftime("%Y-%m-%d"))
        fecha_venc_field = create_text_field(t("finance.expense.due"), width=196)
        categoria_dd = ft.Dropdown(
            label=t("finance.field.category"),
            width=180,
            value="MATERIAL",
            options=[ft.dropdown.Option(x) for x in self.EXPENSE_CATEGORIES],
        )
        obs_field = create_text_field(t("finance.expense.observation"), width=420)
        total_text = ft.Text("Total: Gs. 0", size=13, weight=ft.FontWeight.BOLD, color=COLORS["accent_secondary"])
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        item_rows_col = ft.Column(spacing=6, tight=True)

        def _recalc_total(_=None):
            total = 0.0
            for row_ctrl in item_rows_col.controls:
                try:
                    fields = row_ctrl.content.controls
                    qtd = float((fields[0].value or "1").replace(",", "."))
                    price = float((fields[1].value or "0").replace(",", "."))
                    total += qtd * price
                except Exception:
                    pass
            total_text.value = f"Total: Gs. {total:,.0f}".replace(",", ".")
            try:
                total_text.update()
            except Exception:
                pass

        def _make_item_row():
            qtd_f = create_text_field(t("finance.expense.item_qty"), width=70, value="1")
            price_f = create_text_field(t("finance.expense.item_price"), width=120)
            desc_f = create_text_field(t("finance.expense.item_desc"), width=210)
            qtd_f.on_change = _recalc_total
            price_f.on_change = _recalc_total

            def remove_row(ev, row_ref=None):
                if len(item_rows_col.controls) > 1:
                    item_rows_col.controls.remove(row_ref)
                    _recalc_total()
                    try:
                        item_rows_col.update()
                    except Exception:
                        pass

            row = ft.Container(
                content=ft.Row([qtd_f, price_f, desc_f,
                    ft.IconButton(ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_color=COLORS["accent_error"],
                                  icon_size=20, tooltip=t("finance.expense.remove_item"),
                                  on_click=lambda ev: remove_row(ev, row))],
                    spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            row.content.controls[-1].on_click = lambda ev, r=row: remove_row(ev, r)
            return row

        def add_item_row(ev):
            item_rows_col.controls.append(_make_item_row())
            try:
                item_rows_col.update()
            except Exception:
                pass

        item_rows_col.controls.append(_make_item_row())

        add_btn = ft.TextButton(
            content=ft.Row([ft.Icon(ft.Icons.ADD, size=16), ft.Text("Adicionar item", size=13)], spacing=4),
            on_click=add_item_row,
        )

        def save_expense(ev):
            try:
                items = []
                for row_ctrl in item_rows_col.controls:
                    fields = row_ctrl.content.controls
                    desc = (fields[2].value or "").strip()
                    qtd = int(float((fields[0].value or "1").strip().replace(",", ".")))
                    price = float((fields[1].value or "").strip().replace(",", "."))
                    if desc:
                        items.append({"descripcion": desc, "cantidad": qtd, "precio_unitario": price})
                if not items:
                    error_text.value = t("finance.err.add_item")
                    error_text.visible = True
                    error_text.update()
                    return
                payload = {
                    "proveedor_nombre": (proveedor_field.value or "").strip(),
                    "proveedor_ruc": (ruc_field.value or "").strip() or None,
                    "numero_factura": (factura_field.value or "").strip() or None,
                    "fecha_factura": (fecha_factura_field.value or "").strip(),
                    "fecha_vencimiento": (fecha_venc_field.value or "").strip() or None,
                    "categoria": categoria_dd.value,
                    "items": items,
                    "observacion": (obs_field.value or "").strip() or None,
                }
                finance_service.create_expense(payload)
                if _modal_ref_exp:
                    _modal_ref_exp[0].close()
                self.show_snackbar(t("finance.expense.created"))
                self._run_load_expenses()
                self._run_load_cash()
            except ValueError:
                error_text.value = t("finance.err.qty_price")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_exp: list[AppModal] = []
        modal_exp = AppModal(
            page=self.page,
            title=t("finance.expense.title"),
            content=ft.Column(
                [
                    ft.Row([proveedor_field, ruc_field], spacing=12),
                    ft.Row([factura_field, categoria_dd], spacing=12),
                    ft.Row([fecha_factura_field, fecha_venc_field], spacing=12),
                    ft.Divider(height=1, color=COLORS["border"]),
                    ft.Row([
                        ft.Text("Itens", size=13, weight=ft.FontWeight.BOLD, color=COLORS["text_secondary"]),
                        ft.Container(expand=True),
                        total_text,
                    ]),
                    item_rows_col,
                    add_btn,
                    ft.Divider(height=1, color=COLORS["border"]),
                    obs_field,
                    error_text,
                ],
                spacing=10,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_exp.close()),
                ModalAction(t("common.save"), on_click=save_expense, primary=True),
            ],
            width_pct=0.5,
        )
        _modal_ref_exp.append(modal_exp)
        modal_exp.open()

    def _show_expense_details(self, row: dict):
        items = row.get("items", [])
        item_controls = []
        for item in items:
            item_controls.append(
                ft.Row(
                    [
                        ft.Text(item.get("descripcion", "-"), width=210),
                        ft.Text(f"x{item.get('cantidad', 1)}", width=60),
                        ft.Text(format_currency(item.get("subtotal", 0), "Gs.")),
                    ],
                    spacing=8,
                )
            )
        if not item_controls:
            item_controls = [ft.Text("Sem itens.", color=COLORS["text_muted"])]

        modal = AppModal(
            page=self.page,
            title=t("finance.expense.detail_title"),
            content=ft.Column(
                [
                    ft.Text(f"Fornecedor: {row.get('proveedor_nombre', '-')}"),
                    ft.Text(f"Status: {row.get('status', '-')}"),
                    ft.Text(f"Valor: {format_currency(row.get('valor_total', 0), 'Gs.')}"),
                    ft.Divider(),
                    ft.Text("Itens", weight=ft.FontWeight.BOLD),
                    ft.Column(item_controls, spacing=4),
                ],
                spacing=8,
            ),
            actions=[
                ModalAction("Imprimir", on_click=lambda e: self._print_expense_receipt(row)),
                ModalAction(t("common.close"), on_click=lambda e: modal.close()),
            ],
            width_pct=0.4,
        )
        modal.open()

    def _pay_expense(self, row: dict):
        if row.get("status") != "PENDENTE":
            self.show_snackbar(t("finance.only_pending_payable"))
            return

        obs_field = create_text_field(t("finance.pay_obs"), width=360)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def confirm_pay(ev):
            try:
                paid_expense = finance_service.pay_expense(row["id"], (obs_field.value or "").strip() or None)
                if _modal_ref_pay:
                    _modal_ref_pay[0].close()
                self.show_snackbar(t("finance.expense.paid"))
                self._print_expense_receipt(paid_expense)
                self._run_load_expenses()
                self._run_load_cash()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_pay: list[AppModal] = []
        modal_pay = AppModal(
            page=self.page,
            title=t("finance.pay_expense_title"),
            content=ft.Column(
                [
                    ft.Text(f"Fornecedor: {row.get('proveedor_nombre', '-')}"),
                    ft.Text(f"Valor: {format_currency(row.get('valor_total', 0), 'Gs.')}"),
                    obs_field,
                    error_text,
                ],
                spacing=8,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal_pay.close()),
                ModalAction(t("finance.btn.pay"), on_click=confirm_pay, primary=True),
            ],
            width_pct=0.35,
        )
        _modal_ref_pay.append(modal_pay)
        modal_pay.open()

    def _open_new_employee_modal(self, e):
        W = 200
        name_field = create_text_field(t("finance.employee.name"), width=W)
        ci_field = create_text_field(t("finance.employee.ci"), width=W)
        role_dd = ft.Dropdown(label=t("finance.employee.role"), width=W, value="OUTROS", options=[ft.dropdown.Option(x) for x in self.EMPLOYEE_ROLES])
        salary_field = create_text_field(t("finance.employee.salary_base"), width=W)
        phone_field = create_text_field(t("finance.employee.phone"), width=W)
        ingreso_field = create_text_field(t("finance.employee.ingreso"), width=W, value=datetime.now().strftime("%Y-%m-%d"))
        address_field = create_text_field(t("finance.employee.address"), width=W * 2 + 16)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def save_employee(ev):
            try:
                payload = {
                    "nombre_completo": (name_field.value or "").strip(),
                    "ci": (ci_field.value or "").strip(),
                    "telefono": (phone_field.value or "").strip() or None,
                    "direccion": (address_field.value or "").strip() or None,
                    "cargo": role_dd.value,
                    "salario_base": float((salary_field.value or "").strip().replace(",", ".")),
                    "fecha_ingreso": (ingreso_field.value or "").strip(),
                }
                finance_service.create_employee(payload)
                if _modal_ref_emp:
                    _modal_ref_emp[0].close()
                self.show_snackbar(t("finance.employee.created"))
                self._run_load_employees()
            except ValueError:
                error_text.value = t("finance.err.invalid_salary")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_emp: list[AppModal] = []
        modal_emp = AppModal(
            page=self.page,
            title=t("finance.employee.title"),
            content=ft.Column(
                [
                    ft.Row([name_field, ci_field], spacing=16),
                    ft.Row([role_dd, salary_field], spacing=16),
                    ft.Row([phone_field, ingreso_field], spacing=16),
                    address_field,
                    error_text,
                ],
                spacing=12,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_emp.close()),
                ModalAction(t("common.save"), on_click=save_employee, primary=True),
            ],
            width_pct=0.38,
        )
        _modal_ref_emp.append(modal_emp)
        modal_emp.open()

    def _open_update_employee_modal(self, row: dict):
        W = 200
        name_field = create_text_field("Nome completo", width=W, value=row.get("nombre_completo", ""))
        ci_field = create_text_field("CI", width=W, value=row.get("ci", ""))
        role_dd = ft.Dropdown(label="Cargo", width=W, value=row.get("cargo"), options=[ft.dropdown.Option(x) for x in self.EMPLOYEE_ROLES])
        salary_field = create_text_field("Salário base", width=W, value=str(row.get("salario_base", "")))
        phone_field = create_text_field("Telefone", width=W, value=row.get("telefone", "") or "")
        status_dd = ft.Dropdown(label="Status", width=W, value=row.get("status"), options=[ft.dropdown.Option(x) for x in self.EMPLOYEE_STATUS])
        address_field = create_text_field("Endereço", width=W * 2 + 16, value=row.get("direccion", "") or "")
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def save_update(ev):
            try:
                payload = {
                    "nombre_completo": (name_field.value or "").strip() or None,
                    "ci": (ci_field.value or "").strip() or None,
                    "telefono": (phone_field.value or "").strip() or None,
                    "direccion": (address_field.value or "").strip() or None,
                    "cargo": role_dd.value,
                    "status": status_dd.value,
                    "salario_base": float((salary_field.value or "").strip().replace(",", ".")),
                }
                finance_service.update_employee(row["id"], payload)
                if _modal_ref_upd:
                    _modal_ref_upd[0].close()
                self.show_snackbar(t("finance.employee.updated"))
                self._run_load_employees()
            except ValueError:
                error_text.value = t("finance.err.invalid_salary")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_upd: list[AppModal] = []
        modal_upd = AppModal(
            page=self.page,
            title=f"Editar — {row.get('nombre_completo', '')}",
            content=ft.Column(
                [
                    ft.Row([name_field, ci_field], spacing=16),
                    ft.Row([role_dd, salary_field], spacing=16),
                    ft.Row([phone_field, status_dd], spacing=16),
                    address_field,
                    error_text,
                ],
                spacing=12,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_upd.close()),
                ModalAction(t("common.save"), on_click=save_update, primary=True),
            ],
            width_pct=0.38,
        )
        _modal_ref_upd.append(modal_upd)
        modal_upd.open()

    def _open_new_payroll_modal(self, e):
        if not self._employees_cache:
            self.show_snackbar(t("finance.payroll.need_employees"), error=True)
            return

        active_employees = [emp for emp in self._employees_cache if emp.get("status") == "ATIVO"]
        employee_map = {str(emp.get("id")): emp for emp in active_employees if emp.get("id")}
        if not active_employees:
            self.show_snackbar(t("finance.payroll.no_active"), error=True)
            return

        employee_dd = ft.Dropdown(
            label=t("finance.payroll.field_employee"),
            width=290,
            value=str(active_employees[0].get("id")),
            options=[ft.dropdown.Option(emp["id"], emp["nombre_completo"]) for emp in active_employees],
        )
        tipo_dd = ft.Dropdown(label=t("finance.field.type"), width=150, value="SALARIO", options=[ft.dropdown.Option(x) for x in self.PAYROLL_TYPES])
        mes_field = create_text_field(t("finance.payroll.month"), width=80, value=str(datetime.now().month))
        ano_field = create_text_field(t("finance.payroll.year"), width=100, value=str(datetime.now().year))
        valor_field = create_text_field(t("finance.payroll.base_value"), width=130)
        desconto_field = create_text_field(t("finance.payroll.discounts"), width=130, value="0")
        obs_field = create_text_field(t("finance.payroll.observation"), width=420)
        salary_hint = ft.Text("Salário base: -", color=COLORS["text_secondary"], size=12)
        adiantamento_alert = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=COLORS["accent_warning"], size=16),
                ft.Text("", color=COLORS["accent_warning"], size=12),
            ], spacing=6),
            visible=False,
            bgcolor=f"{COLORS['accent_warning']}22",
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        )
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def _safe_control_update(control: ft.Control):
            try:
                control.update()
            except Exception:
                pass

        def _check_adiantamento(emp_id: str):
            total = sum(
                float(p.get("valor_liquido", 0) or 0)
                for p in (self._payroll_cache or [])
                if str(p.get("employee_id")) == emp_id
                and p.get("tipo") == "ADIANTAMENTO"
                and p.get("status") == "PAGO"
            )
            paid_discounts = sum(
                float(p.get("valor_liquido", 0) or 0)
                for p in (self._payroll_cache or [])
                if str(p.get("employee_id")) == emp_id
                and p.get("tipo") == "DESCONTO"
                and p.get("status") != "CANCELADO"
            )
            pendente = total - paid_discounts
            if pendente > 0:
                adiantamento_alert.content.controls[1].value = (
                    f"Funcionário tem adiantamento não descontado: {format_currency(pendente, 'Gs.')}"
                )
                adiantamento_alert.visible = True
            else:
                adiantamento_alert.visible = False
            _safe_control_update(adiantamento_alert)

        def _apply_default_salary(_=None):
            emp = employee_map.get(str(employee_dd.value or ""))
            salary = float(emp.get("salario_base", 0) or 0) if emp else 0.0
            salary_hint.value = f"Salário base: {format_currency(salary, 'Gs.')}"
            if tipo_dd.value == "SALARIO":
                valor_field.value = str(salary)
            _safe_control_update(salary_hint)
            _safe_control_update(valor_field)
            if employee_dd.value:
                _check_adiantamento(str(employee_dd.value))

        employee_dd.on_change = _apply_default_salary
        tipo_dd.on_change = _apply_default_salary
        _apply_default_salary()

        def save_payroll(ev):
            try:
                payload = {
                    "employee_id": employee_dd.value,
                    "tipo": tipo_dd.value,
                    "mes_referencia": int((mes_field.value or "").strip()),
                    "ano_referencia": int((ano_field.value or "").strip()),
                    "valor_base": float((valor_field.value or "").strip().replace(",", ".")),
                    "descontos": float((desconto_field.value or "0").strip().replace(",", ".")),
                    "observacion": (obs_field.value or "").strip() or None,
                }
                finance_service.create_payroll(payload)
                if _modal_ref_pr:
                    _modal_ref_pr[0].close()
                self.show_snackbar(t("finance.payroll.created"))
                self._run_load_payroll()
            except ValueError:
                error_text.value = t("finance.err.invalid_numeric")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_pr: list[AppModal] = []
        modal_pr = AppModal(
            page=self.page,
            title=t("finance.payroll.title"),
            content=ft.Column(
                [
                    ft.Row([employee_dd, tipo_dd], spacing=8),
                    salary_hint,
                    adiantamento_alert,
                    ft.Row([mes_field, ano_field, valor_field, desconto_field], spacing=8),
                    obs_field,
                    error_text,
                ],
                spacing=10,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_pr.close()),
                ModalAction(t("common.save"), on_click=save_payroll, primary=True),
            ],
            width_pct=0.45,
        )
        _modal_ref_pr.append(modal_pr)
        modal_pr.open()

    def _pay_payroll(self, row: dict):
        if row.get("status") != "PENDENTE":
            self.show_snackbar(t("finance.only_pending_payroll"))
            return

        obs_field = create_text_field(t("finance.payroll.pay_obs"), width=360)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def confirm_pay(ev):
            try:
                paid_payroll = finance_service.pay_payroll(row["id"], (obs_field.value or "").strip() or None)
                if _modal_ref_ppr:
                    _modal_ref_ppr[0].close()
                self.show_snackbar(t("finance.payroll.paid"))
                self._print_employee_payment(paid_payroll)
                self._run_load_payroll()
                self._run_load_cash()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_ppr: list[AppModal] = []
        modal_ppr = AppModal(
            page=self.page,
            title=t("finance.pay_payroll_title"),
            content=ft.Column(
                [
                    ft.Text(f"Funcionario: {row.get('employee_name', '-')}"),
                    ft.Text(f"Liquido: {format_currency(row.get('valor_liquido', 0), 'Gs.')}"),
                    obs_field,
                    error_text,
                ],
                spacing=8,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal_ppr.close()),
                ModalAction(t("finance.btn.pay"), on_click=confirm_pay, primary=True),
            ],
            width_pct=0.35,
        )
        _modal_ref_ppr.append(modal_ppr)
        modal_ppr.open()

    def _cancel_payroll(self, row: dict):
        if row.get("status") != "PENDENTE":
            self.show_snackbar(t("finance.only_pending_cancel"))
            return

        modal_cancel: AppModal = None  # type: ignore

        def confirm_cancel(ev):
            try:
                finance_service.cancel_payroll(row["id"])
                modal_cancel.close()
                self.show_snackbar(t("finance.payroll.canceled"))
                self._run_load_payroll()
            except APIError as err:
                self.show_snackbar(str(err.detail), error=True)

        modal_cancel = AppModal(
            page=self.page,
            title=t("finance.cancel_title"),
            content=ft.Text("Confirma cancelamento deste lancamento de folha?"),
            actions=[
                ModalAction(t("finance.btn.back"), on_click=lambda e: modal_cancel.close()),
                ModalAction(t("finance.btn.cancel_entry"), on_click=confirm_cancel, danger=True),
            ],
            width_pct=0.35,
        )
        modal_cancel.open()

    def _get_company_info(self) -> dict:
        if self._company_cache is not None:
            return self._company_cache
        try:
            self._company_cache = settings_service.get()
        except Exception:
            self._company_cache = {}
        return self._company_cache

    def _print_finance_report(self):
        try:
            summary = finance_service.get_summary()
            transactions = finance_service.list_transactions(limit=200)
            report_payload = {
                "period": {
                    "start": summary.get("periodo_inicio"),
                    "end": summary.get("periodo_fim"),
                },
                "period_label": f"Periodo: {summary.get('periodo_inicio', '-')} a {summary.get('periodo_fim', '-')}",
                "summary": summary,
                "movements": transactions,
                "company": self._get_company_info(),
            }
            pdf = self.finance_report_generator.generate(report_payload)
            period_hint = str(summary.get("periodo_inicio", "periodo")).replace("-", "_")
            printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"finance_report_{period_hint}")
            self.show_snackbar(t("finance.print.report_sent"))
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)

    def _print_expense_receipt(self, expense: dict):
        try:
            payload = dict(expense)
            payload["company"] = self._get_company_info()
            pdf = self.expense_receipt_generator.generate(payload)
            expense_id = str(expense.get("id", "expense"))[:12]
            printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"expense_{expense_id}")
            self.show_snackbar(t("finance.print.expense_voucher_sent"))
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)

    def _print_employee_payment(self, payroll: dict):
        try:
            if not self._employees_cache:
                try:
                    self._employees_cache = finance_service.list_employees()
                except Exception:
                    self._employees_cache = []
            treasurer = next(
                (
                    emp
                    for emp in self._employees_cache
                    if emp.get("status") == "ATIVO" and str(emp.get("cargo", "")).upper() == "TESOUREIRO"
                ),
                None,
            )
            president = next(
                (
                    emp
                    for emp in self._employees_cache
                    if emp.get("status") == "ATIVO" and str(emp.get("cargo", "")).upper() == "PRESIDENTE"
                ),
                None,
            )
            administrators = [
                emp
                for emp in self._employees_cache
                if emp.get("status") == "ATIVO" and str(emp.get("cargo", "")).upper() == "ADMINISTRADOR"
            ]
            if not treasurer and administrators:
                treasurer = administrators[0]
            if not president and administrators:
                president = administrators[1] if len(administrators) > 1 else administrators[0]
            payload = dict(payroll)
            if not payload.get("employee_name"):
                employee_map = {
                    str(emp.get("id")): emp.get("nombre_completo", "-")
                    for emp in self._employees_cache
                    if emp.get("id")
                }
                payload["employee_name"] = employee_map.get(str(payroll.get("employee_id")), "-")
            payload["tesoureiro_nome"] = treasurer.get("nombre_completo") if treasurer else None
            payload["presidente_nome"] = president.get("nombre_completo") if president else None
            payload["company"] = self._get_company_info()
            pdf = self.employee_payment_generator.generate(payload)
            payroll_id = str(payroll.get("id", "payroll"))[:12]
            printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"payroll_{payroll_id}")
            self.show_snackbar(t("finance.print.payroll_voucher_sent"))
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)
