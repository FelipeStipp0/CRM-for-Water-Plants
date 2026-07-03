"""
WMApp Frontend - Invoices View
Tela de faturas com geracao em lote e criacao avulsa.
"""
from datetime import datetime

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.client_search_field import ClientSearchField
from components.data_table import DataTable
from components.loading_overlay import LoadingOverlay
from components.pagination import Pagination
from components.theme import COLORS, FONTS, SPACING, create_button, create_header, create_text_field
from services.api_client import APIError
from utils.errors import friendly_error
from services.client_service import client_service
from services.invoice_service import invoice_service
from i18n import t
from services.pdf_generation.invoices import (
    BulkInvoiceA4Generator,
    InvoiceA4Generator,
    InvoiceP80Generator,
)
from services.pdf_generation.pdf_preview import render_pdf_preview_pages
from services.pdf_generation.printer_manager import printer_manager
from services.reading_service import reading_service
from services.settings_service import settings_service
from utils.formatters import format_currency, format_date


class InvoicesView(ft.Container):
    """Tela de gestao de faturas."""

    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self._loaded = False
        now = datetime.now()
        self._mes_default = now.month
        self._ano_default = now.year
        self._data = []
        self._loading_invoices = False
        self._page_size = 100
        self._current_skip = 0
        self._company_cache: dict | None = None
        self.invoice_generator = InvoiceA4Generator()
        self.invoice_thermal_generator = InvoiceP80Generator()
        self.bulk_invoice_generator = BulkInvoiceA4Generator()

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._company_cache = None
        self._current_skip = 0
        self._run_load_invoices()

    def _on_page_change(self, skip: int):
        self._current_skip = skip
        self._run_load_invoices(skip=skip)

    def _run_load_invoices(self, skip: int = 0):
        if not getattr(self, "_data", None):
            try:
                self.table.show_skeleton(rows=10)
            except Exception as err:
                print(f"[InvoicesView] skeleton_error err={err}")
        if self.page:
            try:
                self.page.run_thread(lambda: self._load_invoices(skip))
                return
            except Exception as err:
                print(f"[InvoicesView] run_thread_error err={err}")
        self._load_invoices(skip)

    def _safe_update(self, control: ft.Control | None):
        if control is None:
            return
        try:
            control.update()
        except Exception as err:
            print(f"[InvoicesView] safe_update_error control={type(control).__name__} err={err}")
            if self.page:
                try:
                    self.page.update()
                except Exception as page_err:
                    print(f"[InvoicesView] page_update_fallback_error err={page_err}")

    def _build(self):
        self.date_from_field = create_text_field(t("invoices.filter.from"), value="", width=150, hint_text="YYYY-MM-DD")
        self.date_to_field = create_text_field(t("invoices.filter.to"), value="", width=150, hint_text="YYYY-MM-DD")
        self.status_dd = ft.Dropdown(
            label=t("invoices.filter.status"),
            width=150,
            value="",
            options=[
                ft.dropdown.Option("", t("invoices.filter.all")),
                ft.dropdown.Option("PENDENTE"),
                ft.dropdown.Option("PARCIAL"),
                ft.dropdown.Option("PAGADA"),
                ft.dropdown.Option("ANULADA"),
            ],
        )

        header = ft.Row(
            [
                create_header(t("invoices.title")),
                ft.Container(expand=True),
                create_button(t("invoices.btn.print_bulk"), icon=ft.Icons.PRINT, on_click=lambda e: self._print_bulk_filtered(), primary=False),
                create_button(t("invoices.btn.generate_bulk"), icon=ft.Icons.AUTO_AWESOME, on_click=self._open_generate_modal),
                create_button(t("invoices.btn.custom"), icon=ft.Icons.ADD_CARD, on_click=self._open_custom_modal, primary=False),
            ]
        )

        filters = ft.Row(
            [
                self.date_from_field,
                self.date_to_field,
                self.status_dd,
                create_button("Aplicar Filtros", icon=ft.Icons.FILTER_ALT, on_click=lambda e: (self.pagination.reset(), self._run_load_invoices(skip=0)), primary=False),
                create_button(t("invoices.btn.clear"), icon=ft.Icons.CLEAR, on_click=self._clear_filters, primary=False),
            ],
            wrap=True,
            spacing=SPACING["sm"],
        )

        self.table = DataTable(
            columns=[
                {"key": "numero_fatura", "label": t("invoices.col.invoice"), "min_width": 90, "flex": 1, "priority": 2, "align": "center"},
                {"key": "cliente_nome", "label": t("invoices.col.client"), "min_width": 220, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "periodo", "label": t("invoices.col.period"), "min_width": 90, "flex": 1, "priority": 2, "align": "center"},
                {"key": "tipo", "label": t("invoices.col.type"), "min_width": 80, "flex": 1, "priority": 3, "align": "center"},
                {"key": "status", "label": t("invoices.col.status"), "min_width": 90, "flex": 1, "priority": 2, "align": "center"},
                {"key": "valor_total_fmt", "label": t("invoices.col.value"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
                {"key": "saldo_devedor_fmt", "label": t("invoices.col.balance_due"), "min_width": 110, "flex": 1, "priority": 3, "align": "right"},
                {"key": "fecha_vencimiento_fmt", "label": t("invoices.col.due_date"), "min_width": 105, "flex": 1, "priority": 4, "align": "center"},
            ],
            data=[],
            on_row_click=self._show_invoice_details,
            on_edit=self._print_single_invoice_from_row,
            on_delete=self._delete_invoice,
            show_actions=True,
            edit_icon=ft.Icons.PRINT,
            edit_tooltip=t("invoices.print_tooltip"),
            delete_icon=ft.Icons.DELETE_FOREVER,
            delete_tooltip=t("invoices.delete_tooltip"),
        )
        self.loading_overlay = LoadingOverlay(t("invoices.loading"))
        self.pagination = Pagination(page_size=self._page_size, on_change=self._on_page_change)

        self.content = ft.Column(
            [
                header,
                filters,
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
        self.padding = ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["sm"])
        self.expand = True

    def _clear_filters(self, e):
        self.date_from_field.value = ""
        self.date_to_field.value = ""
        self.status_dd.value = ""
        self._safe_update(self.date_from_field)
        self._safe_update(self.date_to_field)
        self._safe_update(self.status_dd)
        self.pagination.reset()
        self._current_skip = 0
        self._run_load_invoices(skip=0)

    def _parse_date_filter(self, raw: str | None):
        value = (raw or "").strip()
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _extract_invoice_date(self, invoice_row: dict):
        raw = invoice_row.get("fecha_emision") or invoice_row.get("fecha_vencimiento")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
            except ValueError:
                return None

    def _filter_by_dates(self, rows: list[dict]) -> list[dict]:
        date_from = self._parse_date_filter(self.date_from_field.value)
        date_to = self._parse_date_filter(self.date_to_field.value)
        if not date_from and not date_to:
            return rows

        filtered: list[dict] = []
        for row in rows:
            inv_date = self._extract_invoice_date(row)
            if inv_date is None:
                continue
            if date_from and inv_date < date_from:
                continue
            if date_to and inv_date > date_to:
                continue
            filtered.append(row)
        return filtered

    def _load_invoices(self, skip: int = 0):
        if self._loading_invoices:
            return
        self._loading_invoices = True
        try:
            status = self.status_dd.value or None
            invoices, total = invoice_service.list_paged(status=status, mes=None, ano=None, skip=skip, limit=self._page_size)
            decorated = [self._decorate_invoice(item) for item in invoices]
            self._data = self._filter_by_dates(decorated)
            self.table.set_data(self._data)
            self.pagination.update_state(current_page=skip // self._page_size, total_items=total)
        except ValueError:
            self.table.set_error(t("invoices.err.invalid_dates_table"), on_retry=lambda: self._run_load_invoices(skip))
            self.show_snackbar(t("invoices.err.invalid_dates_filter"), error=True)
        except APIError as err:
            self.table.set_error(t("invoices.load_failed"), on_retry=lambda: self._run_load_invoices(skip))
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            self.table.set_error(t("invoices.load_failed_unexpected"), on_retry=lambda: self._run_load_invoices(skip))
            self.show_snackbar(friendly_error(err), error=True)
        finally:
            self._loading_invoices = False
            if self.page:
                try:
                    self.page.update()
                except Exception as err:
                    print(f"[InvoicesView] final_page_update_error err={err}")

    def _decorate_invoice(self, inv: dict) -> dict:
        row = dict(inv)
        row["numero_fatura"] = (
            inv.get("numero_factura")
            or inv.get("numero_fatura")
            or inv.get("nro_factura")
            or "-"
        )
        row["cliente_nome"] = (
            inv.get("client_nombre")
            or inv.get("cliente_nombre")
            or inv.get("nombre_cliente")
            or "-"
        )
        row["periodo"] = f"{inv.get('mes_referencia', 0):02d}/{inv.get('ano_referencia', '')}"
        row["valor_total_fmt"] = format_currency(inv.get("valor_total", 0), symbol="Gs.")
        row["saldo_devedor_fmt"] = format_currency(inv.get("saldo_devedor", 0), symbol="Gs.")
        row["fecha_vencimiento_fmt"] = format_date(inv.get("fecha_vencimiento"))
        return row

    def _show_invoice_details(self, invoice_row: dict):
        try:
            details = invoice_service.get_with_balance(invoice_row["id"])
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
            return

        items_list = details.get("items", [])
        item_controls = []
        for item in items_list:
            item_controls.append(
                ft.Row(
                    [
                        ft.Text(item.get("descripcion", "-"), width=220),
                        ft.Text(f"x{item.get('cantidad', 1)}", width=60, color=COLORS["text_secondary"]),
                        ft.Text(format_currency(item.get("subtotal", 0), "Gs."), color=COLORS["text_primary"]),
                    ],
                    spacing=8,
                )
            )
        if not item_controls:
            item_controls = [ft.Text("Sem itens detalhados", color=COLORS["text_muted"])]

        def open_print_dialog(ev):
            self._open_print_dialog(details)

        numero_ref = details.get("numero_factura") or details.get("numero_fatura") or "-"
        periodo_ref = f"{details.get('mes_referencia', 0):02d}/{details.get('ano_referencia', '')}"
        modal = AppModal(
            page=self.page,
            title=t("invoices.detail.title", num=numero_ref, period=periodo_ref),
            content=ft.Column(
                [
                    ft.Text(t("invoices.detail.client", value=invoice_row.get("cliente_nome", "-")), color=COLORS["text_secondary"]),
                    ft.Text(t("invoices.detail.status", value=details.get("status", "-")), color=COLORS["text_secondary"]),
                    ft.Text(t("invoices.detail.type", value=details.get("tipo", "-")), color=COLORS["text_secondary"]),
                    ft.Text(t("invoices.detail.due", value=format_date(details.get("fecha_vencimiento"))), color=COLORS["text_secondary"]),
                    ft.Divider(),
                    ft.Text(t("invoices.detail.summary"), weight=ft.FontWeight.BOLD),
                    ft.Text(t("invoices.detail.invoice_value", value=format_currency(details.get("valor_total", 0), "Gs."))),
                    ft.Text(t("invoices.detail.balance_due", value=format_currency(details.get("saldo_devedor", 0), "Gs."))),
                    ft.Text(
                        t("invoices.detail.prev_balance", value=format_currency(details.get("saldo_pendiente_anterior", 0), "Gs."))
                    ),
                    ft.Text(t("invoices.detail.total", value=format_currency(details.get("total_a_pagar", 0), "Gs."))),
                    ft.Divider(),
                    ft.Text(t("invoices.detail.items"), weight=ft.FontWeight.BOLD),
                    ft.Column(item_controls, spacing=4),
                ],
                spacing=8,
            ),
            actions=[
                ModalAction(t("invoices.btn.print"), on_click=open_print_dialog),
                ModalAction(t("common.close"), on_click=lambda e: modal.close()),
            ],
            width_pct=0.45,
        )
        modal.open()

    def _print_single_invoice_from_row(self, invoice_row: dict):
        try:
            details = invoice_service.get_with_balance(invoice_row["id"])
            self._open_print_dialog(details)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)

    def _build_invoice_payload_for_print(self, invoice_details: dict) -> dict:
        client_name = (
            invoice_details.get("client_nombre")
            or invoice_details.get("cliente_nombre")
            or invoice_details.get("nombre_cliente")
            or "-"
        )
        client_payload = {
            "name": client_name,
            "ci_ruc": invoice_details.get("client_ci_ruc", "-"),
            "address": invoice_details.get("client_direccion", "-"),
            "meter": invoice_details.get("client_numero_medidor", "-"),
            "manzana": invoice_details.get("client_manzana", "-"),
            "lote": invoice_details.get("client_lote", "-"),
        }
        client_id = invoice_details.get("client_id")
        needs_client_fetch = any(client_payload[k] in (None, "", "-") for k in ("ci_ruc", "address", "meter"))
        if client_id and needs_client_fetch:
            try:
                client = client_service.get(client_id)
                client_payload = {
                    "name": client.get("nombre_completo", client_payload["name"]),
                    "ci_ruc": client.get("ci_ruc", "-"),
                    "address": client.get("direccion", "-"),
                    "meter": client.get("numero_medidor", "-"),
                    "manzana": client.get("manzana", "-"),
                    "lote": client.get("lote", "-"),
                }
            except APIError:
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

    def _generate_invoice_pdf_a4(self, invoice_details: dict) -> bytes:
        payload = self._build_invoice_payload_for_print(invoice_details)
        return self.invoice_generator.generate(payload)

    def _generate_invoice_pdf_p80(self, invoice_details: dict) -> bytes:
        payload = self._build_invoice_payload_for_print(invoice_details)
        return self.invoice_thermal_generator.generate(payload)

    def _print_invoice_a4(self, invoice_details: dict):
        try:
            pdf_bytes = self._generate_invoice_pdf_a4(invoice_details)
            invoice_id = (invoice_details.get("id") or "invoice")[:12]
            printer_manager.print_pdf(pdf_bytes, printer_type="a4", job_name=f"invoice_{invoice_id}")
            period = f"{invoice_details.get('mes_referencia', 0):02d}/{invoice_details.get('ano_referencia', '-')}"
            self.show_snackbar(t("invoices.printed", period=period))
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)

    def _print_invoice_thermal(self, invoice_details: dict):
        try:
            pdf_bytes = self._generate_invoice_pdf_p80(invoice_details)
            invoice_id = (invoice_details.get("id") or "invoice")[:12]
            printer_manager.print_pdf(pdf_bytes, printer_type="thermal", job_name=f"invoice_p80_{invoice_id}")
            period = f"{invoice_details.get('mes_referencia', 0):02d}/{invoice_details.get('ano_referencia', '-')}"
            self.show_snackbar(t("invoices.printed_thermal", period=period))
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)

    def _open_print_dialog(self, invoice_details: dict):
        numero_ref = invoice_details.get("numero_factura") or invoice_details.get("numero_fatura") or "-"
        periodo_ref = f"{invoice_details.get('mes_referencia', 0):02d}/{invoice_details.get('ano_referencia', '')}"

        format_dd = ft.Dropdown(
            value="A4",
            width=160,
            options=[
                ft.dropdown.Option("A4", "A4"),
                ft.dropdown.Option("P80", t("invoices.print.format_p80")),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            text_style=ft.TextStyle(color=COLORS["text_primary"], size=FONTS["size_sm"]),
            label_style=ft.TextStyle(color=COLORS["text_muted"], size=FONTS["size_xs"]),
        )
        status_text = ft.Text(
            t("invoices.print.select_hint"),
            color=COLORS["text_muted"],
            size=FONTS["size_sm"],
        )

        # Área de preview — começa vazia, expande ao carregar
        pages_col = ft.Row(
            [],
            wrap=True,
            spacing=SPACING["md"],
            run_spacing=SPACING["md"],
            alignment=ft.MainAxisAlignment.CENTER,
        )
        preview_container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=pages_col,
                        padding=ft.padding.symmetric(vertical=SPACING["sm"]),
                    )
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            visible=False,
            height=480,
        )

        previewed_formats: set[str] = set()
        modal: AppModal | None = None  # referência atribuída após criação

        def current_mode() -> str:
            return str(format_dd.value or "A4").upper()

        def run_preview(ev=None):
            mode = current_mode()
            status_text.value = t("invoices.print.generating")
            self._safe_update(status_text)
            try:
                if mode == "P80":
                    pdf_bytes = self._generate_invoice_pdf_p80(invoice_details)
                else:
                    pdf_bytes = self._generate_invoice_pdf_a4(invoice_details)
                result = render_pdf_preview_pages(pdf_bytes, max_pages=6, scale=1.5)
                page_list = result.get("pages", [])
                if not page_list:
                    raise RuntimeError("Nenhuma pagina renderizada.")

                pages_col.controls.clear()
                for b64 in page_list:
                    img_w = int((self.page.width or 1280) * 0.38) - 48
                doc_w = img_w if mode == "A4" else int(img_w * 0.55)
                pages_col.controls.append(
                    ft.Row(
                        [
                            ft.Container(
                                bgcolor="#ffffff",
                                border_radius=4,
                                shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.3, "#000000")),
                                content=ft.Image(
                                    src=f"data:image/png;base64,{b64}",
                                    fit=ft.BoxFit.CONTAIN,
                                    width=doc_w,
                                ),
                            )
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                    )
                )
                preview_container.visible = True
                previewed_formats.add(mode)
                status_text.value = t("invoices.print.ready", mode=mode)
            except Exception as err:
                status_text.value = friendly_error(err)
            self._safe_update(status_text)
            self._safe_update(preview_container)

        def run_print(ev):
            mode = current_mode()
            if mode not in previewed_formats:
                self.show_snackbar(t("invoices.print.preview_first"), error=True)
                return
            if mode == "P80":
                self._print_invoice_thermal(invoice_details)
            else:
                self._print_invoice_a4(invoice_details)

        format_dd.on_change = lambda e: (
            setattr(status_text, "value", f"Formato {current_mode()} selecionado."),
            self._safe_update(status_text),
        )

        body = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(f"Fatura {numero_ref}  ·  {periodo_ref}", size=FONTS["size_sm"], color=COLORS["text_secondary"]),
                                ft.Text(f"Cliente: {invoice_details.get('client_nombre') or '-'}", size=FONTS["size_sm"], color=COLORS["text_muted"]),
                            ],
                            spacing=2,
                            tight=True,
                            expand=True,
                        ),
                        format_dd,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                status_text,
                ft.Divider(height=1, color=COLORS["border"]),
                preview_container,
            ],
            spacing=SPACING["sm"],
            tight=True,
            expand=True,
        )

        modal = AppModal(
            page=self.page,
            title=t("invoices.print.title"),
            content=body,
            width_pct=0.45,
            max_height_pct=0.92,
            actions=[
                ModalAction(t("common.close"), on_click=lambda e: modal.close()),
                ModalAction(t("invoices.btn.preview"), on_click=run_preview),
                ModalAction("Imprimir", on_click=run_print, primary=True),
            ],
        )
        modal.open()
        run_preview()

    def _print_bulk_filtered(self):
        if not self._data:
            self.show_snackbar(t("invoices.bulk.none_loaded"), error=True)
            return
        try:
            payloads = []
            for row in self._data[:30]:
                try:
                    details = invoice_service.get_with_balance(row["id"])
                    payloads.append(self._build_invoice_payload_for_print(details))
                except APIError:
                    continue
            if not payloads:
                self.show_snackbar(t("invoices.bulk.none_valid"), error=True)
                return
            pdf_bytes = self.bulk_invoice_generator.generate(payloads)
            date_from = (self.date_from_field.value or "").strip().replace("-", "") or "all"
            date_to = (self.date_to_field.value or "").strip().replace("-", "") or "all"
            period_hint = f"{date_from}_{date_to}"
            printer_manager.print_pdf(pdf_bytes, printer_type="a4", job_name=f"bulk_{period_hint}")
            pages = (len(payloads) + 2) // 3
            self.show_snackbar(t("invoices.bulk.sent", count=len(payloads), pages=pages))
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)

    def _delete_invoice(self, invoice_row: dict):
        numero = invoice_row.get("numero_fatura") or "-"
        cliente = invoice_row.get("cliente_nome") or "-"

        modal_del: AppModal = None  # type: ignore

        def confirm_delete(e):
            try:
                result = invoice_service.delete(invoice_row["id"])
                modal_del.close()
                payments_deleted = int(result.get("payments_deleted", 0) or 0)
                invoices_reverted = int(result.get("invoices_reverted", 0) or 0)
                self.show_snackbar(
                    "Fatura excluida. "
                    + f"Pagamentos removidos: {payments_deleted}. "
                    + f"Faturas revertidas: {invoices_reverted}."
                )
                self._run_load_invoices()
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        modal_del = AppModal(
            page=self.page,
            title=t("invoices.delete.title"),
            content=ft.Column(
                [
                    ft.Text(f"Fatura: {numero}"),
                    ft.Text(f"Cliente: {cliente}"),
                    ft.Text(
                        "Esta acao exclui a fatura e aplica cascade em pagamentos/ajustes relacionados.",
                        color=COLORS["text_secondary"],
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal_del.close()),
                ModalAction(t("common.delete"), on_click=confirm_delete, danger=True),
            ],
            width_pct=0.35,
        )
        modal_del.open()

    def _fetch_all_period_invoices(self, mes: int, ano: int, limit: int = 200) -> list[dict]:
        all_rows: list[dict] = []
        skip = 0
        while True:
            batch = invoice_service.list(mes=mes, ano=ano, skip=skip, limit=limit)
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < limit:
                break
            skip += limit
        return all_rows

    def _generate_minimum_invoices_for_pending(self, mes: int, ano: int) -> dict:
        settings = settings_service.get()
        valor_minimo = float(
            settings.get("valor_minimo_emissao")
            or settings.get("tarifa_base")
            or 0
        )
        if valor_minimo <= 0:
            raise RuntimeError("Valor minimo/tarifa base nao configurado para gerar faturas sem leitura.")

        pending_clients = reading_service.list_pending(mes=mes, ano=ano)
        if not pending_clients:
            return {"created": 0, "skipped": 0}

        existing = self._fetch_all_period_invoices(mes, ano)
        existing_client_ids = {
            str(inv.get("client_id"))
            for inv in existing
            if inv.get("client_id")
        }

        created = 0
        skipped = 0
        for client in pending_clients:
            client_id = str(client.get("client_id") or "").strip()
            if not client_id:
                skipped += 1
                continue
            if client_id in existing_client_ids:
                skipped += 1
                continue
            payload = {
                "client_id": client_id,
                "tipo": "AVULSA",
                "mes_referencia": mes,
                "ano_referencia": ano,
                "items": [
                    {
                        "descripcion": "Tarifa minima sem leitura",
                        "cantidad": 1,
                        "precio_unitario": valor_minimo,
                    }
                ],
            }
            try:
                invoice_service.create_custom(payload)
                created += 1
                existing_client_ids.add(client_id)
            except APIError:
                skipped += 1
        return {"created": created, "skipped": skipped}

    def _open_generate_modal(self, e):
        mes_field = create_text_field(t("invoices.generate.month"), value=str(self._mes_default), width=140)
        ano_field = create_text_field(t("invoices.generate.year"), value=str(self._ano_default), width=140)
        day_field = create_text_field(t("invoices.generate.day"), width=220)
        clients_field = create_text_field(t("invoices.generate.client_ids"), width=420)
        all_clients_cb = ft.Checkbox(label=t("invoices.generate.all_clients"), value=True)
        min_without_reading_cb = ft.Checkbox(label=t("invoices.generate.min_without_reading"), value=True)
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def toggle_clients_field(_=None):
            clients_field.disabled = bool(all_clients_cb.value)
            if all_clients_cb.value:
                clients_field.value = ""
            self._safe_update(clients_field)

        all_clients_cb.on_change = toggle_clients_field
        toggle_clients_field()

        try:
            settings = settings_service.get()
            day_field.value = str(settings.get("dia_geracao_faturas") or "")
            min_without_reading_cb.value = bool(settings.get("gerar_sem_leitura_valor_minimo", True))
        except Exception:
            pass

        def run_generate(ev):
            try:
                mes = int((mes_field.value or "").strip())
                ano = int((ano_field.value or "").strip())
                ids_raw = (clients_field.value or "").strip()
                client_ids = None
                if not all_clients_cb.value and ids_raw:
                    client_ids = [c.strip() for c in ids_raw.split(",") if c.strip()]
                day_raw = (day_field.value or "").strip()
                dia_geracao = int(day_raw) if day_raw else None
                gerar_minimo = bool(all_clients_cb.value and min_without_reading_cb.value)

                try:
                    result = invoice_service.generate_batch_extended(
                        mes_referencia=mes,
                        ano_referencia=ano,
                        client_ids=client_ids,
                        gerar_sem_leitura_valor_minimo=gerar_minimo,
                        dia_geracao=dia_geracao,
                    )
                    min_generated = int(result.get("total_minimum_generated", 0) or 0)
                    min_skipped = int(result.get("total_minimum_skipped", 0) or 0)
                except APIError as err:
                    # Compatibilidade com backend antigo que nao suporta campos estendidos.
                    if err.status_code in {400, 422}:
                        result = invoice_service.generate_batch(
                            mes_referencia=mes,
                            ano_referencia=ano,
                            client_ids=client_ids,
                        )
                        # Fallback frontend para faturas minimas em backend antigo
                        min_generated = 0
                        min_skipped = 0
                        if gerar_minimo:
                            fallback = self._generate_minimum_invoices_for_pending(mes, ano)
                            min_generated = int(fallback.get("created", 0) or 0)
                            min_skipped = int(fallback.get("skipped", 0) or 0)
                    else:
                        raise

                if _modal_ref_gen:
                    _modal_ref_gen[0].close()
                self.show_snackbar(
                    t(
                        "invoices.generate.summary",
                        gen=result.get('total_generated', 0),
                        skip=result.get('total_skipped', 0),
                        min_gen=min_generated,
                        min_skip=min_skipped,
                    )
                )
                self._run_load_invoices()
            except ValueError:
                error_text.value = t("invoices.err.month_year_numeric")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_gen: list[AppModal] = []
        modal_gen = AppModal(
            page=self.page,
            title=t("invoices.generate.title"),
            content=ft.Column(
                [
                    ft.Row([mes_field, ano_field, day_field], spacing=8, wrap=True),
                    all_clients_cb,
                    clients_field,
                    min_without_reading_cb,
                    error_text,
                ],
                spacing=10,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_gen.close()),
                ModalAction(t("invoices.btn.generate"), on_click=run_generate, primary=True),
            ],
            width_pct=0.45,
        )
        _modal_ref_gen.append(modal_gen)
        modal_gen.open()

    def _open_custom_modal(self, e):
        def _search_clients(query: str):
            try:
                return client_service.search(query=query, limit=20)
            except Exception:
                return []

        client_search = ClientSearchField(on_search=_search_clients, width=440, label=t("invoices.col.client"))
        mes_field = create_text_field(t("invoices.generate.month"), value=str(self._mes_default), width=120)
        ano_field = create_text_field(t("invoices.generate.year"), value=str(self._ano_default), width=120)
        venc_field = create_text_field(t("invoices.custom.venc"), width=200, hint_text="YYYY-MM-DD (opcional)")

        items_column = ft.Column(spacing=8)
        item_rows = []

        def add_item_row(ev=None, refresh=True):
            desc = create_text_field(t("invoices.custom.item_desc"), width=230)
            qtd = create_text_field(t("invoices.custom.item_qty"), value="1", width=70)
            price = create_text_field(t("invoices.custom.item_price"), width=120)
            row = ft.Row([desc, qtd, price], spacing=8)
            item_rows.append({"desc": desc, "qtd": qtd, "price": price})
            items_column.controls.append(row)
            if refresh:
                self._safe_update(items_column)

        add_item_row(refresh=False)

        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def save_custom(ev):
            try:
                if not client_search.selected_id:
                    raise APIError(400, t("readings.err.select_client"))

                items = []
                for item in item_rows:
                    desc = (item["desc"].value or "").strip()
                    qtd_raw = (item["qtd"].value or "").strip()
                    price_raw = (item["price"].value or "").strip().replace(",", ".")
                    if not desc and not price_raw:
                        continue
                    if not desc:
                        raise APIError(400, t("invoices.err.item_desc_required"))
                    items.append(
                        {
                            "descripcion": desc,
                            "cantidad": int(qtd_raw or "1"),
                            "precio_unitario": float(price_raw),
                        }
                    )

                if not items:
                    raise APIError(400, t("invoices.err.add_one_item"))

                payload = {
                    "client_id": client_search.selected_id,
                    "tipo": "AVULSA",
                    "mes_referencia": int((mes_field.value or "").strip()),
                    "ano_referencia": int((ano_field.value or "").strip()),
                    "items": items,
                }
                venc = (venc_field.value or "").strip()
                if venc:
                    payload["fecha_vencimiento"] = venc

                invoice_service.create_custom(payload)
                if _modal_ref_custom:
                    _modal_ref_custom[0].close()
                self.show_snackbar(t("invoices.custom.created"))
                self._run_load_invoices()
            except ValueError:
                error_text.value = t("invoices.err.invalid_items")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        _modal_ref_custom: list[AppModal] = []
        modal_custom = AppModal(
            page=self.page,
            title=t("invoices.custom.title"),
            content=ft.Column(
                [
                    client_search,
                    ft.Row([mes_field, ano_field, venc_field], spacing=8),
                    ft.Row(
                        [
                            ft.Text(t("invoices.detail.items"), weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            create_button(t("invoices.custom.add_item"), icon=ft.Icons.ADD, on_click=add_item_row, primary=False),
                        ]
                    ),
                    items_column,
                    error_text,
                ],
                spacing=10,
                tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal_custom.close()),
                ModalAction(t("common.save"), on_click=save_custom, primary=True),
            ],
            width_pct=0.4,
        )
        _modal_ref_custom.append(modal_custom)
        modal_custom.open()
