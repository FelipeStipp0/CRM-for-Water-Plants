"""
WMApp Frontend - Dashboard View
Painel operacional com metricas, alertas e atalhos.
"""
from __future__ import annotations

from datetime import datetime

import flet as ft

from components.loading_overlay import LoadingOverlay
from components.theme import COLORS, SPACING, create_button, create_header
from services.api_client import APIError
from utils.errors import friendly_error
from services.client_service import client_service
from services.cutoff_service import cutoff_service
from services.finance_service import finance_service
from services.invoice_service import invoice_service
from services.payment_service import payment_service
from services.sponsor_service import sponsor_service
from utils.formatters import format_currency, format_date


class DashboardView(ft.Container):
    """Dashboard operacional com dados reais da API."""

    def __init__(self, show_snackbar, on_navigate, user: dict | None):
        super().__init__()
        self.show_snackbar = show_snackbar
        self.on_navigate = on_navigate
        self.user = user or {}
        self._loaded = False
        self._metrics = {}
        self._loading_dashboard = False

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        if self.page:
            try:
                self.page.run_thread(self.trigger_initial_load)
                return
            except Exception as err:
                print(f"[DashboardView] on_visible_run_thread_error err={err}")
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._load_dashboard()

    def _has_scope(self, scope: str) -> bool:
        if self.user.get("is_superuser"):
            return True
        scopes = self.user.get("scopes", [])
        return "*" in scopes or scope in scopes

    @staticmethod
    def _to_float(value) -> float:
        try:
            return float(value or 0)
        except Exception:
            try:
                return float(str(value).replace(",", "."))
            except Exception:
                return 0.0

    def _safe_update(self, control: ft.Control | None):
        if control is None:
            return
        try:
            control.update()
        except Exception as err:
            print(f"[DashboardView] safe_update_error control={type(control).__name__} err={err}")
            if self.page:
                try:
                    self.page.update()
                except Exception as page_err:
                    print(f"[DashboardView] page_update_fallback_error err={page_err}")

    @staticmethod
    def _safe_period(value) -> str:
        try:
            return f"{int(value or 0):02d}"
        except Exception:
            return "00"

    def _build_metric_card(self, title: str, value_control: ft.Text, subtitle_control: ft.Text, icon: str, route: str | None = None):
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            on_click=(lambda e: self.on_navigate(route)) if route else None,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, size=17, color=COLORS["accent_secondary"]),
                            ft.Text(title, color=COLORS["text_secondary"], size=12),
                        ],
                        spacing=6,
                    ),
                    value_control,
                    subtitle_control,
                ],
                spacing=5,
                tight=True,
            ),
        )

    def _metric_row(self, cards: list[ft.Control]) -> ft.Row:
        return ft.Row(
            [ft.Container(content=card, expand=1) for card in cards],
            spacing=SPACING["sm"],
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _build(self):
        self.m_clients_value = ft.Text("-", size=21, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        self.m_clients_sub = ft.Text("Sem dados", size=12, color=COLORS["text_secondary"])

        self.m_debt_value = ft.Text("-", size=21, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        self.m_debt_sub = ft.Text("Sem dados", size=12, color=COLORS["text_secondary"])

        self.m_invoices_value = ft.Text("-", size=21, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        self.m_invoices_sub = ft.Text("Sem dados", size=12, color=COLORS["text_secondary"])

        self.m_cash_value = ft.Text("-", size=21, weight=ft.FontWeight.BOLD, color=COLORS["accent_success"])
        self.m_cash_sub = ft.Text("Sem dados", size=12, color=COLORS["text_secondary"])

        self.m_cutoff_value = ft.Text("-", size=21, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        self.m_cutoff_sub = ft.Text("Sem dados", size=12, color=COLORS["text_secondary"])

        self.m_sponsors_value = ft.Text("-", size=21, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        self.m_sponsors_sub = ft.Text("Sem dados", size=12, color=COLORS["text_secondary"])

        self.alerts_col = ft.Column(
            [ft.Text("Carregando alertas...", color=COLORS["text_muted"])],
            spacing=SPACING["xs"],
        )
        self.recent_payments_col = ft.Column(
            [ft.Text("Carregando pagamentos...", color=COLORS["text_muted"])],
            spacing=SPACING["xs"],
        )
        self.pending_invoices_col = ft.Column(
            [ft.Text("Carregando faturas...", color=COLORS["text_muted"])],
            spacing=SPACING["xs"],
        )

        header = ft.Row(
            [
                create_header("Dashboard Operacional"),
                ft.Container(expand=True),
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._load_dashboard(), primary=False),
            ]
        )

        quick_actions = ft.Container(
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_elevated"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Row(
                [
                    create_button("Novo Recebimento", icon=ft.Icons.POINT_OF_SALE, on_click=lambda e: self.on_navigate("/payments")),
                    create_button("Faturas", icon=ft.Icons.RECEIPT_LONG, on_click=lambda e: self.on_navigate("/invoices"), primary=False),
                    create_button("Corte", icon=ft.Icons.CONTENT_CUT, on_click=lambda e: self.on_navigate("/cutoff"), primary=False),
                    create_button("Financeiro", icon=ft.Icons.ACCOUNT_BALANCE, on_click=lambda e: self.on_navigate("/finance"), primary=False),
                    create_button("Subsidios", icon=ft.Icons.PEOPLE, on_click=lambda e: self.on_navigate("/sponsors"), primary=False),
                ],
                spacing=SPACING["sm"],
                wrap=True,
                run_spacing=SPACING["sm"],
            ),
        )

        cards_row_1 = self._metric_row(
            [
                self._build_metric_card("Clientes", self.m_clients_value, self.m_clients_sub, ft.Icons.PEOPLE, "/clients"),
                self._build_metric_card("Inadimplencia", self.m_debt_value, self.m_debt_sub, ft.Icons.WARNING, "/payments"),
                self._build_metric_card("Faturas Pendentes", self.m_invoices_value, self.m_invoices_sub, ft.Icons.DESCRIPTION, "/invoices"),
            ]
        )
        cards_row_2 = self._metric_row(
            [
                self._build_metric_card("Caixa do Periodo", self.m_cash_value, self.m_cash_sub, ft.Icons.ACCOUNT_BALANCE, "/finance"),
                self._build_metric_card("Corte", self.m_cutoff_value, self.m_cutoff_sub, ft.Icons.CONTENT_CUT, "/cutoff"),
                self._build_metric_card("Subsidios", self.m_sponsors_value, self.m_sponsors_sub, ft.Icons.PEOPLE, "/sponsors"),
            ]
        )

        alerts_panel = ft.Container(
            expand=True,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Text("Alertas Operacionais", weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    self.alerts_col,
                ],
                spacing=SPACING["sm"],
            ),
        )

        recent_panel = ft.Container(
            expand=True,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Text("Pagamentos Recentes", weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    self.recent_payments_col,
                ],
                spacing=SPACING["sm"],
            ),
        )

        pending_panel = ft.Container(
            expand=True,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
            content=ft.Column(
                [
                    ft.Text("Faturas Pendentes Prioritarias", weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    self.pending_invoices_col,
                ],
                spacing=SPACING["sm"],
            ),
        )

        main_content = ft.Column(
            [
                header,
                ft.Container(height=SPACING["md"]),
                quick_actions,
                ft.Container(height=SPACING["md"]),
                cards_row_1,
                ft.Container(height=SPACING["sm"]),
                cards_row_2,
                ft.Container(height=SPACING["md"]),
                alerts_panel,
                ft.Container(height=SPACING["sm"]),
                recent_panel,
                ft.Container(height=SPACING["sm"]),
                pending_panel,
            ],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.loading_overlay = LoadingOverlay("Carregando dashboard...")
        self.content = ft.Stack(
            [
                main_content,
                self.loading_overlay,
            ],
            expand=True,
        )
        self.padding = ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["sm"])
        self.bgcolor = COLORS["bg_primary"]
        self.expand = True

    def _load_dashboard(self):
        if self._loading_dashboard:
            return
        self._loading_dashboard = True
        print("[DashboardView] load_start")
        self.loading_overlay.show("Carregando dashboard...")

        metrics = {
            "clients_total": 0,
            "clients_active": 0,
            "debt_clients": 0,
            "debt_total": 0.0,
            "pending_invoices_count": 0,
            "pending_invoices_total": 0.0,
            "cash_saldo": 0.0,
            "cash_entradas": 0.0,
            "cash_saidas": 0.0,
            "cutoff_ready": 0,
            "cutoff_countdown": 0,
            "sponsors_count": 0,
            "recent_payments": [],
            "pending_invoices": [],
            "warnings": [],
        }

        if self._has_scope("clients"):
            try:
                clients = client_service.list(limit=120)
                metrics["clients_total"] = len(clients)
                metrics["clients_active"] = sum(1 for c in clients if c.get("status") == "ATIVO")
                debt_clients = client_service.list_with_debt(limit=120)
                metrics["debt_clients"] = len(debt_clients)
                metrics["debt_total"] = sum(self._to_float(c.get("deuda_total", c.get("divida_total", 0))) for c in debt_clients)
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        if self._has_scope("invoices"):
            try:
                pending = invoice_service.list(status="PENDENTE", limit=120)
                parcial = invoice_service.list(status="PARCIAL", limit=120)
                pending_all = pending + parcial
                metrics["pending_invoices_count"] = len(pending_all)
                metrics["pending_invoices_total"] = sum(self._to_float(i.get("saldo_devedor", 0)) for i in pending_all)
                metrics["pending_invoices"] = sorted(
                    pending_all,
                    key=lambda x: str(x.get("fecha_vencimiento", "")),
                )[:6]
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        if self._has_scope("payments"):
            try:
                metrics["recent_payments"] = payment_service.list(limit=8)
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        if self._has_scope("finance"):
            try:
                summary = finance_service.get_summary()
                metrics["cash_saldo"] = self._to_float(summary.get("saldo_periodo", 0))
                metrics["cash_entradas"] = self._to_float(summary.get("total_entradas", 0))
                metrics["cash_saidas"] = self._to_float(summary.get("total_saidas", 0))
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        if self._has_scope("cutoff"):
            try:
                ready = cutoff_service.list_ready(limit=120)
                countdown = cutoff_service.list_notices(status="EM_CONTAGEM", limit=120)
                metrics["cutoff_ready"] = len(ready)
                metrics["cutoff_countdown"] = len(countdown)
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        if self._has_scope("sponsors") or self._has_scope("finance"):
            try:
                metrics["sponsors_count"] = len(sponsor_service.list_sponsors())
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)

        self._metrics = metrics
        try:
            self._render_metrics()
        except Exception as err:
            self.show_snackbar(friendly_error(err), error=True)
        finally:
            self.loading_overlay.hide()
            self._loading_dashboard = False
            if self.page:
                try:
                    self.page.update()
                except Exception as err:
                    print(f"[DashboardView] final_page_update_error err={err}")
            print("[DashboardView] load_end")

    def _render_metrics(self):
        m = self._metrics
        self.m_clients_value.value = str(m["clients_total"])
        self.m_clients_sub.value = f"{m['clients_active']} ativos"

        self.m_debt_value.value = format_currency(m["debt_total"], "Gs.")
        self.m_debt_sub.value = f"{m['debt_clients']} clientes com divida"

        self.m_invoices_value.value = str(m["pending_invoices_count"])
        self.m_invoices_sub.value = f"Saldo: {format_currency(m['pending_invoices_total'], 'Gs.')}"

        self.m_cash_value.value = format_currency(m["cash_saldo"], "Gs.")
        self.m_cash_value.color = COLORS["accent_success"] if m["cash_saldo"] >= 0 else COLORS["accent_error"]
        self.m_cash_sub.value = (
            f"Entradas {format_currency(m['cash_entradas'], 'Gs.')} | "
            f"Saidas {format_currency(m['cash_saidas'], 'Gs.')}"
        )

        self.m_cutoff_value.value = str(m["cutoff_ready"])
        self.m_cutoff_sub.value = f"{m['cutoff_countdown']} em contagem"

        self.m_sponsors_value.value = str(m["sponsors_count"])
        self.m_sponsors_sub.value = "Responsaveis cadastrados"

        alerts = []
        if m["debt_clients"] > 0:
            alerts.append(f"{m['debt_clients']} cliente(s) com inadimplencia.")
        if m["pending_invoices_count"] > 0:
            alerts.append(f"{m['pending_invoices_count']} fatura(s) pendente(s).")
        if m["cutoff_ready"] > 0:
            alerts.append(f"{m['cutoff_ready']} cliente(s) pronto(s) para corte.")
        if m["cash_saldo"] < 0:
            alerts.append("Saldo do periodo negativo no caixa.")
        if not alerts:
            alerts = ["Sem alertas criticos no momento."]
        self.alerts_col.controls = [ft.Text(a, color=COLORS["text_secondary"]) for a in alerts]

        recent_controls = []
        for p in m["recent_payments"][:6]:
            recent_controls.append(
                ft.Row(
                    [
                        ft.Text(format_date(p.get("fecha_pago"), "%d/%m %H:%M"), width=90, color=COLORS["text_secondary"]),
                        ft.Text(str(p.get("metodo", "-")), width=90, color=COLORS["text_secondary"]),
                        ft.Text(format_currency(p.get("valor_total", 0), "Gs."), color=COLORS["text_primary"]),
                    ],
                    spacing=8,
                )
            )
        if not recent_controls:
            recent_controls = [ft.Text("Sem pagamentos recentes.", color=COLORS["text_muted"])]
        self.recent_payments_col.controls = recent_controls

        pending_controls = []
        for inv in m["pending_invoices"][:6]:
            pending_controls.append(
                ft.Row(
                    [
                        ft.Text(f"{self._safe_period(inv.get('mes_referencia', 0))}/{inv.get('ano_referencia', '-')}", width=80),
                        ft.Text(format_date(inv.get("fecha_vencimiento")), width=90, color=COLORS["text_secondary"]),
                        ft.Text(format_currency(inv.get("saldo_devedor", 0), "Gs."), color=COLORS["text_primary"]),
                    ],
                    spacing=8,
                )
            )
        if not pending_controls:
            pending_controls = [ft.Text("Sem faturas pendentes.", color=COLORS["text_muted"])]
        self.pending_invoices_col.controls = pending_controls

        self._safe_update(self)
