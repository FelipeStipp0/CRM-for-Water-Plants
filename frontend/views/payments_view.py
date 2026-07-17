"""
WMApp Frontend - Payments View
Tela de caixa para recebimento e historico de pagamentos.
"""

from datetime import datetime

import flet as ft

from components.data_table import DataTable
from components.loading_overlay import LoadingOverlay
from components.pagination import Pagination
from components.app_modal import AppModal, ModalAction
from components.theme import (
    COLORS,
    FONTS,
    SPACING,
    create_button,
    create_header,
    create_money_field,
    create_text_field,
    get_status_color,
)
from config.local_settings import get_api_url, get_invoice_print_format
from services.api_client import APIError
from utils.errors import friendly_error
from services.client_service import client_service
from services.cutoff_service import cutoff_service
from services.invoice_service import invoice_service
from services.payment_service import payment_service
from i18n import t
from services.pdf_generation.invoices import InvoiceA4Generator, InvoiceP80Generator
from services.pdf_generation.notifications import ReactivationRequestGenerator
from services.pdf_generation.printer_manager import printer_manager
from services.pdf_generation.receipts import PaymentReceiptP80Generator
from services.settings_service import settings_service
from utils.formatters import format_currency, format_date


class PaymentsView(ft.Container):
    """Tela de pagamentos/caixa."""

    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self._loaded = False
        self._data = []
        self._loading_payments = False
        self._page_size = 100
        self._client_name_cache: dict[str, str] = {}
        self._company_cache: dict | None = None
        self.last_payment_result = None
        self.receipt_generator = PaymentReceiptP80Generator()
        self.invoice_generator = InvoiceA4Generator()
        self.invoice_p80_generator = InvoiceP80Generator()
        self.reactivation_generator = ReactivationRequestGenerator()

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._company_cache = None
        self._run_load_payments()

    def _on_page_change(self, skip: int):
        self._run_load_payments(skip=skip)

    def _run_load_payments(self, skip: int = 0):
        if not getattr(self, "_data", None):
            try:
                self.table.show_skeleton(rows=10)
            except Exception as err:
                print(f"[PaymentsView] skeleton_error err={err}")
        if self.page:
            try:
                self.page.run_thread(lambda: self._load_payments(skip))
                return
            except Exception:
                pass
        self._load_payments(skip)

    def _build(self):
        header = ft.Row(
            [
                create_header(t("payments.title")),
                ft.Container(expand=True),
                create_button("Novo Recebimento", icon=ft.Icons.POINT_OF_SALE, on_click=self._open_new_payment_modal),
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: (self.pagination.reset(), self._run_load_payments(skip=0)), primary=False),
            ]
        )

        self.table = DataTable(
            columns=[
                {"key": "fecha_pago_fmt", "label": t("payments.col.date"), "min_width": 130, "flex": 1, "priority": 1, "align": "center"},
                {"key": "cliente_nome", "label": t("payments.col.client"), "min_width": 220, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "metodo", "label": t("payments.col.method"), "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
                {"key": "valor_total_fmt", "label": t("payments.col.value"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
                {"key": "invoices_count", "label": t("payments.col.invoices"), "min_width": 80, "flex": 1, "priority": 2, "align": "center"},
            ],
            data=[],
            on_row_click=self._show_payment_details_from_row,
            show_actions=False,
        )
        self.loading_overlay = LoadingOverlay(t("payments.loading"))
        self.pagination = Pagination(page_size=self._page_size, on_change=self._on_page_change)

        # Painel oculto por default — so aparece depois que um pagamento for
        # processado nesta sessao (mostra resumo do recibo).
        self.last_receipt = ft.Container(
            content=ft.Text(""),
            padding=12,
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=8,
            visible=False,
        )

        self.content = ft.Column(
            [
                header,
                self.last_receipt,
                ft.Stack(
                    [
                        self.table,
                        self.loading_overlay,
                    ],
                    expand=True,
                ),
                self.pagination,
            ],
            spacing=SPACING["sm"],
            expand=True,
        )
        self.padding = ft.Padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"])
        self.expand = True

    def _load_payments(self, skip: int = 0):
        if self._loading_payments:
            return
        self._loading_payments = True
        try:
            payments, total = payment_service.list_paged(skip=skip, limit=self._page_size)
            self._resolve_payment_client_names(payments)
            self._data = [self._decorate_payment(p) for p in payments]
            self.table.set_data(self._data)
            self.pagination.update_state(current_page=skip // self._page_size, total_items=total)
        except APIError as err:
            self.table.set_error(t("payments.load_failed"), on_retry=lambda: self._run_load_payments(skip))
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            self.table.set_error(t("payments.load_failed_unexpected"), on_retry=lambda: self._run_load_payments(skip))
            self.show_snackbar(friendly_error(err), error=True)
        finally:
            self._loading_payments = False
            if self.page:
                try:
                    self.page.update()
                except Exception:
                    pass

    def _extract_client_id(self, payment: dict) -> str:
        raw_id = payment.get("client_id")
        if raw_id:
            return str(raw_id).strip()
        client_obj = payment.get("client")
        if isinstance(client_obj, dict):
            return str(
                client_obj.get("id")
                or client_obj.get("$id")
                or client_obj.get("_id")
                or ""
            ).strip()
        return ""

    def _resolve_payment_client_names(self, payments: list[dict]):
        missing_ids: set[str] = set()
        for payment in payments:
            if (
                payment.get("client_name")
                or payment.get("client_nombre")
                or payment.get("nombre_cliente")
                or payment.get("cliente_nome")
                or (isinstance(payment.get("client"), dict) and payment.get("client", {}).get("nombre_completo"))
            ):
                continue
            client_id = self._extract_client_id(payment)
            if client_id and client_id not in self._client_name_cache:
                missing_ids.add(client_id)

        for client_id in missing_ids:
            try:
                client = client_service.get(client_id)
                name = client.get("nombre_completo") or "-"
                self._client_name_cache[client_id] = name
            except Exception:
                self._client_name_cache[client_id] = "-"

    def _decorate_payment(self, p: dict) -> dict:
        row = dict(p)
        client_id = self._extract_client_id(p)
        client_obj = p.get("client") if isinstance(p.get("client"), dict) else {}
        row["cliente_nome"] = (
            p.get("client_name")
            or p.get("client_nombre")
            or p.get("nombre_cliente")
            or p.get("cliente_nome")
            or client_obj.get("nombre_completo")
            or self._client_name_cache.get(client_id)
            or "-"
        )
        row["fecha_pago_fmt"] = format_date(p.get("fecha_pago"), "%d/%m/%Y %H:%M")
        row["valor_total_fmt"] = format_currency(p.get("valor_total", 0), "Gs.")
        return row

    # ---- helpers visuais do modal de cobro ---------------------------------
    @staticmethod
    def _money(v) -> str:
        return format_currency(v or 0, "Gs.")

    @staticmethod
    def _section(num: int, title: str, body: ft.Control, ref: ft.Container | None = None) -> ft.Container:
        """Card de seção numerada (passo a passo) para o modal de cobro."""
        head = ft.Row(
            [
                ft.Container(
                    content=ft.Text(str(num), color=COLORS["text_primary"], weight=ft.FontWeight.BOLD, size=13),
                    width=26, height=26, border_radius=13,
                    bgcolor=COLORS["accent_secondary"], alignment=ft.Alignment(0, 0),
                ),
                ft.Text(title, size=FONTS["size_base"], weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ],
            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        container = ref if ref is not None else ft.Container()
        container.content = ft.Column([head, body], spacing=SPACING["sm"])
        container.padding = SPACING["md"]
        container.bgcolor = COLORS["bg_surface"]
        container.border_radius = 12
        container.border = ft.Border.all(1, COLORS["border"])
        return container

    @staticmethod
    def _status_chip(status: str) -> ft.Container:
        color = get_status_color(status or "-")
        return ft.Container(
            content=ft.Text(status or "-", size=FONTS["size_xs"], weight=ft.FontWeight.BOLD, color=color),
            bgcolor=ft.Colors.with_opacity(0.16, color),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
            padding=ft.Padding.symmetric(horizontal=10, vertical=3),
            border_radius=20,
        )

    def _open_new_payment_modal(self, e):
        # Estado mutável compartilhado entre os callbacks do modal.
        selected = {"id": None, "data": None}
        state = {"debt": 0.0, "facturas": 0, "taxa": 0.0, "cortado": False}
        result_clients: list[dict] = []

        def _u(control: ft.Control):
            try:
                control.update()
            except Exception:
                pass

        def _bg(fn):
            """Roda fn fora da thread da UI para não congelar a janela durante
            chamadas remotas (busca/seleção fazem várias idas à API)."""
            if self.page:
                try:
                    self.page.run_thread(fn)
                    return
                except Exception:
                    pass
            fn()

        # ---------- SECCIÓN 1 — Buscar cliente ----------
        invoice_number_field = create_text_field(t("payments.field.invoice_number"), width=200)
        invoice_search_hint = ft.Text("", color=COLORS["text_muted"], size=12, visible=False)
        client_search = create_text_field(t("payments.field.client_search"), width=420)
        search_hint = ft.Text(t("payments.search_hint"),
                              color=COLORS["text_muted"], size=12)
        search_results = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=150)

        # ---------- SECCIÓN 2 — Cliente y deuda ----------
        client_name_text = ft.Text("", size=FONTS["size_lg"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        client_status_chip = ft.Container(visible=False)
        client_sub_text = ft.Text("", size=12, color=COLORS["text_secondary"])
        debt_value_text = ft.Text("Gs. 0", size=FONTS["size_2xl"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        debt_count_text = ft.Text("", size=12, color=COLORS["text_secondary"])
        cut_warning = ft.Container(visible=False)
        invoice_breakdown = ft.Column(
            controls=[], spacing=3, height=110, scroll=ft.ScrollMode.AUTO,
        )
        sponsor_info = ft.Text("", color=COLORS["accent_secondary"], size=12, visible=False)
        apply_subsidy_cb = ft.Checkbox(label=t("payments.apply_subsidy"), value=False, visible=False)

        section2_body = ft.Column(
            [
                ft.Row(
                    [client_name_text, ft.Container(width=8), client_status_chip],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True,
                ),
                client_sub_text,
                ft.Divider(height=1, color=COLORS["border"]),
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("SALDO PENDIENTE", size=11, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                                debt_value_text,
                                debt_count_text,
                            ],
                            spacing=2,
                        ),
                    ],
                ),
                cut_warning,
                sponsor_info,
                apply_subsidy_cb,
                ft.Text("Facturas pendientes", size=11, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                invoice_breakdown,
            ],
            spacing=SPACING["sm"],
        )
        section2 = ft.Container(visible=False)
        self._section(2, t("payments.section.client_debt"), section2_body, ref=section2)

        # ---------- SECCIÓN 3 — Cobro ----------
        method_dd = ft.Dropdown(
            label=t("payments.field.method"), width=200, value="EFECTIVO",
            options=[ft.dropdown.Option("EFECTIVO"), ft.dropdown.Option("TRANSFERENCIA"), ft.dropdown.Option("CHEQUE")],
        )
        amount_field = create_money_field(t("payments.field.amount"), width=220)
        receiver_field = create_text_field(t("payments.field.receiver"), width=200)
        obs_field = create_text_field(
            t("payments.field.observation"),
            width=430,
            multiline=True,
            min_lines=2,
            max_lines=3,
        )
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        preview_total = ft.Text("Gs. 0", size=FONTS["size_lg"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        preview_lines = ft.Column([], spacing=2)
        preview_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(t("payments.preview.title"), size=11, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                    preview_lines,
                ],
                spacing=6,
            ),
            padding=SPACING["md"], bgcolor=COLORS["bg_elevated"],
            border=ft.Border.all(1, COLORS["border"]), border_radius=10,
        )

        section3_body = ft.Column(
            [
                ft.Row([method_dd, amount_field], spacing=SPACING["sm"], wrap=True),
                ft.Row([receiver_field], spacing=SPACING["sm"]),
                obs_field,
                preview_panel,
                error_text,
            ],
            spacing=SPACING["sm"],
        )
        section3 = ft.Container(visible=False)
        self._section(3, t("payments.section.charge"), section3_body, ref=section3)

        # ---------- lógica ----------
        def _parse_amount(raw: str):
            raw = (raw or "").strip().replace(".", "").replace(",", ".")
            if not raw:
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        def update_preview(ev=None):
            amount = _parse_amount(amount_field.value)
            debt = state["debt"]
            taxa = state["taxa"] if state["cortado"] else 0.0
            lines: list[ft.Control] = []

            def line(lbl, val, *, strong=False, color=None, sign=""):
                return ft.Row(
                    [
                        ft.Text(lbl, size=12, color=color or COLORS["text_secondary"],
                                weight=ft.FontWeight.BOLD if strong else ft.FontWeight.NORMAL),
                        ft.Container(expand=True),
                        ft.Text(f"{sign}{self._money(val)}", size=12, color=color or COLORS["text_primary"],
                                weight=ft.FontWeight.BOLD if strong else ft.FontWeight.NORMAL),
                    ],
                )

            lines.append(line(t("payments.preview.debt"), debt))
            if state["cortado"]:
                lines.append(line(t("payments.preview.reactivation"), taxa, color=COLORS["accent_warning"]))
            total_cobrar = debt + taxa
            lines.append(ft.Divider(height=1, color=COLORS["border"]))
            lines.append(line(t("payments.preview.total"), total_cobrar, strong=True))

            if amount is not None:
                lines.append(ft.Container(height=4))
                lines.append(line(t("payments.preview.received"), amount, color=COLORS["accent_secondary"]))
                aplicado = min(amount, debt)
                restante = max(0.0, debt - amount)
                vuelto = max(0.0, amount - debt)
                lines.append(line(t("payments.preview.applied"), aplicado))
                if restante > 0:
                    lines.append(line(t("payments.preview.remaining"), restante, color=COLORS["accent_warning"]))
                else:
                    lines.append(line(t("payments.preview.remaining_zero"), 0, color=COLORS["accent_success"]))
                if vuelto > 0:
                    lines.append(line(t("payments.preview.change"), vuelto, color=COLORS["text_secondary"]))
            preview_lines.controls = lines
            _u(preview_lines)

        amount_field.on_change = update_preview

        def _show_client_sections():
            section2.visible = True
            section3.visible = True
            _u(section2)
            _u(section3)

        def update_debt():
            client_id = selected["id"]
            if not client_id:
                return
            # status / dados do cliente
            selected_client = selected["data"] or {}
            if not selected_client:
                try:
                    selected_client = client_service.get(client_id)
                    selected["data"] = selected_client
                except APIError:
                    selected_client = {}
            status = selected_client.get("status", "-")
            client_name_text.value = selected_client.get("nombre_completo", t("payments.client_default"))
            chip = self._status_chip(status)
            client_status_chip.content = chip.content
            client_status_chip.bgcolor = chip.bgcolor
            client_status_chip.border = chip.border
            client_status_chip.padding = chip.padding
            client_status_chip.border_radius = chip.border_radius
            client_status_chip.visible = True
            client_sub_text.value = t(
                "payments.client_sub",
                ci=selected_client.get('ci_ruc', '-'),
                meter=selected_client.get('numero_medidor', '-'),
            )
            state["cortado"] = (status == "CORTADO")
            _u(client_name_text)
            _u(client_status_chip)
            _u(client_sub_text)

            # saldo pendente
            try:
                debt = client_service.get_pending_balance(client_id)
                state["debt"] = float(debt.get("saldo_pendiente", 0) or 0)
                state["facturas"] = int(debt.get("facturas_pendientes", 0) or 0)
            except APIError:
                state["debt"] = 0.0
                state["facturas"] = 0
            debt_value_text.value = self._money(state["debt"])
            debt_count_text.value = t("payments.debt_count", count=state['facturas'])
            _u(debt_value_text)
            _u(debt_count_text)

            # taxa de reativação (das configurações) — sempre exibida se CORTADO
            if state["cortado"]:
                try:
                    state["taxa"] = float((self._get_company_info() or {}).get("taxa_reativacao", 0) or 0)
                except Exception:
                    state["taxa"] = 0.0
                total_reactiv = state["debt"] + state["taxa"]
                cut_warning.content = ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=COLORS["accent_error"], size=18),
                                ft.Text(t("payments.cortado_warning"),
                                        size=12, weight=ft.FontWeight.W_600, color=COLORS["text_primary"], expand=True),
                            ],
                            spacing=8,
                        ),
                        ft.Row([ft.Text(t("payments.warn.debt"), size=12, color=COLORS["text_secondary"]), ft.Container(expand=True),
                                ft.Text(self._money(state["debt"]), size=12, color=COLORS["text_primary"])]),
                        ft.Row([ft.Text(t("payments.preview.reactivation"), size=12, color=COLORS["accent_warning"]), ft.Container(expand=True),
                                ft.Text(self._money(state["taxa"]), size=12, color=COLORS["accent_warning"])]),
                        ft.Divider(height=1, color=COLORS["border"]),
                        ft.Row([ft.Text(t("payments.warn.total"), size=12, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                                ft.Container(expand=True),
                                ft.Text(self._money(total_reactiv), size=13, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])]),
                    ],
                    spacing=5,
                )
                cut_warning.padding = SPACING["sm"]
                cut_warning.bgcolor = ft.Colors.with_opacity(0.10, COLORS["accent_error"])
                cut_warning.border = ft.Border.all(1, ft.Colors.with_opacity(0.5, COLORS["accent_error"]))
                cut_warning.border_radius = 10
                cut_warning.visible = True
            else:
                state["taxa"] = 0.0
                cut_warning.visible = False
            _u(cut_warning)

            # faturas pendentes (detalhe)
            try:
                invoices = invoice_service.list_by_client(client_id, limit=100)
                pending = [inv for inv in invoices if inv.get("status") in {"PENDENTE", "PARCIAL"}]
                rows: list[ft.Control] = []
                for inv in pending[:30]:
                    numero = inv.get("numero_factura") or inv.get("numero_fatura") or "-"
                    periodo = f"{inv.get('mes_referencia', 0):02d}/{inv.get('ano_referencia', '-')}"
                    saldo = self._money(inv.get("saldo_devedor", inv.get("valor_total", 0)))
                    rows.append(
                        ft.Row(
                            [
                                ft.Text(f"#{numero}", size=12, color=COLORS["text_secondary"], width=70),
                                ft.Text(periodo, size=12, color=COLORS["text_secondary"], width=70),
                                ft.Container(expand=True),
                                ft.Text(saldo, size=12, color=COLORS["text_primary"]),
                            ],
                        )
                    )
                if len(pending) > 30:
                    rows.append(ft.Text(f"... y {len(pending) - 30} más", color=COLORS["text_muted"], size=11))
                if not rows:
                    rows = [ft.Text("Sin facturas pendientes.", color=COLORS["text_muted"], size=12)]
                invoice_breakdown.controls = rows
            except APIError:
                invoice_breakdown.controls = [ft.Text("No se pudieron cargar las facturas.", color=COLORS["accent_error"], size=12)]
            _u(invoice_breakdown)

            # subsídio
            has_sponsor = bool(selected_client.get("has_sponsor"))
            is_sponsor = bool(selected_client.get("is_sponsor"))
            if has_sponsor and not is_sponsor:
                sub = selected_client.get("subsidio_porcentagem")
                subsidy_label = f"{sub}%" if sub is not None else "estándar"
                sponsor_info.value = f"Cliente subsidiado · porcentaje: {subsidy_label}"
                sponsor_info.visible = True
                apply_subsidy_cb.visible = True
                apply_subsidy_cb.value = True
            else:
                sponsor_info.visible = False
                apply_subsidy_cb.visible = False
            _u(sponsor_info)
            _u(apply_subsidy_cb)

            # prefill do monto com a dívida e atualização do preview
            if not (amount_field.value or "").strip():
                amount_field.value = f"{int(round(state['debt']))}" if state["debt"] else ""
                _u(amount_field)
            _show_client_sections()
            update_preview()

        def render_search_results():
            controls: list[ft.Control] = []
            for c in result_clients:
                status = c.get("status", "-")

                def choose_client(ev, client=c):
                    selected["id"] = client.get("id")
                    selected["data"] = client
                    amount_field.value = ""
                    _bg(update_debt)

                controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.PERSON, size=16, color=COLORS["text_secondary"]),
                                ft.Column(
                                    [
                                        ft.Text(c.get("nombre_completo", "-"), size=13, color=COLORS["text_primary"],
                                                weight=ft.FontWeight.W_500, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(t("payments.result_client_sub", ci=c.get('ci_ruc', '-'), meter=c.get('numero_medidor', '-')),
                                                size=11, color=COLORS["text_muted"]),
                                    ],
                                    spacing=1, expand=True,
                                ),
                                self._status_chip(status),
                            ],
                            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        bgcolor=COLORS["bg_elevated"], border=ft.Border.all(1, COLORS["border"]),
                        border_radius=8, ink=True, on_click=choose_client,
                    )
                )
            if not controls:
                controls = [ft.Text("Ningún cliente encontrado.", color=COLORS["text_muted"], size=12)]
            search_results.controls = controls
            _u(search_results)

        def search_by_invoice_number(ev=None):
            raw = (invoice_number_field.value or "").strip()
            if not raw.isdigit():
                invoice_search_hint.value = t("payments.invoice.numbers_only")
                invoice_search_hint.visible = True
                _u(invoice_search_hint)
                return
            try:
                invoice_search_hint.value = t("payments.invoice.searching")
                invoice_search_hint.visible = True
                _u(invoice_search_hint)
                inv = invoice_service.get_by_number(int(raw))
                client_id = inv.get("client_id")
                if not client_id:
                    invoice_search_hint.value = t("payments.invoice.no_client")
                    _u(invoice_search_hint)
                    return
                selected["id"] = client_id
                selected["data"] = None
                amount_field.value = ""
                invoice_search_hint.value = (
                    f"Factura #{raw} — {inv.get('status', '?')} · "
                    f"saldo {self._money(inv.get('saldo_devedor', 0))}"
                )
                _u(invoice_search_hint)
                update_debt()
            except APIError as err:
                invoice_search_hint.value = (
                    f"Factura #{raw} no encontrada." if err.status_code == 404 else f"Error: {err.detail}"
                )
                _u(invoice_search_hint)

        invoice_number_field.on_submit = lambda e: _bg(search_by_invoice_number)

        def run_search(ev=None):
            query = (client_search.value or "").strip()
            if len(query) < 2:
                result_clients.clear()
                render_search_results()
                return
            try:
                search_hint.value = t("payments.searching_clients")
                _u(search_hint)
                found = client_service.search(query=query, limit=30)
                result_clients.clear()
                result_clients.extend(found)
                render_search_results()
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)
            finally:
                search_hint.value = t("payments.search_hint")
                _u(search_hint)

        client_search.on_submit = lambda e: _bg(run_search)

        def save_payment(ev):
            if not selected["id"]:
                error_text.value = t("payments.err.select_client")
                error_text.visible = True
                _u(error_text)
                return
            amount = _parse_amount(amount_field.value)
            if amount is None or amount <= 0:
                error_text.value = t("payments.err.invalid_amount")
                error_text.visible = True
                _u(error_text)
                return
            try:
                payload = {
                    "client_id": selected["id"],
                    "valor_total": amount,
                    "metodo": method_dd.value or "EFECTIVO",
                    "aplicar_subsidio": bool(apply_subsidy_cb.value) if apply_subsidy_cb.visible else False,
                    "recibido_por": (receiver_field.value or "").strip() or None,
                    "observacion": (obs_field.value or "").strip() or None,
                }
                result = payment_service.create(payload)
                if _modal_ref:
                    _modal_ref[0].close()
                self.last_payment_result = result
                self._update_last_receipt(result)
                self._run_load_payments()
                self._show_payment_result_dialog(result)
                self._print_payment_documents(result)
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                _u(error_text)

        section1_body = ft.Column(
            [
                ft.Text("Por número de factura", size=11, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                ft.Row(
                    [
                        invoice_number_field,
                        create_button("Buscar factura", icon=ft.Icons.RECEIPT_LONG, on_click=lambda e: _bg(search_by_invoice_number), primary=False),
                    ],
                    spacing=SPACING["sm"],
                ),
                invoice_search_hint,
                ft.Container(height=2),
                ft.Text("O por cliente", size=11, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                ft.Row(
                    [
                        client_search,
                        create_button("Buscar", icon=ft.Icons.SEARCH, on_click=lambda e: _bg(run_search), primary=False),
                    ],
                    spacing=SPACING["sm"],
                ),
                search_hint,
                search_results,
            ],
            spacing=SPACING["sm"],
        )
        section1 = self._section(1, t("payments.section.search"), section1_body)

        modal_h = int((self.page.height or 800) * 0.74)
        _modal_ref: list[AppModal] = []
        modal = AppModal(
            page=self.page,
            title=t("payments.new"),
            content=ft.Column(
                [section1, section2, section3],
                spacing=SPACING["md"],
                scroll=ft.ScrollMode.AUTO,
                height=modal_h,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal.close()),
                ModalAction(t("payments.process"), on_click=save_payment, primary=True),
            ],
            width_pct=0.56,
        )
        _modal_ref.append(modal)
        modal.open()

    def _update_last_receipt(self, result: dict):
        payment = result.get("payment", {})
        valor_pago = float(payment.get("valor_total", 0) or 0)
        total_subsidio = float(result.get("total_subsidio", 0) or 0)
        valor_original = valor_pago + total_subsidio
        subsidio_aplicado = bool(result.get("subsidio_aplicado", False))
        self.last_receipt.content = ft.Column(
            [
                ft.Text(t("payments.last_receipt.title"), weight=ft.FontWeight.BOLD),
                ft.Text(
                    t("payments.last_receipt.client", name=result.get('client_name', '-'), ci=result.get('client_ci_ruc', '-')),
                    color=COLORS["text_secondary"],
                ),
                ft.Text(t("payments.value_original", value=format_currency(valor_original, 'Gs.'))),
                ft.Text(
                    t("payments.subsidy_discount", value=format_currency(total_subsidio, 'Gs.'))
                    + (t("payments.subsidy_responsible", name=result.get('sponsor_name', '-')) if subsidio_aplicado else "")
                ),
                ft.Text(t("payments.value_paid", value=format_currency(valor_pago, 'Gs.'))),
                ft.Text(
                    t("payments.debt_before_after",
                      before=format_currency(result.get('total_debt_before', 0), 'Gs.'),
                      after=format_currency(result.get('total_debt_after', 0), 'Gs.'))
                ),
                ft.Text(t("payments.change_excess", value=format_currency(result.get('overpayment', 0), 'Gs.')), color=COLORS["text_secondary"]),
            ],
            spacing=2,
        )
        self.last_receipt.visible = True
        self.last_receipt.update()

    def _show_payment_result_dialog(self, result: dict):
        affected = result.get("invoices_affected", [])
        valor_pago = float(result.get("payment", {}).get("valor_total", 0) or 0)
        total_subsidio = float(result.get("total_subsidio", 0) or 0)
        valor_original = valor_pago + total_subsidio
        subsidio_aplicado = bool(result.get("subsidio_aplicado", False))
        allocations_controls = []
        for a in affected:
            subsidio = a.get("subsidio_transferido")
            allocations_controls.append(
                ft.Row(
                    [
                        ft.Text(f"{a.get('mes_referencia', 0):02d}/{a.get('ano_referencia', '')}", width=90),
                        ft.Text(format_currency(a.get("valor_aplicado", 0), "Gs."), width=140),
                        ft.Text(
                            (t("payments.subsidy_alloc", value=format_currency(subsidio, 'Gs.')) if subsidio else a.get("status_final", "-")),
                            color=COLORS["text_secondary"],
                        ),
                    ],
                    spacing=8,
                )
            )
        if not allocations_controls:
            allocations_controls = [ft.Text(t("payments.no_affected"), color=COLORS["text_muted"])]

        modal = AppModal(
            page=self.page,
            title=t("payments.result.title"),
            content=ft.Column(
                [
                    ft.Text(t("payments.result.client", name=result.get('client_name', '-'))),
                    ft.Text(t("payments.value_original", value=format_currency(valor_original, 'Gs.'))),
                    ft.Text(
                        t("payments.subsidy_discount", value=format_currency(total_subsidio, 'Gs.'))
                        + (t("payments.subsidy_responsible", name=result.get('sponsor_name', '-')) if subsidio_aplicado else "")
                    ),
                    ft.Text(t("payments.value_paid", value=format_currency(valor_pago, 'Gs.'))),
                    ft.Text(t("payments.result.debt_before", value=format_currency(result.get('total_debt_before', 0), 'Gs.'))),
                    ft.Text(t("payments.result.debt_after", value=format_currency(result.get('total_debt_after', 0), 'Gs.'))),
                    ft.Divider(),
                    ft.Text(t("payments.affected_invoices"), weight=ft.FontWeight.BOLD),
                    ft.Column(allocations_controls, spacing=4),
                ],
                spacing=8,
            ),
            actions=[
                ModalAction(t("payments.reprint"), on_click=lambda e: self._print_payment_documents(result)),
                ModalAction(t("common.close"), on_click=lambda e: modal.close()),
            ],
            width_pct=0.45,
        )
        modal.open()

    def _build_invoice_payload_for_print(self, invoice_details: dict, payment_result: dict) -> dict:
        client_payload = {
            "name": payment_result.get("client_name", "-"),
            "ci_ruc": payment_result.get("client_ci_ruc", "-"),
            "address": "-",
            "meter": "-",
            "manzana": "-",
            "lote": "-",
        }
        client_id = invoice_details.get("client_id")
        if client_id:
            try:
                from services.client_service import client_service
                client = client_service.get(client_id)
                client_payload = {
                    "name": client.get("nombre_completo", client_payload["name"]),
                    "ci_ruc": client.get("ci_ruc", client_payload["ci_ruc"]),
                    "address": client.get("direccion", "-"),
                    "meter": client.get("numero_medidor", "-"),
                    "manzana": client.get("manzana", "-"),
                    "lote": client.get("lote", "-"),
                }
            except Exception:
                pass
        return {
            "invoice": invoice_details,
            "client": client_payload,
            "company": self._get_company_info(),
        }

    def _get_company_info(self) -> dict:
        if self._company_cache is not None:
            return self._company_cache
        try:
            self._company_cache = settings_service.get()
        except Exception:
            self._company_cache = {}
        return self._company_cache

    def _print_auto_reactivation(self, result: dict, company: dict):
        """Imprime a Orden de Reactivación gerada automaticamente pelo pagamento
        que quitou a dívida de um cliente CORTADO."""
        notice_id = result.get("reactivation_notice_id")
        notice = cutoff_service.get_notice(notice_id) or {}
        try:
            taxa = float((company or {}).get("taxa_reativacao", 0) or 0)
        except Exception:
            taxa = 0.0
        deuda = float(result.get("total_debt_before", 0) or 0)
        token = result.get("reactivation_qr_token")
        qr_url = f"{get_api_url().rstrip('/')}/cutoff/qr/{token}/info" if token else None
        payment = result.get("payment", {}) or {}
        payload = {
            "client_name": notice.get("client_nombre", result.get("client_name", "-")),
            "client_ci_ruc": notice.get("client_ci_ruc", result.get("client_ci_ruc", "-")),
            "client_phone": notice.get("client_telefono"),
            "client_address": notice.get("client_direccion", "-"),
            "total_due": deuda,
            "reativation_fee": taxa,
            "paid_value": deuda + taxa,
            "notification_date": notice.get("fecha_aviso_gerado") or notice.get("fecha_entrega_aviso"),
            "payment_date": payment.get("fecha_pago"),
            "comprobante": result.get("reactivation_comprobante"),
            "issue_date": datetime.utcnow(),
            "qr_url": qr_url,
            "company": company,
        }
        pdf = self.reactivation_generator.generate(payload)
        printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"reactivation_{str(notice_id)[:12]}")

    def _print_payment_documents(self, result: dict):
        printed_count = 0
        errors = []
        company = self._get_company_info()

        try:
            receipt_payload = dict(result)
            receipt_payload["company"] = company
            receipt_pdf = self.receipt_generator.generate(receipt_payload)
            group = (result.get("payment", {}).get("grupo_pagamento") or "payment")[:20]
            printer_manager.print_pdf(receipt_pdf, printer_type="thermal", job_name=f"receipt_{group}")
            printed_count += 1
        except Exception as exc:
            print(f"[Payments] print_receipt_failed err={exc}")
            errors.append("el recibo")

        # Ordem de reativación automática: o cliente estava CORTADO e este
        # pagamento quitou a dívida → sai junto com o recibo.
        if result.get("reactivation_notice_id"):
            try:
                self._print_auto_reactivation(result, company)
                printed_count += 1
            except Exception as exc:
                print(f"[Payments] print_reactivation_failed err={exc}")
                errors.append("la orden de reactivación")

        affected = result.get("invoices_affected", []) or []
        # Formato escolhido pelo usuário: P80 (térmica, padrão) ou A4.
        fmt = get_invoice_print_format()
        if fmt == "a4":
            inv_gen, inv_printer = self.invoice_generator, "a4"
        else:
            inv_gen, inv_printer = self.invoice_p80_generator, "thermal"
        printed_invoices = set()
        for allocation in affected:
            invoice_id = allocation.get("invoice_id")
            if not invoice_id or invoice_id in printed_invoices:
                continue
            printed_invoices.add(invoice_id)
            try:
                details = invoice_service.get_with_balance(invoice_id)
                payload = self._build_invoice_payload_for_print(details, result)
                invoice_pdf = inv_gen.generate(payload)
                # Cada fatura é um job separado para a impressora cortar entre elas.
                printer_manager.print_pdf(invoice_pdf, printer_type=inv_printer, job_name=f"invoice_{invoice_id[:8]}")
                printed_count += 1
            except Exception as exc:
                period = f"{allocation.get('mes_referencia', 0):02d}/{allocation.get('ano_referencia', '-')}"
                print(f"[Payments] print_invoice_failed period={period} err={exc}")
                errors.append(t("payments.print.invoice_label", period=period))

        if errors:
            details = ", ".join(errors[:3])
            if len(errors) > 3:
                details += t("payments.print.and_more", count=len(errors) - 3)
            self.show_snackbar(
                t("payments.print.partial", count=printed_count, details=details),
                error=True,
            )
            return

        self.show_snackbar(t("payments.print.success", count=printed_count))

    def _show_payment_details_from_row(self, row: dict):
        try:
            details = payment_service.get(row["id"])
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
            return

        allocations = details.get("allocations", [])
        alloc_controls = []
        for item in allocations:
            alloc_controls.append(
                ft.Row(
                    [
                        ft.Text(f"{item.get('mes_referencia', 0):02d}/{item.get('ano_referencia', '')}", width=90),
                        ft.Text(format_currency(item.get("valor_aplicado", 0), "Gs."), width=130),
                        ft.Text(item.get("status_final", "-")),
                    ],
                    spacing=8,
                )
            )
        if not alloc_controls:
            alloc_controls = [ft.Text(t("payments.no_allocations"), color=COLORS["text_muted"])]

        nro = details.get("numero_recibo")
        recibo_txt = f"{int(nro):05d}" if nro not in (None, "") else "—"
        modal = AppModal(
            page=self.page,
            title=t("payments.detail.title", num=recibo_txt),
            content=ft.Column(
                [
                    ft.Text(t("payments.detail.date", value=format_date(details.get('fecha_pago'), '%d/%m/%Y %H:%M'))),
                    ft.Text(t("payments.detail.method", value=details.get('metodo', '-'))),
                    ft.Text(t("payments.detail.amount", value=format_currency(details.get('valor_total', 0), 'Gs.'))),
                    ft.Divider(),
                    ft.Text(t("payments.paid_invoices"), weight=ft.FontWeight.BOLD),
                    ft.Column(alloc_controls, spacing=4),
                ],
                spacing=8,
            ),
            actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
            width_pct=0.4,
        )
        modal.open()
