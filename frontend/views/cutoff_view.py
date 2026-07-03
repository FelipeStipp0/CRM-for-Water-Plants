"""WMApp Frontend - Cutoff View"""
from datetime import date, datetime

import flet as ft

from components.custom_tabs import CustomTabs, TabItem
from components.data_table import DataTable
from components.image_viewer import ImageViewer
from components.loading_overlay import LoadingOverlay
from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, SPACING, create_button, create_header, create_text_field
from config.local_settings import get_api_url
from services.api_client import APIError
from utils.errors import friendly_error
from services.cutoff_service import cutoff_service
from i18n import t
from services.pdf_generation.notifications import CutNoticeGenerator, CutOrderGenerator, ReactivationRequestGenerator
from services.pdf_generation.printer_manager import printer_manager
from services.settings_service import settings_service
from utils.formatters import format_currency, format_date


# Mapeamento status → label legível
_STATUS_LABEL = {
    "EM_LISTA": "Na lista",
    "EM_AVISO": "Aviso emitido",
    "EM_CONTAGEM": "Em contagem",
    "PRONTO_PARA_CORTE": "Pronto p/ corte",
    "CORTADO": "Cortado",
}


class CutoffView(ft.Container):
    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self._loaded = False
        self._loading_cutoff = False
        self._company_cache: dict | None = None
        # Seleção múltipla de candidatos: client_id -> (checkbox, row)
        self._cand_checks: dict[str, tuple] = {}
        self.cut_notice_generator = CutNoticeGenerator()
        self.cut_order_generator = CutOrderGenerator()
        self.reactivation_generator = ReactivationRequestGenerator()
        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._company_cache = None
        self._run_refresh_all()

    # ------------------------------------------------------------------ helpers

    def _run_in_thread(self, fn):
        try:
            if self.page:
                self.page.run_thread(fn)
                return
        except Exception:
            pass
        fn()

    def _run_with_overlay(self, message: str, fn):
        # Skeleton cobre o vazio das tabelas. Overlay sobreposto causava
        # sensacao de "spinner em cima de placeholder".
        def worker():
            try:
                fn()
            finally:
                try:
                    if self.page:
                        self.page.update()
                except Exception:
                    pass
        self._run_in_thread(worker)

    def _run_refresh_all(self):
        self._run_with_overlay("Carregando corte...", self._refresh_all)

    def _run_load_candidates(self):
        try:
            if not self.candidates_table.data:
                self.candidates_table.show_skeleton(rows=10)
        except Exception:
            pass
        self._run_with_overlay("Carregando candidatos...", self._load_candidates)

    def _run_load_notices(self):
        try:
            if not self.notices_table.data:
                self.notices_table.show_skeleton(rows=10)
        except Exception:
            pass
        self._run_with_overlay("Carregando workflow...", self._load_notices)

    def _run_load_ready(self):
        try:
            if not self.ready_table.data:
                self.ready_table.show_skeleton(rows=10)
        except Exception:
            pass
        self._run_with_overlay("Carregando prontos...", self._load_ready)

    def _close(self, d):
        d.close()

    def _d(self, v):
        if not v:
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).date() if "T" in v else datetime.strptime(v[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    def _countdown_text(self, status, limite) -> str:
        if status != "EM_CONTAGEM":
            return "-"
        d = self._d(limite)
        if not d:
            return "-"
        days = (d - date.today()).days
        return f"{days} dia(s)" if days >= 0 else f"Vencido há {abs(days)} dia(s)"

    def _get_company_info(self) -> dict:
        if self._company_cache is not None:
            return self._company_cache
        try:
            self._company_cache = settings_service.get()
        except Exception:
            self._company_cache = {}
        return self._company_cache

    _ALIAS_LABEL = {"CI": "C.I.", "CELULAR": "Celular", "EMAIL": "Correo", "RUC": "RUC"}

    def _compose_bank_info(self, company: dict) -> str | None:
        """Monta a linha de transferência ('Banco X, con Alias TIPO valor').

        Retorna None quando não há dados configurados — assim o gerador de PDF
        usa seu fallback padrão em vez de imprimir uma linha incompleta.
        """
        banco = (company.get("banco_nombre") or "").strip()
        alias_valor = (company.get("alias_valor") or "").strip()
        if not banco and not alias_valor:
            return None
        alias_label = self._ALIAS_LABEL.get(company.get("alias_tipo") or "", "")
        partes = []
        if banco:
            partes.append(banco)
        if alias_valor:
            partes.append(f"con Alias {alias_label} {alias_valor}".strip())
        return ", ".join(partes)

    # ------------------------------------------------------------------ build

    def _build(self):
        self.status_dd = ft.Dropdown(
            label=t("cutoff.filter.status"),
            value="",
            width=170,
            options=[ft.dropdown.Option("", t("cutoff.filter.all"))] + [
                ft.dropdown.Option(x, _STATUS_LABEL.get(x, x))
                for x in ["EM_LISTA", "EM_AVISO", "EM_CONTAGEM", "PRONTO_PARA_CORTE", "CORTADO"]
            ],
        )
        self.status_dd.on_change = lambda e: self._run_load_notices()
        self.include_exited = ft.Checkbox(label=t("cutoff.include_exited"), value=False)
        self.include_exited.on_change = lambda e: self._run_load_notices()

        self.candidates_table = DataTable(
            columns=[
                {"key": "sel", "label": "", "width": 44, "priority": 1, "hideable": False, "align": "center", "no_row_click": True},
                {"key": "nombre_completo", "label": t("cutoff.col.client"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "ci_ruc", "label": t("cutoff.col.ci_ruc"), "min_width": 100, "flex": 1, "priority": 3, "align": "center"},
                {"key": "manzana", "label": t("cutoff.col.mz"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "lote", "label": t("cutoff.col.lt"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "meses_atraso", "label": t("cutoff.col.months_late"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
                {"key": "divida_fmt", "label": t("cutoff.col.debt"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
            ],
            data=[],
            on_row_click=self._on_candidate_click,
            show_actions=False,
        )

        self.notices_table = DataTable(
            columns=[
                {"key": "client_nombre", "label": t("cutoff.col.client"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "client_manzana", "label": t("cutoff.col.mz"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "client_lote", "label": t("cutoff.col.lt"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "status_label", "label": t("cutoff.col.situation"), "min_width": 130, "flex": 1, "priority": 1, "align": "center"},
                {"key": "divida_fmt", "label": t("cutoff.col.debt"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
                {"key": "countdown_txt", "label": t("cutoff.col.deadline"), "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
            ],
            data=[],
            on_row_click=self._open_notice,
            show_actions=False,
        )

        self.ready_table = DataTable(
            columns=[
                {"key": "client_nombre", "label": t("cutoff.col.client"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "client_manzana", "label": t("cutoff.col.mz"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "client_lote", "label": t("cutoff.col.lt"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "divida_atual_fmt", "label": t("cutoff.col.debt"), "min_width": 120, "flex": 1, "priority": 1, "align": "right"},
                {"key": "limite_fmt", "label": t("cutoff.col.deadline_limit"), "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
                {"key": "status_label", "label": t("cutoff.col.situation"), "min_width": 130, "flex": 1, "priority": 1, "align": "center"},
            ],
            data=[],
            on_row_click=self._open_notice,
            show_actions=False,
        )

        tabs = CustomTabs(
            tabs=[
                TabItem(t("cutoff.tab.candidates"), self._build_candidates_tab()),
                TabItem(t("cutoff.tab.workflow"), self._build_workflow_tab()),
                TabItem(t("cutoff.tab.ready"), self._build_ready_tab()),
            ],
            selected_index=0,
        )

        self.loading_overlay = LoadingOverlay(t("cutoff.loading"))
        self.content = ft.Stack(
            [
                ft.Column(
                    [
                        ft.Row([
                            create_header(t("cutoff.title")),
                            ft.Container(expand=True),
                            create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_refresh_all(), primary=False),
                        ]),
                        ft.Container(height=SPACING["md"]),
                        tabs,
                    ],
                    expand=True,
                ),
                self.loading_overlay,
            ],
            expand=True,
        )
        self.padding = ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["sm"])
        self.expand = True

    def _action_bar(self, left: list | None = None, right: list | None = None) -> ft.Control:
        # Layout responsivo sem wrap (wrap+expand quebra) e sem expand spacer
        # (que somia em telas estreitas): grupos esquerdo e direito separados
        # por MainAxisAlignment.SPACE_BETWEEN. Funciona em qualquer largura
        # razoavel — em 720/768p o conteudo cabe folgado.
        left = left or []
        right = right or []
        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        left,
                        spacing=SPACING["sm"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                    ft.Row(
                        right,
                        spacing=SPACING["sm"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
            bgcolor=COLORS["bg_elevated"],
            border=ft.Border.all(1, COLORS["border"]),
            border_radius=10,
        )

    def _hint_text(self, message: str) -> ft.Control:
        # Hint vai em linha propria acima do action bar. Em vez de competir
        # com os botoes pelo espaco horizontal (e cortar o botao em telas
        # pequenas), fica numa Row separada que envolve naturalmente.
        return ft.Container(
            content=ft.Text(message, color=COLORS["text_muted"], size=12, italic=True),
            padding=ft.padding.only(left=4, right=4, bottom=2),
        )

    def _build_candidates_tab(self) -> ft.Control:
        hint = self._hint_text(
            "Marcá los clientes y agregalos a la lista de notificados (se imprime el aviso). "
            "También podés hacer clic en una fila para agregar uno solo."
        )
        self.cand_select_all = ft.Checkbox(label=t("cutoff.select_all"), value=False, on_change=self._toggle_select_all_candidates)
        actions = self._action_bar(
            left=[self.cand_select_all],
            right=[
                create_button("Agregar seleccionados", icon=ft.Icons.NOTIFICATIONS_ACTIVE,
                              on_click=lambda e: self._add_selected_candidates(), primary=True),
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_load_candidates(), primary=False),
            ],
        )
        return ft.Column(
            [
                ft.Container(height=SPACING["sm"]),
                hint,
                actions,
                ft.Container(height=SPACING["sm"]),
                self.candidates_table,
            ],
            expand=True,
        )

    def _build_workflow_tab(self) -> ft.Control:
        actions = self._action_bar(
            left=[self.status_dd, self.include_exited],
            right=[
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_load_notices(), primary=False),
            ],
        )
        return ft.Column([ft.Container(height=SPACING["sm"]), actions, ft.Container(height=SPACING["sm"]), self.notices_table], expand=True)

    def _build_ready_tab(self) -> ft.Control:
        hint = self._hint_text("Avisos com prazo vencido, aguardando execução do corte.")
        actions = self._action_bar(
            right=[
                create_button("Processar Expirados", icon=ft.Icons.SCHEDULE, on_click=self._process_expired, primary=False),
                create_button("Atualizar", icon=ft.Icons.REFRESH, on_click=lambda e: self._run_load_ready(), primary=False),
            ],
        )
        return ft.Column(
            [
                ft.Container(height=SPACING["sm"]),
                hint,
                actions,
                ft.Container(height=SPACING["sm"]),
                self.ready_table,
            ],
            expand=True,
        )

    # ------------------------------------------------------------------ data loading

    def _refresh_all(self):
        if self._loading_cutoff:
            return
        self._loading_cutoff = True
        try:
            self._load_candidates()
            self._load_notices()
            self._load_ready()
        finally:
            self._loading_cutoff = False

    def _load_candidates(self):
        try:
            rows = cutoff_service.list_candidates()
            self._cand_checks = {}
            if hasattr(self, "cand_select_all"):
                self.cand_select_all.value = False
            for r in rows:
                r["divida_fmt"] = format_currency(r.get("divida_total", 0), "Gs.")
                cid = str(r.get("client_id", ""))
                cb = ft.Checkbox(value=False)
                self._cand_checks[cid] = (cb, r)
                r["sel"] = cb
            self.candidates_table.set_data(rows)
        except APIError as err:
            self.candidates_table.set_error(t("cutoff.load_failed.candidates"), on_retry=self._run_load_candidates)
            self.show_snackbar(friendly_error(err), error=True)

    def _decorate_notice(self, r: dict) -> dict:
        r["status_label"] = _STATUS_LABEL.get(r.get("status", ""), r.get("status", "-"))
        r["divida_fmt"] = format_currency(r.get("divida_original", 0), "Gs.")
        r["divida_atual_fmt"] = format_currency(r.get("divida_atual", r.get("divida_original", 0)), "Gs.")
        r["limite_fmt"] = format_date(r.get("fecha_limite_pago"))
        r["countdown_txt"] = self._countdown_text(r.get("status", ""), r.get("fecha_limite_pago"))
        # Fallback de nome caso a listagem não traga
        if not r.get("client_nombre"):
            r["client_nombre"] = f"Cliente {str(r.get('client_id', ''))[:8]}"
        if not r.get("client_manzana"):
            r["client_manzana"] = r.get("manzana", "-")
        if not r.get("client_lote"):
            r["client_lote"] = r.get("lote", "-")
        return r

    def _load_notices(self):
        try:
            # A listagem já vem com os dados do cliente (batch no backend), então
            # não há mais N+1 de get_notice por linha aqui.
            rows = cutoff_service.list_notices(
                status=self.status_dd.value or None,
                include_exited=bool(self.include_exited.value),
                limit=120,
            )
            decorated = [self._decorate_notice(r) for r in rows]
            self.notices_table.set_data(decorated)
        except APIError as err:
            self.notices_table.set_error(t("cutoff.load_failed.workflow"), on_retry=self._run_load_notices)
            self.show_snackbar(friendly_error(err), error=True)

    def _load_ready(self):
        try:
            rows = cutoff_service.list_ready(limit=120)
            for r in rows:
                self._decorate_notice(r)
            self.ready_table.set_data(rows)
        except APIError as err:
            self.ready_table.set_error(t("cutoff.load_failed.ready"), on_retry=self._run_load_ready)
            self.show_snackbar(friendly_error(err), error=True)

    # ------------------------------------------------------------------ actions

    def _on_candidate_click(self, row: dict):
        """Clique numa linha = adicionar esse único candidato (com confirmação)."""
        self._confirm_add([row])

    def _toggle_select_all_candidates(self, e):
        val = bool(self.cand_select_all.value)
        for cb, _row in self._cand_checks.values():
            cb.value = val
            try:
                cb.update()
            except Exception:
                pass

    def _add_selected_candidates(self):
        rows = [row for cb, row in self._cand_checks.values() if cb.value]
        if not rows:
            self.show_snackbar(t("cutoff.select_one"), error=True)
            return
        self._confirm_add(rows)

    def _confirm_add(self, rows: list[dict]):
        """Modal de confirmação: adicionar à lista de notificados + imprimir aviso."""
        # A nota imprime horário/dados bancários — exige configuração.
        if not self._require_notice_config():
            return

        names = [r.get("nombre_completo", "Cliente") for r in rows]
        if len(names) <= 6:
            lista = ft.Column(
                [ft.Text(f"• {n}", size=12, color=COLORS["text_primary"]) for n in names],
                spacing=2,
            )
        else:
            lista = ft.Text(
                "• " + ", ".join(names[:5]) + t("cutoff.more_suffix", count=len(names) - 5),
                size=12, color=COLORS["text_primary"],
            )
        md: AppModal = None  # type: ignore

        def confirm(e):
            md.close()
            self._run_with_overlay(
                t("cutoff.add.overlay"),
                lambda: self._do_add_and_print(rows),
            )

        md = AppModal(
            page=self.page,
            title=t("cutoff.add.title"),
            content=ft.Column(
                [
                    ft.Text(
                        t("cutoff.add.body", count=len(rows)),
                        size=13, color=COLORS["text_secondary"],
                    ),
                    ft.Container(height=4),
                    lista,
                ],
                spacing=8, tight=True,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: md.close()),
                ModalAction(t("cutoff.add.confirm"), on_click=confirm, primary=True),
            ],
            width_pct=0.36,
        )
        md.open()

    def _do_add_and_print(self, rows: list[dict]):
        """Para cada candidato: adiciona ao workflow, gera o aviso e imprime."""
        ok, fail = 0, []
        for r in rows:
            nome = r.get("nombre_completo", "Cliente")
            try:
                added = cutoff_service.add_notice(r["client_id"])
                notice_id = added.get("cutoff_notice_id")
                if not notice_id:
                    fail.append(f"{nome}: sin id de aviso")
                    continue
                info = cutoff_service.generate_notice(notice_id)
                token = info.get("qr_token")
                detail = cutoff_service.get_notice(notice_id)
                url = f"{get_api_url().rstrip('/')}/cutoff/qr/{token}/info" if token else None
                self._print_cutoff_document(detail, url, is_notice=True)
                ok += 1
            except APIError as err:
                fail.append(f"{nome}: {err.detail}")
            except Exception as err:
                fail.append(f"{nome}: {err}")

        # Recarrega as abas (já estamos numa worker thread do overlay).
        self._refresh_all()

        if fail:
            resumo = "; ".join(fail[:3]) + (f"; +{len(fail) - 3}" if len(fail) > 3 else "")
            self.show_snackbar(t("cutoff.add.partial", ok=ok, resumo=resumo), error=True)
        else:
            self.show_snackbar(t("cutoff.add.success", count=ok))

    def _process_expired(self, e):
        try:
            result = cutoff_service.process_expired()
            self.show_snackbar(result.get("message", t("cutoff.expired_processed")))
            self._run_refresh_all()
        except APIError as err:
            self.show_snackbar(str(err.detail), error=True)

    # ------------------------------------------------------------------ notice detail dialog

    def _open_notice(self, row: dict):
        try:
            n = cutoff_service.get_notice(row["id"])
        except APIError as err:
            self.show_snackbar(str(err.detail), error=True)
            return

        status = n.get("status", "")

        # ---- Linha do tempo ----
        timeline_items = [
            ("Adicionado à lista", n.get("created_at"), None),
            ("Aviso gerado", n.get("fecha_aviso_gerado"), None),
            ("Aviso entregue", n.get("fecha_entrega_aviso"), n.get("aviso_entregue_por")),
            ("Prazo limite", n.get("fecha_limite_pago"), None),
            ("Corte executado", n.get("fecha_corte"), n.get("cortado_por")),
            ("Reativação solicitada", n.get("fecha_solicitud_reativacao"), None),
            ("Reativação confirmada", n.get("fecha_reativacao"), n.get("reativacao_confirmada_por")),
        ]

        timeline_controls = []
        for label, dt_val, responsible in timeline_items:
            if not dt_val:
                continue
            d = self._d(dt_val) or dt_val
            date_str = format_date(d) if not isinstance(d, str) else d
            sub = f" — {responsible}" if responsible else ""
            timeline_controls.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CIRCLE, size=8, color=COLORS["accent_secondary"]),
                        ft.Text(f"{label}: {date_str}{sub}", size=12, color=COLORS["text_primary"]),
                    ],
                    spacing=8,
                )
            )

        if not timeline_controls:
            timeline_controls = [ft.Text("Sem datas registradas.", color=COLORS["text_muted"], size=12)]

        # ---- Fotos/GPS ----
        has_media = (
            n.get("foto_instalacao_url")
            or n.get("foto_reativacao_url")
            or n.get("gps_corte_latitude") is not None
            or n.get("gps_reativacao_latitude") is not None
        )

        # ---- Cabeçalho de info ----
        countdown_txt = self._countdown_text(status, n.get("fecha_limite_pago"))
        info_lines = [
            ft.Text(
                n.get("client_nombre", "-"),
                size=15,
                weight=ft.FontWeight.BOLD,
                color=COLORS["text_primary"],
            ),
            ft.Row([
                ft.Text(f"Mz {n.get('client_manzana', '-')} / Lt {n.get('client_lote', '-')}", color=COLORS["text_secondary"], size=12),
                ft.Container(width=16),
                ft.Text(f"CI/RUC: {n.get('client_ci_ruc', '-')}", color=COLORS["text_secondary"], size=12),
            ], spacing=0),
            ft.Row([
                ft.Text(f"Dívida atual: ", color=COLORS["text_secondary"], size=13),
                ft.Text(format_currency(n.get("divida_atual", n.get("divida_original", 0)), "Gs."), size=13, weight=ft.FontWeight.BOLD, color=COLORS["accent_error"]),
            ], spacing=4),
        ]
        if countdown_txt != "-":
            info_lines.append(ft.Text(f"Prazo: {countdown_txt}", color=COLORS["accent_warning"], size=12))
        if n.get("observacion_aviso"):
            info_lines.append(ft.Text(f"Obs. entrega: {n['observacion_aviso']}", color=COLORS["text_muted"], size=11, italic=True))
        if n.get("observacion_corte"):
            info_lines.append(ft.Text(f"Obs. corte: {n['observacion_corte']}", color=COLORS["text_muted"], size=11, italic=True))

        content_col = ft.Column(
            [
                ft.Column(info_lines, spacing=4),
                ft.Divider(),
                ft.Text("Linha do tempo", weight=ft.FontWeight.BOLD, size=12, color=COLORS["text_secondary"]),
                ft.Column(timeline_controls, spacing=6),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )

        # ---- Botões de ação por status ----
        d: AppModal = None  # type: ignore
        action_actions: list[ModalAction] = []

        if status == "EM_LISTA":
            action_actions.append(
                ModalAction(t("cutoff.act.generate_notice"), on_click=lambda e: self._act_generate(n, d, is_notice=True), primary=True)
            )

        if status == "EM_AVISO":
            action_actions.append(
                ModalAction(t("cutoff.act.register_delivery"), on_click=lambda e: self._act_deliver_modal(n, d), primary=True)
            )

        if status == "EM_CONTAGEM":
            action_actions.append(
                ModalAction(t("cutoff.act.mark_ready"), on_click=lambda e: self._act_simple(lambda: cutoff_service.mark_ready(n["id"]), d), primary=True)
            )

        if status == "PRONTO_PARA_CORTE":
            action_actions.append(
                ModalAction(t("cutoff.act.generate_order"), on_click=lambda e: self._act_generate(n, d, is_notice=False))
            )
            action_actions.append(
                ModalAction(t("cutoff.act.execute"), on_click=lambda e: self._act_execute_modal(n, d), danger=True)
            )

        if status == "CORTADO":
            action_actions.append(
                ModalAction("Solicitar Reativação", on_click=lambda e: self._reactivate_request(n, d), primary=True)
            )
            if n.get("reativacao_solicitada") and not n.get("fecha_reativacao"):
                action_actions.append(
                    ModalAction(t("cutoff.act.confirm_reactivation"), on_click=lambda e: self._act_simple(lambda: cutoff_service.confirm_reactivation(n["id"]), d), primary=True)
                )

        if has_media:
            action_actions.append(
                ModalAction(t("cutoff.act.view_photos"), on_click=lambda e: self._show_photos_dialog(n))
            )

        action_actions.append(ModalAction(t("common.close"), on_click=lambda e: self._close(d)))

        d = AppModal(
            page=self.page,
            title=f"{_STATUS_LABEL.get(status, status)} — {n.get('client_nombre', '-')}",
            content=content_col,
            actions=action_actions,
            width_pct=0.45,
        )
        d.open()

    # ------------------------------------------------------------------ action helpers

    def _act_simple(self, call, dialog: AppModal):
        try:
            r = call()
            dialog.close()
            self.show_snackbar(r.get("message", "Operação realizada."))
            self._run_refresh_all()
        except APIError as err:
            self.show_snackbar(str(err.detail), error=True)

    def _act_deliver_modal(self, n: dict, parent_dialog: AppModal):
        nome_f = create_text_field("Entregue por (opcional)", width=300)
        obs_f = create_text_field("Observação (opcional)", width=300)
        err_t = ft.Text("", color=COLORS["accent_error"], visible=False)
        md: AppModal = None  # type: ignore

        def confirm(e):
            try:
                r = cutoff_service.register_delivery(
                    n["id"],
                    entregue_por=(nome_f.value or "").strip() or None,
                    observacion=(obs_f.value or "").strip() or None,
                )
                md.close()
                parent_dialog.close()
                self.show_snackbar(r.get("message", "Entrega registrada."))
                self._run_refresh_all()
            except APIError as ex:
                err_t.value = str(ex.detail)
                err_t.visible = True
                err_t.update()

        md = AppModal(
            page=self.page,
            title=t("cutoff.deliver.title"),
            content=ft.Column([nome_f, obs_f, err_t], spacing=10, tight=True),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: md.close()),
                ModalAction(t("common.confirm"), on_click=confirm, primary=True),
            ],
            width_pct=0.3,
        )
        md.open()

    def _act_execute_modal(self, n: dict, parent_dialog: AppModal):
        nome_f = create_text_field("Executado por (opcional)", width=300)
        obs_f = create_text_field("Observação (opcional)", width=300)
        err_t = ft.Text("", color=COLORS["accent_error"], visible=False)
        md: AppModal = None  # type: ignore

        def confirm(e):
            try:
                r = cutoff_service.execute_cutoff(
                    n["id"],
                    cortado_por=(nome_f.value or "").strip() or None,
                    observacion=(obs_f.value or "").strip() or None,
                )
                md.close()
                parent_dialog.close()
                self.show_snackbar(r.get("message", "Corte executado."))
                self._run_refresh_all()
            except APIError as ex:
                err_t.value = str(ex.detail)
                err_t.visible = True
                err_t.update()

        md = AppModal(
            page=self.page,
            title=t("cutoff.execute.title"),
            content=ft.Column([
                ft.Text(
                    f"Confirmar corte de {n.get('client_nombre', '-')}?\nEssa ação marca o cliente como CORTADO.",
                    color=COLORS["text_secondary"],
                    size=13,
                ),
                nome_f, obs_f, err_t,
            ], spacing=10, tight=True),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: md.close()),
                ModalAction(t("cutoff.act.execute"), on_click=confirm, danger=True),
            ],
            width_pct=0.3,
        )
        md.open()

    def _require_notice_config(self) -> bool:
        """Exige horário de atención + dados bancários configurados antes de gerar
        a notificação (são impressos no documento; sem fallback)."""
        # Recarrega as configs (podem ter sido editadas nesta sessão).
        self._company_cache = None
        company = self._get_company_info()
        horario = (company.get("horario_atencion") or "").strip()
        banco = (company.get("banco_nombre") or "").strip()
        alias = (company.get("alias_valor") or "").strip()
        if not horario or not banco or not alias:
            self.show_snackbar(
                "Configure el horario de atención y los datos bancarios (banco + alias) "
                "en Configuración antes de generar la notificación.",
                error=True,
            )
            return False
        return True

    def _act_generate(self, n: dict, parent_dialog: AppModal, is_notice: bool):
        # Só a Nota imprime horário/dados bancários; a Orden não precisa deles.
        if is_notice and not self._require_notice_config():
            return
        try:
            info = cutoff_service.generate_notice(n["id"]) if is_notice else cutoff_service.generate_order(n["id"])
            parent_dialog.close()
            self._run_refresh_all()
            token = info.get("qr_token")
            if token:
                url = f"{get_api_url().rstrip('/')}/cutoff/qr/{token}/info"
                try:
                    detail = cutoff_service.get_notice(n["id"])
                    self._print_cutoff_document(detail, url, is_notice=is_notice)
                except APIError:
                    pass
                self.show_snackbar(t("cutoff.doc.generated"))
            else:
                self.show_snackbar(t("cutoff.doc.no_qr"))
        except APIError as err:
            self.show_snackbar(str(err.detail), error=True)

    def _reactivate_request(self, n: dict, parent_dialog: AppModal):
        taxa = 0.0
        try:
            taxa = float(settings_service.get().get("taxa_reativacao", 0) or 0)
        except Exception:
            pass
        div = float(n.get("divida_atual", 0) or 0)
        val_f = create_text_field("Valor Pago", value=str(div + taxa), width=200)
        err_t = ft.Text("", color=COLORS["accent_error"], visible=False)
        md: AppModal = None  # type: ignore

        def send(e):
            try:
                v = float((val_f.value or "").replace(",", "."))
                r = cutoff_service.request_reactivation(n["client_id"], v)
                md.close()
                parent_dialog.close()
                self._run_refresh_all()
                token = r.get("qr_token")
                if token:
                    url = f"{get_api_url().rstrip('/')}/cutoff/qr/{token}/info"
                    self._print_reactivation_document(
                        n, url, paid_value=v, fee=taxa,
                        comprobante=r.get("comprobante"),
                        payment_date=r.get("fecha_pago"),
                    )
                self.show_snackbar(t("cutoff.reactivation.requested"))
            except ValueError:
                err_t.value = t("cutoff.err.invalid_value")
                err_t.visible = True
                err_t.update()
            except APIError as ex:
                err_t.value = str(ex.detail)
                err_t.visible = True
                err_t.update()

        md = AppModal(
            page=self.page,
            title=t("cutoff.reactivation.title"),
            content=ft.Column([
                ft.Text(f"Dívida: {format_currency(div, 'Gs.')}  |  Taxa: {format_currency(taxa, 'Gs.')}", color=COLORS["text_secondary"], size=13),
                ft.Text("O valor pago deve cobrir dívida + taxa.", color=COLORS["text_muted"], size=12, italic=True),
                val_f, err_t,
            ], spacing=10, tight=True),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: md.close()),
                ModalAction(t("cutoff.reactivation.request"), on_click=send, primary=True),
            ],
            width_pct=0.32,
        )
        md.open()

    # ------------------------------------------------------------------ media

    def _show_photos_dialog(self, notice: dict):
        panels: list[ft.Control] = []

        if notice.get("foto_instalacao_url"):
            panels.append(ImageViewer(
                image_url=notice["foto_instalacao_url"],
                title=t("cutoff.photo.cut_title"),
                gps_latitude=notice.get("gps_corte_latitude"),
                gps_longitude=notice.get("gps_corte_longitude"),
                width=620, height=320,
            ))

        if notice.get("foto_reativacao_url"):
            panels.append(ImageViewer(
                image_url=notice["foto_reativacao_url"],
                title=t("cutoff.photo.reactivation_title"),
                gps_latitude=notice.get("gps_reativacao_latitude"),
                gps_longitude=notice.get("gps_reativacao_longitude"),
                width=620, height=320,
            ))

        if not panels:
            for label, lat, lon in [
                ("GPS corte", notice.get("gps_corte_latitude"), notice.get("gps_corte_longitude")),
                ("GPS reativação", notice.get("gps_reativacao_latitude"), notice.get("gps_reativacao_longitude")),
            ]:
                if lat is not None and lon is not None:
                    panels.append(ft.Text(f"{label}: {lat:.6f}, {lon:.6f}", color=COLORS["text_secondary"]))

        if not panels:
            panels.append(ft.Text("Nenhuma foto ou GPS disponível.", color=COLORS["text_muted"]))

        dlg = AppModal(
            page=self.page,
            title=f"Evidências — {notice.get('client_nombre', '-')}",
            content=ft.Column(panels, spacing=8),
            actions=[ModalAction(t("common.close"), on_click=lambda e: dlg.close())],
            width_pct=0.55,
        )
        dlg.open()

    # ------------------------------------------------------------------ print

    def _print_cutoff_document(self, notice: dict, qr_url: str, is_notice: bool):
        # Nota de corte (aviso ao cliente) e Orden de corte (execução) são
        # documentos DIFERENTES, com geradores distintos.
        company = self._get_company_info()
        base = {
            "client_name": notice.get("client_nombre", "-"),
            "client_ci_ruc": notice.get("client_ci_ruc", "-"),
            "client_phone": notice.get("client_telefono"),
            "client_address": notice.get("client_direccion", "-"),
            "client_manzana": notice.get("client_manzana", "-"),
            "client_lote": notice.get("client_lote", "-"),
            "total_due": notice.get("divida_atual", notice.get("divida_original", 0)),
            "issue_date": datetime.utcnow(),
            "qr_url": qr_url,
            "company": company,
        }
        try:
            if is_notice:
                # NOTA / Notificación de corte (aviso prévio + meios de pagamento).
                payload = {
                    **base,
                    "title": "Notificación de Corte de Servicio",
                    "office_hours": (company.get("horario_atencion") or "").strip() or None,
                    "bank_info": self._compose_bank_info(company),
                }
                pdf = self.cut_notice_generator.generate(payload)
                job = "cut_notice"
            else:
                # ORDEN de corte (execução): deuda + multa configurada + data da nota.
                try:
                    multa = float(company.get("multa", 0) or 0)
                except Exception:
                    multa = 0.0
                payload = {
                    **base,
                    "multa": multa,
                    "notification_date": notice.get("fecha_aviso_gerado") or notice.get("fecha_entrega_aviso"),
                }
                pdf = self.cut_order_generator.generate(payload)
                job = "cut_order"
            printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"{job}_{str(notice.get('id', ''))[:12]}")
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)

    def _print_reactivation_document(self, notice: dict, qr_url: str, paid_value: float, fee: float,
                                     comprobante: str | None = None, payment_date=None):
        payload = {
            "client_name": notice.get("client_nombre", "-"),
            "client_ci_ruc": notice.get("client_ci_ruc", "-"),
            "client_phone": notice.get("client_telefono"),
            "client_address": notice.get("client_direccion", "-"),
            "total_due": notice.get("divida_atual", 0),
            "reativation_fee": fee,
            "paid_value": paid_value,
            # Data da notificação de corte que originou esta reativação.
            "notification_date": notice.get("fecha_aviso_gerado") or notice.get("fecha_entrega_aviso"),
            "payment_date": payment_date or datetime.utcnow(),
            "comprobante": comprobante,
            "issue_date": datetime.utcnow(),
            "qr_url": qr_url,
            "company": self._get_company_info(),
        }
        try:
            pdf = self.reactivation_generator.generate(payload)
            printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"reactivation_{str(notice.get('id', ''))[:12]}")
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.print_failed"), error=True)
