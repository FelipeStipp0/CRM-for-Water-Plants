"""
WMApp Frontend - Modo Caja (cobrança do dia a dia).

Tela cheia dedicada ao caixa: busca cliente -> grade de meses (pago/pendente/
adiantar) -> cobro direcionado e/ou adiantamento -> imprime recibo. Marca branca
(logo/nome da junta vêm de SystemSettings). O cajero cai direto aqui no login.

Reusa a infra já pronta:
- GET /clients/{id}/payment-context  -> grade_meses + saldo + faturas + tarifa_base
- POST /payments/  com invoice_ids (direcionado) e prepay_periods (adiantamento)
- Impressão P80 (mesmos geradores do payments_view)

Factura legal (SIFEN) + conferência de dados: próximo bloco.
"""

import threading
import uuid
from datetime import datetime

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.sifen_progress import open_sifen_progress
from components.theme import COLORS, FONTS, SPACING, RADIUS, create_text_field
from services.sifen_service import sifen_service
from config.local_settings import get_api_url
from services.api_client import APIError
from services.caja_service import caja_service
from services.client_service import client_service
from services.cutoff_service import cutoff_service
from services.payment_service import payment_service
from services.settings_service import settings_service
from services.pdf_generation.finance import CierreCajaP80Generator
from services.pdf_generation.receipts import PaymentReceiptP80Generator
from services.pdf_generation.notifications import ReactivationRequestGenerator
from services.pdf_generation.printer_manager import printer_manager
from utils.errors import friendly_error
from utils.formatters import format_currency, format_local, to_local
from i18n import t

_MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
_DIA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _money(v) -> str:
    return format_currency(v or 0, "Gs.")


class CajaView(ft.Container):
    """Layout de tela cheia do Modo Caja."""

    # Janela futura da grade de meses: começa em 6 e o cajero estica de 12 em 12
    # (teto igual ao do endpoint, que recusa mais que isso).
    MESES_FUTURO_INICIAL = 6
    MESES_FUTURO_MAX = 36

    def __init__(self, show_snackbar, current_user: dict, on_logout=None):
        super().__init__()
        self.show_snackbar = show_snackbar
        self.current_user = current_user or {}
        self.on_logout = on_logout

        self.expand = True
        self.bgcolor = COLORS["bg_primary"]

        self._alive = True
        self._clock_timer = None
        self._company = None
        self._search_timer = None

        # turno de caja aberto (None = nada cobrável, mostra a tela de apertura)
        self._sesion = None

        # estado da cobrança atual
        self._ctx = None            # payment-context do cliente selecionado
        self._cells = []            # [{ano,mes,estado,saldo,invoice_ids,sel}]
        self._tarifa = 0.0
        self._results = []
        self._meses_futuro = self.MESES_FUTURO_INICIAL

        # geradores de PDF (mesmos do payments_view)
        self._g_receipt = PaymentReceiptP80Generator()
        self._g_react = ReactivationRequestGenerator()
        self._g_cierre = CierreCajaP80Generator()

        self._build()

    # ---------------------------------------------------------------- helpers
    def _u(self, ctrl: ft.Control):
        try:
            ctrl.update()
        except Exception:
            pass

    def _bg(self, fn):
        if self.page:
            try:
                self.page.run_thread(fn)
                return
            except Exception:
                pass
        fn()

    def _get_company(self) -> dict:
        if self._company is None:
            try:
                self._company = settings_service.get() or {}
            except Exception as exc:  # noqa: BLE001
                # Sem isso os documentos saem sem nome/RUC da junta — não pode
                # falhar calado, o cajero tem que saber antes de imprimir.
                self._company = {}
                print(f"[Caja] company_load_failed err={exc}")
                self.show_snackbar(
                    "No se pudieron cargar los datos de la junta: los documentos "
                    "van a salir sin encabezado.", error=True)
        return self._company

    def _parse_amount(self, raw: str):
        raw = (raw or "").strip().replace(".", "").replace(",", ".")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def stop(self):
        """Encerra o relógio e devolve a janela ao normal (chamado no logout)."""
        self._alive = False
        if self._clock_timer:
            try:
                self._clock_timer.cancel()
            except Exception:
                pass
        self._sesion = None
        self._guard_window(False)

    # ---------------------------------------------------------------- build
    def _build(self):
        company = self._get_company()
        org_name = company.get("nombre_junta") or "Junta de Saneamiento"
        initials = "".join([w[0] for w in org_name.split()[:2]]).upper() or "JS"

        self._clock = ft.Text("", size=12, color=COLORS["text_secondary"])

        # Identificação do turno: "CAJA 07 · desde 08:12" (some enquanto fechada).
        self.caja_chip = ft.Container(visible=False)
        self.cerrar_btn = ft.TextButton(
            content=ft.Row([
                ft.Icon(ft.Icons.LOCK_OUTLINE, size=15, color=COLORS["text_secondary"]),
                ft.Text("Cerrar caja", size=12, color=COLORS["text_secondary"]),
            ], spacing=6, tight=True),
            on_click=lambda e: self._open_cierre(),
            visible=False,
        )

        top = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Text(initials, size=13, weight=ft.FontWeight.W_800, color="#CFE4FF"),
                        width=34, height=34, border_radius=9, alignment=ft.Alignment.CENTER,
                        bgcolor="#0B1834", border=ft.Border.all(1, "#24406E"),
                    ),
                    ft.Column(
                        [
                            ft.Text(org_name, size=15, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
                            ft.Text(company.get("actividad") or "Servicio de agua potable", size=11, color=COLORS["text_muted"]),
                        ],
                        spacing=1,
                    ),
                    ft.Container(expand=True),
                    self.caja_chip,
                    self._clock,
                    ft.Container(width=1, height=20, bgcolor=COLORS["border"]),
                    ft.Text(
                        f"Cajero: {self.current_user.get('full_name') or self.current_user.get('username', '')}",
                        size=13, color=COLORS["text_secondary"],
                    ),
                    self.cerrar_btn,
                    ft.TextButton(
                        content=ft.Text("Salir", size=12, color=COLORS["text_muted"]),
                        on_click=lambda e: self._try_logout(),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=13,
            ),
            padding=ft.Padding.symmetric(horizontal=22, vertical=10),
            bgcolor=COLORS["bg_secondary"],
            border=ft.Border.only(bottom=ft.BorderSide(1, COLORS["border"])),
        )

        cobranza = ft.Column(
            [top, ft.Row([self._build_left(), self._build_right()], spacing=0, expand=True)],
            spacing=0, expand=True,
        )
        # A apertura cobre a cobrança inteira: sem turno aberto não se cobra nada.
        # StackFit.EXPAND para as duas camadas ocuparem a tela toda (o default
        # LOOSE deixaria a camada só do tamanho do card).
        self.content = ft.Stack(
            [cobranza, self._build_apertura()], expand=True, fit=ft.StackFit.EXPAND,
        )
        self._start_clock()

    # ------------------------------------------------------- apertura / cierre
    def _build_apertura(self) -> ft.Control:
        self.apertura_monto = ft.TextField(
            value="", hint_text="0", border=ft.InputBorder.NONE, autofocus=True,
            text_style=ft.TextStyle(size=24, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=lambda e: self._abrir_caja(),
        )
        self.apertura_err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
        self.apertura_btn = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.LOCK_OPEN_OUTLINED, color="#FFFFFF", size=19),
                ft.Text("Abrir caja", size=16, weight=ft.FontWeight.W_700, color="#FFFFFF"),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=9),
            height=56, border_radius=RADIUS["md"], bgcolor=COLORS["accent_primary"],
            alignment=ft.Alignment.CENTER, ink=True, on_click=lambda e: self._abrir_caja(),
        )
        self.apertura_hint = ft.Text(
            "Contá el efectivo con el que arrancás el turno (fondo de cambio). "
            "Al cerrar, el sistema compara lo contado con lo que debería haber.",
            size=12, color=COLORS["text_muted"],
        )

        card = ft.Container(
            content=ft.Column([
                ft.Text("Caja cerrada", size=26, weight=ft.FontWeight.W_800, color=COLORS["text_primary"]),
                ft.Text("Abrí la caja para empezar a cobrar.", size=14, color=COLORS["text_secondary"]),
                ft.Container(height=10),
                ft.Text("MONTO INICIAL", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                ft.Container(
                    content=ft.Row([
                        ft.Text("Gs.", size=18, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                        ft.Container(content=self.apertura_monto, expand=True),
                    ], spacing=10),
                    bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["border"]),
                    border_radius=RADIUS["md"],
                    padding=ft.Padding.symmetric(horizontal=15, vertical=0), height=54,
                ),
                self.apertura_err,
                self.apertura_hint,
                ft.Container(height=6),
                self.apertura_btn,
                ft.TextButton(
                    content=ft.Text("Salir", size=12, color=COLORS["text_muted"]),
                    on_click=lambda e: self._try_logout(),
                ),
            ], spacing=10, tight=True),
            width=440, padding=ft.Padding.symmetric(horizontal=30, vertical=28),
            bgcolor=COLORS["bg_secondary"], border_radius=RADIUS["lg"],
            border=ft.Border.all(1, COLORS["border"]),
        )

        # Começa visível: até `did_mount` confirmar que há turno aberto, a tela
        # de cobrança fica coberta — nada de cobrar numa caja fechada.
        self.apertura_layer = ft.Container(
            content=card, alignment=ft.Alignment.CENTER, expand=True,
            bgcolor=COLORS["bg_primary"], visible=True,
        )
        return self.apertura_layer

    def did_mount(self):
        threading.Thread(target=self._load_sesion, daemon=True).start()

    def _load_sesion(self):
        """Descobre se o cajero já tem turno aberto e ajusta a tela."""
        try:
            self._sesion = caja_service.actual()
        except APIError as exc:
            self._sesion = None
            self.show_snackbar(friendly_error(exc), error=True)
        self._render_sesion()

    def _render_sesion(self):
        """Mostra a cobrança (turno aberto) ou a tela de apertura (turno fechado)."""
        abierta = bool(self._sesion)
        if abierta:
            # O backend grava a apertura em UTC; o cajero precisa ver a hora dele.
            dt = to_local(self._sesion.get("fecha_apertura"))
            desde = f" · desde {dt:%H:%M}" if dt else ""
            self.caja_chip.content = ft.Text(
                f"CAJA {self._sesion.get('numero_fmt', '?')}{desde}",
                size=12, weight=ft.FontWeight.W_700, color="#CFE4FF",
            )
            self.caja_chip.padding = ft.Padding.symmetric(horizontal=11, vertical=5)
            self.caja_chip.bgcolor = "#0B1834"
            self.caja_chip.border = ft.Border.all(1, "#24406E")
            self.caja_chip.border_radius = RADIUS["sm"]

        self.caja_chip.visible = abierta
        self.cerrar_btn.visible = abierta
        self.apertura_layer.visible = not abierta
        self._u(self.caja_chip)
        self._u(self.cerrar_btn)
        self._u(self.apertura_layer)
        self._guard_window(abierta)

    # --------------------------------------------------- não sair sem cerrar
    def _guard_window(self, abierta: bool):
        """
        Com turno aberto, o X da janela não fecha o app — o dinheiro na gaveta
        precisa ser contado antes. Sem turno aberto, a janela volta ao normal.
        """
        page = self.page
        if not page:
            return
        try:
            page.window.prevent_close = bool(abierta)
            page.window.on_event = self._on_window_event if abierta else None
            page.update()
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] guard_window_failed err={exc}")

    def _on_window_event(self, e):
        if getattr(e, "type", None) == ft.WindowEventType.CLOSE and self._sesion:
            self._warn_caja_abierta("cerrar el sistema")

    def _try_logout(self):
        """Salir só passa com a caja fechada."""
        if self._sesion:
            self._warn_caja_abierta("salir")
            return
        if self.on_logout:
            self.on_logout()

    def _warn_caja_abierta(self, accion: str):
        numero = (self._sesion or {}).get("numero_fmt", "")
        modal = AppModal(
            page=self.page,
            title=f"Caja {numero} abierta",
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.LOCK_OUTLINE, size=20, color=COLORS["accent_warning"]),
                    ft.Text("Tenés un turno abierto.", size=15,
                            weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
                ], spacing=9),
                ft.Text(
                    f"No podés {accion} sin cerrar la caja: hay que contar el efectivo "
                    "y registrar la diferencia. Cerrá el turno y volvé a intentar.",
                    size=13, color=COLORS["text_secondary"],
                ),
            ], spacing=10, tight=True),
            actions=[
                ModalAction("Volver", on_click=lambda e: modal.close()),
                ModalAction("Cerrar caja", primary=True,
                            on_click=lambda e: (modal.close(), self._open_cierre())),
            ],
            width_pct=0.36,
        )
        modal.open()

    def _abrir_caja(self):
        monto = self._parse_amount(self.apertura_monto.value)
        if monto is None:
            monto = 0.0
        if monto < 0:
            self.apertura_err.value = "El monto inicial no puede ser negativo."
            self.apertura_err.visible = True
            self._u(self.apertura_err)
            return

        self.apertura_err.visible = False
        self.apertura_btn.disabled = True
        self._u(self.apertura_err)
        self._u(self.apertura_btn)

        def work():
            try:
                self._sesion = caja_service.abrir(monto)
            except APIError as exc:
                self.apertura_err.value = friendly_error(exc)
                self.apertura_err.visible = True
                self._u(self.apertura_err)
                return
            finally:
                self.apertura_btn.disabled = False
                self._u(self.apertura_btn)

            self.apertura_monto.value = ""
            self._u(self.apertura_monto)
            self._render_sesion()
            self.show_snackbar(f"Caja {self._sesion.get('numero_fmt')} abierta.")
            try:
                self.search_field.focus()
            except Exception:
                pass

        self._bg(work)

    def _open_cierre(self):
        """Modal do cierre: resumo do turno + contagem do efectivo."""
        if not self._sesion:
            return

        resumen = ft.Column([ft.Text("Calculando…", size=13, color=COLORS["text_muted"])],
                            spacing=7, tight=True)
        fisico = ft.TextField(
            value="", hint_text="0", border=ft.InputBorder.NONE, autofocus=True,
            text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        obs = create_text_field("Observaciones (opcional)", width=None)
        err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
        dif_txt = ft.Text("", size=13, weight=ft.FontWeight.W_600, visible=False)
        esperado = {"valor": 0.0}

        def _line(label: str, value: str, strong: bool = False) -> ft.Control:
            return ft.Row([
                ft.Text(label, size=13, color=COLORS["text_secondary"]),
                ft.Container(expand=True),
                ft.Text(value, size=14 if strong else 13,
                        weight=ft.FontWeight.W_700 if strong else ft.FontWeight.W_500,
                        color=COLORS["text_primary"]),
            ])

        def _on_fisico_change(e):
            contado = self._parse_amount(fisico.value)
            if contado is None:
                dif_txt.visible = False
                self._u(dif_txt)
                return
            dif = contado - esperado["valor"]
            if dif == 0:
                dif_txt.value = "Cuadra exacto."
                dif_txt.color = COLORS["accent_success"]
            elif dif > 0:
                dif_txt.value = f"Sobra {_money(dif)}"
                dif_txt.color = COLORS["accent_warning"]
            else:
                dif_txt.value = f"Falta {_money(abs(dif))}"
                dif_txt.color = COLORS["accent_error"]
            dif_txt.visible = True
            self._u(dif_txt)

        fisico.on_change = _on_fisico_change

        modal = AppModal(
            page=self.page,
            title=f"Cerrar Caja {self._sesion.get('numero_fmt', '')}",
            content=ft.Column([
                resumen,
                ft.Divider(height=1, color=COLORS["border_subtle"]),
                ft.Text("EFECTIVO CONTADO", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                ft.Container(
                    content=ft.Row([
                        ft.Text("Gs.", size=16, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                        ft.Container(content=fisico, expand=True),
                    ], spacing=10),
                    bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["border"]),
                    border_radius=RADIUS["md"],
                    padding=ft.Padding.symmetric(horizontal=15, vertical=0), height=50,
                ),
                dif_txt, obs, err,
            ], spacing=11, tight=True),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
                ModalAction("Cerrar caja", primary=True, on_click=lambda e: _cerrar()),
            ],
            width_pct=0.42,
        )

        def _cerrar():
            contado = self._parse_amount(fisico.value)
            if contado is None:
                err.value = "Ingresá el efectivo contado."
                err.visible = True
                self._u(err)
                return

            def work():
                try:
                    cerrada = caja_service.cerrar(contado, (obs.value or "").strip() or None)
                except APIError as exc:
                    err.value = friendly_error(exc)
                    err.visible = True
                    self._u(err)
                    return
                try:
                    modal.close()
                except Exception:
                    pass
                self._sesion = None
                self._reset()
                self._render_sesion()
                self._print_cierre(cerrada)
                dif = float(cerrada.get("diferencia") or 0)
                estado = ("cuadró exacto" if dif == 0
                          else f"sobra {_money(dif)}" if dif > 0
                          else f"falta {_money(abs(dif))}")
                self.show_snackbar(
                    f"Caja {cerrada.get('numero_fmt')} cerrada — {estado}.", error=dif != 0)

            self._bg(work)

        modal.open()

        def load():
            try:
                r = caja_service.preview()
            except APIError as exc:
                resumen.controls = [ft.Text(friendly_error(exc), size=13, color=COLORS["accent_error"])]
                self._u(resumen)
                return
            esperado["valor"] = float(r.get("efectivo_esperado") or 0)
            filas = [
                _line("Abierta", format_local(r.get("fecha_apertura"), "%d/%m/%Y %H:%M")),
                _line("Monto inicial", _money(r.get("monto_inicial"))),
                _line(f"Cobros en efectivo ({r.get('cantidad_pagos', 0)} pagos)",
                      _money(r.get("ingresos_efectivo"))),
            ]
            if float(r.get("ingresos_transferencia") or 0):
                filas.append(_line("Transferencias (no van en la gaveta)",
                                   _money(r.get("ingresos_transferencia"))))
            if float(r.get("ingresos_cheque") or 0):
                filas.append(_line("Cheques (no van en la gaveta)", _money(r.get("ingresos_cheque"))))
            if float(r.get("estornos_efectivo_previos") or 0):
                filas.append(_line("Anulaciones pagadas de esta caja",
                                   f"− {_money(r.get('estornos_efectivo_previos'))}"))
            filas.append(ft.Divider(height=1, color=COLORS["border_subtle"]))
            filas.append(_line("Efectivo esperado", _money(esperado["valor"]), strong=True))
            resumen.controls = filas
            self._u(resumen)

        self._bg(load)

    def _start_clock(self):
        def tick():
            if not self._alive:
                return
            now = datetime.now()
            self._clock.value = f"{_DIA[now.weekday()]} {now:%d/%m/%Y · %H:%M:%S}"
            self._u(self._clock)
            self._clock_timer = threading.Timer(1.0, tick)
            self._clock_timer.daemon = True
            self._clock_timer.start()
        tick()

    def _build_left(self) -> ft.Control:
        self.search_field = create_text_field(
            "", hint_text="Buscar cliente o Nº de factura…", width=None, autofocus=True,
        )
        self.search_field.on_change = self._on_search_change
        self.search_field.on_submit = lambda e: self._bg(self._run_search)
        self.search_results = ft.Column(spacing=6, height=0, scroll=ft.ScrollMode.AUTO)

        # cartão cliente + saldo (ocultos até selecionar)
        self.client_name = ft.Text("", size=21, weight=ft.FontWeight.W_700, color=COLORS["text_primary"])
        self.client_sub = ft.Text("", size=13, color=COLORS["text_secondary"])
        self.client_chip = ft.Container(visible=False)
        self.saldo_big = ft.Text("Gs. 0", size=26, weight=ft.FontWeight.W_800, color=COLORS["text_primary"])
        self.saldo_cnt = ft.Text("", size=13, color=COLORS["text_secondary"])
        self.months_grid = ft.Column(spacing=8)
        self.months_sub = ft.Text("", size=12, color=COLORS["text_secondary"])
        self.mas_meses_btn = ft.TextButton(
            content=ft.Row([
                ft.Icon(ft.Icons.ADD, size=14, color=COLORS["accent_secondary"]),
                ft.Text("Mostrar 12 meses más", size=12, color=COLORS["accent_secondary"]),
            ], spacing=5, tight=True),
            tooltip="Estira la grilla hacia adelante para adelantar meses del año que viene",
            on_click=lambda e: self._mas_meses(),
        )
        self.recent_pays = ft.Column(spacing=0)
        self.consumo_bars = ft.Row(spacing=6, height=58, vertical_alignment=ft.CrossAxisAlignment.END)
        self.consumo_labels = ft.Row(spacing=6)
        self.consumo_foot = ft.Text("", size=12, color=COLORS["text_secondary"])

        self.client_block = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column([self.client_name, self.client_sub], spacing=2, expand=True),
                        self.client_chip,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Divider(height=1, color=COLORS["border_subtle"]),
                ft.Row(
                    [
                        ft.Text("SALDO PENDIENTE", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                        self.saldo_big, self.saldo_cnt,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END, spacing=13,
                ),
                ft.Container(height=4),
                ft.Row([
                    ft.Column([
                        ft.Text("MESES", size=12, weight=ft.FontWeight.W_700,
                                color=COLORS["text_secondary"]),
                        self.months_sub,
                    ], spacing=1, expand=True),
                    ft.TextButton(
                        content=ft.Text("Todo lo que debe", size=12, color=COLORS["accent_secondary"]),
                        on_click=lambda e: self._select_pendientes(),
                    ),
                    ft.TextButton(
                        content=ft.Text("Limpiar", size=12, color=COLORS["text_muted"]),
                        on_click=lambda e: self._clear_selection(),
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
                self.months_grid,
                ft.Row([self.mas_meses_btn], spacing=0),
                ft.Row([
                    self._legend(ft.Icons.CHECK_CIRCLE, COLORS["accent_secondary"], "Entra en este cobro"),
                    self._legend(ft.Icons.RADIO_BUTTON_UNCHECKED, COLORS["accent_warning"], "Debe, fuera del cobro"),
                    self._legend(ft.Icons.ADD_CIRCLE_OUTLINE, COLORS["text_muted"], "Adelanto (mes por venir)"),
                    self._legend(ft.Icons.REMOVE_CIRCLE_OUTLINE, COLORS["text_muted"], "No facturado"),
                    self._legend(ft.Icons.CHECK_CIRCLE, COLORS["accent_success"], "Ya pagado"),
                ], spacing=14, wrap=True),
                ft.Text(
                    "«No facturado» es un mes pasado sin factura emitida — no es deuda. Si lo cobrás, "
                    "el sistema emite la factura mínima en ese momento. Al adelantar meses, deja de "
                    "emitir factura hasta que el período pagado expire; el consumo por encima del "
                    "mínimo se cobra aparte.",
                    size=12, color=COLORS["text_muted"],
                ),
                ft.Container(height=4),
                ft.Row(
                    [
                        self._info_card("ÚLTIMOS PAGOS", self.recent_pays),
                        self._info_card("CONSUMO (m³)", ft.Column(
                            [self.consumo_bars, self.consumo_labels, self.consumo_foot], spacing=6)),
                    ],
                    spacing=10, vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ],
            spacing=SPACING["sm"], visible=False,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row([
                        ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=21),
                        ft.Container(content=self.search_field, expand=True),
                    ], spacing=10),
                    self.search_results,
                    self.client_block,
                ],
                spacing=SPACING["md"], scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding.symmetric(horizontal=26, vertical=20),
            expand=True,
        )

    def _build_right(self) -> ft.Control:
        # Lista item a item do que entra no cobro — o cajero tem que poder ler
        # em voz alta pro cliente antes de apertar o botão.
        self.detail_list = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, height=0)
        self.brk_deuda = ft.Text("Gs. 0", size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"])
        self.brk_adv = ft.Text("Gs. 0", size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"])
        self.brk_adv_n = ft.Text("", size=12, color=COLORS["text_muted"])
        self.brk_adv_lbl = ft.Text("Adelanto", size=13, color=COLORS["text_secondary"])
        self.brk_box = ft.Column([
            ft.Row([ft.Text("Deuda", size=13, color=COLORS["text_secondary"]),
                    ft.Container(expand=True), self.brk_deuda]),
            ft.Row([self.brk_adv_lbl, self.brk_adv_n,
                    ft.Container(expand=True), self.brk_adv]),
        ], spacing=5, visible=False)
        self.total_text = ft.Text("Gs. 0", size=30, weight=ft.FontWeight.W_800, color=COLORS["text_primary"])

        self.recibi_field = ft.TextField(
            value="", hint_text="0", border=ft.InputBorder.NONE,
            text_style=ft.TextStyle(size=24, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_recibi_change,
            on_submit=lambda e: self._confirm(),
        )
        recibi_box = ft.Container(
            content=ft.Row([
                ft.Text("Gs.", size=18, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                ft.Container(content=self.recibi_field, expand=True),
            ], spacing=10),
            bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["border"]),
            border_radius=RADIUS["md"], padding=ft.Padding.symmetric(horizontal=15, vertical=0), height=54,
        )

        quick = ft.Row(
            [self._quick_chip("Exacto", None)] +
            [self._quick_chip(_money(v).replace("Gs. ", ""), v) for v in (100000, 150000, 200000)],
            spacing=7,
        )

        self.vuelto_lbl = ft.Text("VUELTO", size=12, weight=ft.FontWeight.W_700, color="#5FD6AB")
        self.vuelto_val = ft.Text("Gs. 0", size=33, weight=ft.FontWeight.W_800, color=COLORS["accent_success"])
        self.vuelto_box = ft.Container(
            content=ft.Row([self.vuelto_lbl, ft.Container(expand=True), self.vuelto_val],
                           vertical_alignment=ft.CrossAxisAlignment.END),
            padding=ft.Padding.symmetric(horizontal=17, vertical=15), border_radius=RADIUS["lg"],
            bgcolor=ft.Colors.with_opacity(0.12, COLORS["accent_success"]),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.28, COLORS["accent_success"])),
        )

        self.metodo = "EFECTIVO"
        self.metodo_row = ft.Row([
            self._metodo_chip("Efectivo", "EFECTIVO"),
            self._metodo_chip("Transferencia", "TRANSFERENCIA"),
            self._metodo_chip("Cheque", "CHEQUE"),
        ], spacing=8)

        # comprobante: recibo do sistema OU factura legal (SIFEN)
        self.comprobante = "recibo"
        self.comprobante_row = ft.Row(self._comprobante_chips(), spacing=8)
        self.comprobante_help = ft.Text(
            "Recibo del sistema con las facturas cobradas.",
            size=12, color=COLORS["text_muted"],
        )

        self.confirm_text = ft.Text("Cobrar e imprimir", size=16, weight=ft.FontWeight.W_700, color="#FFFFFF")
        self.confirm_btn = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.PRINT_OUTLINED, color="#FFFFFF", size=19),
                self.confirm_text,
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=9),
            height=56, border_radius=RADIUS["md"], bgcolor=COLORS["accent_primary"],
            alignment=ft.Alignment.CENTER, ink=True, on_click=lambda e: self._confirm(),
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("COBRANDO", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    self.detail_list,
                    self.brk_box,
                    ft.Container(
                        content=ft.Row([ft.Text("TOTAL", size=13, weight=ft.FontWeight.W_700, color=COLORS["text_secondary"]),
                                        ft.Container(expand=True), self.total_text],
                                       vertical_alignment=ft.CrossAxisAlignment.END),
                        padding=ft.Padding.symmetric(horizontal=0, vertical=15),
                        border=ft.Border.only(top=ft.BorderSide(1, COLORS["border"]),
                                              bottom=ft.BorderSide(1, COLORS["border"])),
                    ),
                    ft.Text("RECIBÍ", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    recibi_box,
                    quick,
                    self.vuelto_box,
                    ft.Text("MÉTODO", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    self.metodo_row,
                    ft.Text("COMPROBANTE", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    self.comprobante_row,
                    self.comprobante_help,
                    ft.Container(expand=True),
                    self.confirm_btn,
                ],
                spacing=13,
            ),
            width=384, bgcolor=COLORS["bg_secondary"],
            border=ft.Border.only(left=ft.BorderSide(1, COLORS["border"])),
            padding=ft.Padding.symmetric(horizontal=22, vertical=20),
        )

    def _quick_chip(self, label: str, value) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=COLORS["text_secondary"]),
            padding=ft.Padding.symmetric(horizontal=0, vertical=8), expand=True,
            alignment=ft.Alignment.CENTER, bgcolor=COLORS["bg_input"],
            border=ft.Border.all(1, COLORS["border"]), border_radius=RADIUS["sm"], ink=True,
            on_click=lambda e, v=value: self._set_recibi(v),
        )

    def _metodo_chip(self, label: str, value: str) -> ft.Container:
        on = value == getattr(self, "metodo", "EFECTIVO")
        return ft.Container(
            data=value,
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=COLORS["text_primary"] if on else COLORS["text_secondary"]),
            padding=ft.Padding.symmetric(horizontal=0, vertical=10), expand=True,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.14, COLORS["accent_primary"]) if on else COLORS["bg_input"],
            border=ft.Border.all(1, COLORS["accent_primary"] if on else COLORS["border"]),
            border_radius=RADIUS["md"], ink=True, on_click=lambda e, v=value: self._set_metodo(v),
        )

    def _set_metodo(self, value: str):
        self.metodo = value
        self.metodo_row.controls = [
            self._metodo_chip("Efectivo", "EFECTIVO"),
            self._metodo_chip("Transferencia", "TRANSFERENCIA"),
            self._metodo_chip("Cheque", "CHEQUE"),
        ]
        self._u(self.metodo_row)

    def _comprobante_chips(self) -> list:
        chips = []
        for label, value in (("Recibo", "recibo"), ("Factura legal", "factura")):
            on = value == getattr(self, "comprobante", "recibo")
            chips.append(ft.Container(
                content=ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                                color=COLORS["text_primary"] if on else COLORS["text_secondary"]),
                padding=ft.Padding.symmetric(horizontal=0, vertical=9), expand=True,
                alignment=ft.Alignment.CENTER,
                bgcolor=COLORS["bg_elevated"] if on else COLORS["bg_input"],
                border=ft.Border.all(1, COLORS["accent_secondary"] if on else COLORS["border"]),
                border_radius=RADIUS["sm"], ink=True, on_click=lambda e, v=value: self._set_comprobante(v),
            ))
        return chips

    def _set_comprobante(self, value: str):
        self.comprobante = value
        self.comprobante_row.controls = self._comprobante_chips()
        if value == "factura":
            self.comprobante_help.value = "Recibo del sistema + factura legal (KuDE) al emitirse."
            self.confirm_text.value = "Cobrar y emitir factura"
        else:
            self.comprobante_help.value = "Recibo del sistema con las facturas cobradas."
            self.confirm_text.value = "Cobrar e imprimir"
        self._u(self.comprobante_row)
        self._u(self.comprobante_help)
        self._u(self.confirm_text)

    # ---------------------------------------------------------------- busca
    def _on_search_change(self, e):
        q = (self.search_field.value or "").strip()
        if self._search_timer:
            try:
                self._search_timer.cancel()
            except Exception:
                pass
        if len(q) < 2:
            self._results = []
            self._render_results()
            return
        self._search_timer = threading.Timer(0.35, lambda: self._bg(self._run_search))
        self._search_timer.daemon = True
        self._search_timer.start()

    def _run_search(self):
        q = (self.search_field.value or "").strip()
        if len(q) < 2:
            return
        try:
            self._results = client_service.search(query=q, limit=20)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
            return
        self._render_results()

    def _render_results(self):
        rows = []
        for c in self._results:
            rows.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.PERSON, size=16, color=COLORS["text_secondary"]),
                    ft.Column([
                        ft.Text(c.get("nombre_completo", "-"), size=13, color=COLORS["text_primary"],
                                weight=ft.FontWeight.W_500, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"CI {c.get('ci_ruc', '-')} · Med. {c.get('numero_medidor', '-')}",
                                size=11, color=COLORS["text_muted"]),
                    ], spacing=1, expand=True),
                    self._status_chip(c.get("status", "-")),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                bgcolor=COLORS["bg_elevated"], border=ft.Border.all(1, COLORS["border"]),
                border_radius=RADIUS["sm"], ink=True,
                on_click=lambda e, cid=c.get("id"): self._bg(lambda: self._select_client(cid)),
            ))
        if not rows:
            rows = [ft.Text("Ningún cliente encontrado.", size=12, color=COLORS["text_muted"])]
        self.search_results.controls = rows
        self.search_results.height = min(230, 44 * max(1, len(self._results)))
        self._u(self.search_results)

    def _status_chip(self, status: str) -> ft.Container:
        colors = {"ATIVO": COLORS["status_active"], "CORTADO": COLORS["status_cut"],
                  "INATIVO": COLORS["status_inactive"]}
        label = {"ATIVO": "Activo", "CORTADO": "Cortado", "INATIVO": "Inactivo"}.get(status, status)
        col = colors.get(status, COLORS["text_secondary"])
        return ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.W_700, color=col),
            bgcolor=ft.Colors.with_opacity(0.14, col), border=ft.Border.all(1, ft.Colors.with_opacity(0.3, col)),
            padding=ft.Padding.symmetric(horizontal=10, vertical=3), border_radius=RADIUS["pill"],
        )

    # ---------------------------------------------------------------- seleção
    def _select_client(self, client_id: str):
        self._meses_futuro = self.MESES_FUTURO_INICIAL
        try:
            ctx = client_service.get_payment_context(client_id, self._meses_futuro)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
            return
        self._ctx = ctx
        self._tarifa = float(ctx.get("tarifa_base", 0) or 0)
        client = ctx.get("client") or {}

        # monta as células da grade (pendente pré-selecionada)
        self._build_cells(ctx)

        self.client_name.value = client.get("nombre_completo", "-")
        self.client_sub.value = (f"CI {client.get('ci_ruc', '-')} · Medidor {client.get('numero_medidor', '-')} "
                                 f"· Mz {client.get('manzana', '-')}/Lote {client.get('lote', '-')}")
        chip = self._status_chip(client.get("status", "-"))
        self.client_chip.content = chip.content
        self.client_chip.bgcolor = chip.bgcolor
        self.client_chip.border = chip.border
        self.client_chip.padding = chip.padding
        self.client_chip.border_radius = chip.border_radius
        self.client_chip.visible = True

        self.saldo_big.value = _money(ctx.get("saldo_pendiente", 0))
        self.saldo_cnt.value = f"{ctx.get('facturas_pendientes', 0)} facturas"

        self._results = []
        self.search_results.controls = []
        self.search_results.height = 0
        self.client_block.visible = True
        self._render_months()
        self._load_recent(client_id)
        self._load_consumo(client_id)
        # pré-preenche o recibí com o total selecionado
        self._recompute(prefill=True)
        self._u(self.search_results)
        self._u(self.client_block)

    def _build_cells(self, ctx: dict, seleccionados: set | None = None):
        """
        Monta a grade a partir do contexto. `seleccionados` preserva a escolha
        do cajero quando a grade é recarregada com mais meses.
        """
        self._cells = []
        for m in ctx.get("grade_meses", []):
            key = (m["ano"], m["mes"])
            sel = (key in seleccionados) if seleccionados is not None else (m["estado"] == "pendente")
            self._cells.append({
                "ano": m["ano"], "mes": m["mes"], "estado": m["estado"],
                "saldo": float(m.get("saldo", 0) or 0),
                "invoice_ids": m.get("invoice_ids", []),
                "sel": sel and m["estado"] != "pagada",
            })

    def _mas_meses(self):
        """Estica a grade um ano para frente — para adiantar até o ano que vem."""
        if not self._ctx:
            return
        client_id = (self._ctx.get("client") or {}).get("id")
        if not client_id:
            return
        nuevo = min(self.MESES_FUTURO_MAX, self._meses_futuro + 12)
        if nuevo == self._meses_futuro:
            self.show_snackbar("Ya estás en el máximo de meses por adelantar.")
            return

        marcados = {(c["ano"], c["mes"]) for c in self._cells if c["sel"]}

        def work():
            try:
                ctx = client_service.get_payment_context(client_id, nuevo)
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)
                return
            self._meses_futuro = nuevo
            self._ctx = ctx
            self._build_cells(ctx, marcados)
            self._render_months()
            self._recompute()

        self._bg(work)

    def _kind(self, c: dict) -> str:
        """
        Classifica o mês para a UI: `deuda` (tem fatura em aberto), `pagada`,
        `adelanto` (mês atual/futuro sem fatura) ou `sin_factura` (mês que já
        passou e nunca foi faturado — comum no histórico importado).

        A diferença importa: adiantar um mês futuro é rotina; cobrar um mês
        passado sem fatura é decisão do cajero, e vai gerar a fatura na hora.
        """
        if c["estado"] == "pagada":
            return "pagada"
        if c["estado"] == "pendente":
            return "deuda"
        hoy = datetime.now()
        return "sin_factura" if (c["ano"], c["mes"]) < (hoy.year, hoy.month) else "adelanto"

    def _month_cell(self, idx: int, c: dict) -> ft.Control:
        """
        Um mês da grade. O estado tem que ser óbvio de longe: quem está sendo
        cobrado fica preenchido e escrito "Cobrando", o resto se apaga.
        """
        kind = self._kind(c)
        pagada = kind == "pagada"
        selected = c["sel"] and not pagada

        if pagada:
            icon, icon_col = ft.Icons.CHECK_CIRCLE, COLORS["accent_success"]
            estado_txt, estado_col = "Pagado", COLORS["accent_success"]
            valor = "—"
            bg, border_col, border_w = COLORS["bg_input"], COLORS["border_subtle"], 1
        elif selected:
            sufijo = {"adelanto": " (adelanto)", "sin_factura": " (sin factura)"}.get(kind, "")
            icon, icon_col = ft.Icons.CHECK_CIRCLE, COLORS["accent_secondary"]
            estado_txt, estado_col = f"Cobrando{sufijo}", COLORS["accent_secondary"]
            valor = _money(c["saldo"] if kind == "deuda" else self._tarifa)
            bg = ft.Colors.with_opacity(0.16, COLORS["accent_secondary"])
            border_col, border_w = COLORS["accent_secondary"], 2
        elif kind == "adelanto":
            icon, icon_col = ft.Icons.ADD_CIRCLE_OUTLINE, COLORS["text_muted"]
            estado_txt, estado_col = "Adelantar", COLORS["text_muted"]
            valor = _money(self._tarifa)
            bg, border_col, border_w = COLORS["bg_input"], COLORS["border_subtle"], 1
        elif kind == "sin_factura":
            icon, icon_col = ft.Icons.REMOVE_CIRCLE_OUTLINE, COLORS["text_muted"]
            estado_txt, estado_col = "No facturado", COLORS["text_muted"]
            valor = "—"
            bg, border_col, border_w = COLORS["bg_input"], COLORS["border_subtle"], 1
        else:
            icon, icon_col = ft.Icons.RADIO_BUTTON_UNCHECKED, COLORS["accent_warning"]
            estado_txt, estado_col = "Debe", COLORS["accent_warning"]
            valor = _money(c["saldo"])
            bg, border_col, border_w = COLORS["bg_input"], COLORS["accent_warning"], 1

        periodo = f"{_MES[c['mes'] - 1]}/{c['ano']}"
        if pagada:
            tooltip = f"{periodo} · ya pagado"
        elif kind == "sin_factura":
            tooltip = (f"{periodo} · ese mes nunca se facturó. Si lo cobrás, el sistema "
                       f"emite la factura mínima de {_money(self._tarifa)}.")
        elif kind == "adelanto":
            tooltip = f"{periodo} · mes por venir, se cobra adelantado a {_money(self._tarifa)}"
        else:
            tooltip = f"{periodo} · debe {_money(c['saldo'])}"
        if not pagada:
            tooltip += "  —  tocá para " + ("sacarlo del cobro" if c["sel"] else "agregarlo al cobro")

        return ft.Container(
            data=idx,
            content=ft.Column([
                ft.Row([
                    ft.Text(_MES[c["mes"] - 1].upper(), size=13, weight=ft.FontWeight.W_800,
                            color=COLORS["text_muted"] if pagada else COLORS["text_primary"]),
                    ft.Container(expand=True),
                    ft.Icon(icon, size=15, color=icon_col),
                ], spacing=4),
                ft.Text(valor, size=13, weight=ft.FontWeight.W_700,
                        # sem seleção, adelanto e mês pago ficam apagados: só o
                        # que entra no cobro (e o que ele deve) puxa o olho.
                        color=COLORS["text_primary"] if kind == "deuda" else COLORS["text_muted"]),
                ft.Text(estado_txt, size=10, weight=ft.FontWeight.W_600, color=estado_col),
            ], spacing=2),
            width=112, padding=ft.Padding.only(left=10, top=8, right=10, bottom=8),
            bgcolor=bg, border=ft.Border.all(border_w, border_col), border_radius=RADIUS["sm"],
            opacity=0.5 if pagada else (0.75 if kind == "sin_factura" else 1.0),
            ink=not pagada,
            tooltip=tooltip,
            on_click=None if pagada else (lambda e, i=idx: self._toggle_month(i)),
        )

    def _render_months(self):
        """Grade agrupada por ano — o ano fica na lateral, não repetido em cada célula."""
        grupos: dict = {}
        orden = []
        for i, c in enumerate(self._cells):
            if c["ano"] not in grupos:
                grupos[c["ano"]] = []
                orden.append(c["ano"])
            grupos[c["ano"]].append((i, c))

        rows = []
        for ano in orden:
            items = grupos[ano]
            for j in range(0, len(items), 6):
                bloque = items[j:j + 6]
                etiqueta = ft.Container(
                    width=42, alignment=ft.Alignment.CENTER_RIGHT,
                    content=ft.Text(str(ano) if j == 0 else "", size=12,
                                    weight=ft.FontWeight.W_800, color=COLORS["text_muted"]),
                )
                rows.append(ft.Row(
                    [etiqueta] + [self._month_cell(i, c) for i, c in bloque],
                    spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ))

        self.months_grid.controls = rows
        self._u(self.months_grid)
        self.mas_meses_btn.visible = self._meses_futuro < self.MESES_FUTURO_MAX
        self._u(self.mas_meses_btn)
        self._render_months_header()

    def _render_months_header(self):
        """Resumo em texto acima da grade: quantos deve, quantos entram no cobro."""
        pend = [c for c in self._cells if c["estado"] == "pendente"]
        deuda_total = sum(c["saldo"] for c in pend)
        n_sel = len([c for c in self._cells if c["sel"] and c["estado"] != "pagada"])
        if pend:
            self.months_sub.value = (
                f"Debe {len(pend)} {'mes' if len(pend) == 1 else 'meses'} · {_money(deuda_total)}"
                f"  ·  {n_sel} en este cobro"
            )
            self.months_sub.color = COLORS["accent_warning"]
        else:
            self.months_sub.value = f"Sin deuda · {n_sel} en este cobro"
            self.months_sub.color = COLORS["accent_success"]
        self._u(self.months_sub)

    def _toggle_month(self, idx: int):
        self._cells[idx]["sel"] = not self._cells[idx]["sel"]
        self._render_months()
        self._recompute(prefill=True)

    def _select_pendientes(self):
        """Volta à seleção padrão: tudo que ele deve, nada de adelanto."""
        for c in self._cells:
            c["sel"] = c["estado"] == "pendente"
        self._render_months()
        self._recompute(prefill=True)

    def _clear_selection(self):
        for c in self._cells:
            c["sel"] = False
        self._render_months()
        self._recompute(prefill=True)

    def _load_recent(self, client_id: str):
        try:
            pays = payment_service.list_by_client(client_id, limit=3)
        except Exception:
            pays = []
        rows = []
        for p in pays:
            nro = p.get("numero_recibo")
            rec = f"Rec. {int(nro):05d}" if nro not in (None, "") else "Rec. —"
            fecha = format_local(p.get("fecha_pago"), "%d/%m/%Y")
            rows.append(ft.Container(
                content=ft.Row([
                    ft.Text(fecha, size=13, color=COLORS["text_secondary"], width=90),
                    ft.Text(rec, size=11, color=COLORS["text_muted"]),
                    ft.Container(expand=True),
                    ft.Text(_money(p.get("valor_total", 0)), size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
                ], spacing=10),
                padding=ft.Padding.symmetric(horizontal=0, vertical=7),
                border=ft.Border.only(top=ft.BorderSide(1, COLORS["border_subtle"])) if rows else None,
            ))
        if not rows:
            rows = [ft.Text("Sin pagos registrados.", size=12, color=COLORS["text_muted"])]
        self.recent_pays.controls = rows
        self._u(self.recent_pays)

    def _legend(self, icon, color: str, label: str) -> ft.Control:
        return ft.Row([
            ft.Icon(icon, size=13, color=color),
            ft.Text(label, size=11, color=COLORS["text_muted"]),
        ], spacing=5, tight=True)

    def _info_card(self, title: str, body: ft.Control) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [ft.Text(title, size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]), body],
                spacing=9),
            expand=True, bgcolor=COLORS["bg_input"],
            border=ft.Border.all(1, COLORS["border_subtle"]),
            border_radius=RADIUS["md"], padding=13,
        )

    def _load_consumo(self, client_id: str):
        try:
            readings = client_service.get_readings(client_id, limit=6) or []
        except Exception:
            readings = []
        readings = sorted(
            readings, key=lambda r: (r.get("ano_referencia", 0), r.get("mes_referencia", 0)))[-6:]
        vals = [int(r.get("consumo_calculado") or 0) for r in readings]
        if not vals or max(vals) == 0:
            self.consumo_bars.controls = [ft.Text("Sin lecturas.", size=12, color=COLORS["text_muted"])]
            self.consumo_labels.controls = []
            self.consumo_foot.value = ""
        else:
            mx = max(vals)
            bars, labels = [], []
            for i, (r, v) in enumerate(zip(readings, vals)):
                cur = i == len(vals) - 1
                h = max(4, int(round(54 * v / mx)))
                bars.append(ft.Container(
                    expand=True, height=h,
                    border_radius=ft.BorderRadius.only(top_left=3, top_right=3),
                    bgcolor=COLORS["accent_secondary"] if cur else COLORS["bg_elevated"],
                    tooltip=f"{v} m³",
                ))
                labels.append(ft.Container(
                    expand=True,
                    content=ft.Text(_MES[(int(r.get("mes_referencia", 1)) - 1) % 12],
                                    size=9, color=COLORS["text_muted"], text_align=ft.TextAlign.CENTER)))
            self.consumo_bars.controls = bars
            self.consumo_labels.controls = labels
            avg = sum(vals) / len(vals)
            self.consumo_foot.value = f"Lectura {readings[-1].get('valor_leitura', '-')} · Prom. {avg:.1f} m³"
        self._u(self.consumo_bars)
        self._u(self.consumo_labels)
        self._u(self.consumo_foot)

    # ---------------------------------------------------------------- totais
    def _selected_total(self) -> tuple:
        deuda = sum(c["saldo"] for c in self._cells if c["estado"] == "pendente" and c["sel"])
        adv_cells = [c for c in self._cells if c["estado"] == "sem_factura" and c["sel"]]
        adv = self._tarifa * len(adv_cells)
        return deuda, adv, len(adv_cells)

    def _render_detail(self):
        """Uma linha por mês cobrado, na ordem do calendário."""
        rows = []
        for c in self._cells:
            if not c["sel"] or c["estado"] == "pagada":
                continue
            kind = self._kind(c)
            tag = {"deuda": "deuda", "adelanto": "adelanto", "sin_factura": "sin factura"}[kind]
            tag_col = COLORS["accent_warning"] if kind == "deuda" else COLORS["accent_secondary"]
            rows.append(ft.Row([
                ft.Text(f"{_MES[c['mes'] - 1]} {c['ano']}", size=13,
                        weight=ft.FontWeight.W_600, color=COLORS["text_primary"], width=86),
                ft.Text(tag, size=11, color=tag_col),
                ft.Container(expand=True),
                ft.Text(_money(c["saldo"] if kind == "deuda" else self._tarifa), size=13,
                        weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ], spacing=7, height=26))
        if not rows:
            rows = [ft.Container(
                content=ft.Text("Ningún mes seleccionado.", size=12, color=COLORS["text_muted"]),
                height=26,
            )]
        self.detail_list.controls = rows
        self.detail_list.height = min(182, 26 * len(rows))
        self._u(self.detail_list)

    def _recompute(self, prefill: bool = False):
        deuda, adv, adv_n = self._selected_total()
        total = deuda + adv
        self.brk_deuda.value = _money(deuda)
        self.brk_adv.value = _money(adv)
        self.brk_adv_n.value = f"({adv_n} {'mes' if adv_n == 1 else 'meses'})" if adv_n else ""
        # O rótulo segue o que de fato está na conta: adelanto, mês não faturado ou os dois.
        kinds = {self._kind(c) for c in self._cells if c["sel"] and c["estado"] == "sem_factura"}
        self.brk_adv_lbl.value = {
            frozenset({"adelanto"}): "Adelanto",
            frozenset({"sin_factura"}): "Meses no facturados",
        }.get(frozenset(kinds), "Adelanto y no facturados")
        # Só vale a pena separar deuda x adelanto quando há adelanto na conta.
        self.brk_box.visible = adv_n > 0
        self._u(self.brk_adv_lbl)
        self.total_text.value = _money(total)
        self._render_detail()
        self._render_months_header()
        self._u(self.brk_box)
        if prefill:
            self.recibi_field.value = f"{int(round(total))}" if total else ""
            self._u(self.recibi_field)
        self._update_vuelto(total)
        for c in (self.brk_deuda, self.brk_adv, self.brk_adv_n, self.total_text):
            self._u(c)

    def _update_vuelto(self, total: float):
        recibi = self._parse_amount(self.recibi_field.value) or 0
        diff = recibi - total
        if diff >= 0:
            self.vuelto_lbl.value = "VUELTO"
            self.vuelto_val.value = _money(diff)
            self.vuelto_val.color = COLORS["accent_success"]
            self.vuelto_lbl.color = "#5FD6AB"
            self.vuelto_box.bgcolor = ft.Colors.with_opacity(0.12, COLORS["accent_success"])
            self.vuelto_box.border = ft.Border.all(1, ft.Colors.with_opacity(0.28, COLORS["accent_success"]))
        else:
            self.vuelto_lbl.value = "FALTA"
            self.vuelto_val.value = _money(-diff)
            self.vuelto_val.color = COLORS["accent_error"]
            self.vuelto_lbl.color = "#F0899B"
            self.vuelto_box.bgcolor = ft.Colors.with_opacity(0.10, COLORS["accent_error"])
            self.vuelto_box.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, COLORS["accent_error"]))
        self._u(self.vuelto_lbl)
        self._u(self.vuelto_val)
        self._u(self.vuelto_box)

    def _on_recibi_change(self, e):
        deuda, adv, _ = self._selected_total()
        self._update_vuelto(deuda + adv)

    def _set_recibi(self, value):
        deuda, adv, _ = self._selected_total()
        if value is None:  # "Exacto"
            value = deuda + adv
        self.recibi_field.value = f"{int(round(value))}"
        self._u(self.recibi_field)
        self._update_vuelto(deuda + adv)

    # ---------------------------------------------------------------- cobrar
    def _confirm(self):
        if not self._ctx:
            return
        if not self._sesion:
            self.show_snackbar("Abrí la caja antes de cobrar.", error=True)
            return
        deuda, adv, _ = self._selected_total()
        total = deuda + adv
        if total <= 0:
            self.show_snackbar("Seleccioná al menos un mes para cobrar.", error=True)
            return
        recibi = self._parse_amount(self.recibi_field.value)
        if recibi is None or recibi < total:
            self.show_snackbar("El monto recibido no cubre el total.", error=True)
            return

        invoice_ids = []
        prepay = []
        for c in self._cells:
            if not c["sel"]:
                continue
            if c["estado"] == "pendente":
                invoice_ids.extend(c["invoice_ids"])
            elif c["estado"] == "sem_factura":
                prepay.append({"mes": c["mes"], "ano": c["ano"]})

        client = self._ctx.get("client") or {}
        payload = {
            "client_id": client.get("id"),
            "valor_total": total,
            "metodo": self.metodo,
            "aplicar_subsidio": bool(client.get("has_sponsor")),
            "invoice_ids": invoice_ids or None,
            "prepay_periods": prepay or None,
        }

        if self.comprobante == "recibo":
            self.confirm_btn.disabled = True
            self._u(self.confirm_btn)
            self._bg(lambda: self._do_confirm_recibo(payload))
            return

        # Factura legal: SEMPRE confere antes (na thread da UI). Emitida errada, a
        # única saída é cancelación no SET — conferir na tela é muito mais barato.
        self._open_conferencia(client, payload, self._build_factura_items())

    def _do_confirm_recibo(self, payload: dict):
        try:
            result = payment_service.create(payload)
        except APIError as err:
            self.confirm_btn.disabled = False
            self._u(self.confirm_btn)
            self.show_snackbar(friendly_error(err), error=True)
            return
        self._print_documents(result)
        nro = result.get("payment", {}).get("numero_recibo")
        rec = f"{int(nro):05d}" if nro not in (None, "") else "—"
        self.show_snackbar(f"✓ Cobro registrado · Recibo {rec}")
        self._reset()

    # ------------------------------------------------------ factura legal (SIFEN)
    def _build_factura_items(self) -> list:
        company = self._get_company()
        try:
            tasa = int(company.get("iva_tasa_agua", 10) or 10)
        except Exception:
            tasa = 10
        try:
            afect = int(company.get("iva_afectacion_agua", 1) or 1)
        except Exception:
            afect = 1
        items = []
        for c in self._cells:
            if not c["sel"] or c["estado"] not in ("pendente", "sem_factura"):
                continue
            precio = int(round(c["saldo"] if c["estado"] == "pendente" else self._tarifa))
            if precio <= 0:
                continue
            per = f"{_MES[c['mes'] - 1]}/{c['ano']}"
            # Só o mês por vir é adelanto; mês passado sem fatura é serviço comum.
            desc = (f"Servicio de agua (adelanto) {per}" if self._kind(c) == "adelanto"
                    else f"Servicio de agua {per}")
            items.append({"descripcion": desc, "cantidad": 1, "precio_unit": precio,
                          "tasa_iva": tasa, "afectacion": afect, "codigo": "1"})
        return items

    def _needs_conferencia(self, client: dict) -> bool:
        import re
        nombre = (client.get("nombre_completo") or "").strip()
        doc = (client.get("ci_ruc") or "").strip()
        if not nombre or not doc:
            return True
        # doc plausível: 5-10 dígitos, com dígito verificador opcional (ex.: 80012345-6)
        return re.match(r"^\d{5,10}(-\d)?$", doc) is None

    def _open_conferencia(self, client: dict, payload: dict, items: list):
        """
        Última conferência antes de emitir a factura legal.

        Aparece sempre, não só quando falta dado: o KuDE é documento fiscal e, uma
        vez emitido, só sai por cancelación no SET. O cajero vê o receptor e as
        linhas que vão para o SET, e corrige o receptor aqui mesmo.

        Editável é só o receptor. Os itens saem dos meses selecionados na grade e
        o total tem de casar com o cobro que vai ser registrado — mexer no preço
        aqui faria a factura divergir do recibo. Para mudar valores, fecha e muda
        a seleção.
        """
        client_id = client.get("id")
        faltando = self._needs_conferencia(client)

        nombre_field = create_text_field("Nombre o razón social",
                                         value=client.get("nombre_completo") or "", width=None)
        doc_field = create_text_field("RUC / CI", value=client.get("ci_ruc") or "", width=None)
        err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)

        aviso = ft.Text(
            "Faltan datos o el documento es inválido. Corregilos para emitir la factura legal."
            if faltando else
            "Revisá antes de emitir: una vez emitida, la factura solo se anula por cancelación en el SET.",
            size=13,
            color=COLORS["accent_warning"] if faltando else COLORS["text_secondary"],
        )

        # Como o documento VAI SAIR na factura. Sem isto, um RUC activo emitido
        # como CI (sem DV) só aparecia depois, no KuDE — e aí já era documento
        # fiscal. A consulta é a mesma que a emissão faz, então o que se lê aqui
        # é o que sai.
        natureza = ft.Text("", size=12, color=COLORS["text_muted"])

        def _checar_documento(_=None):
            doc_atual = (doc_field.value or "").strip()
            if not doc_atual:
                natureza.value = ""
                natureza.color = COLORS["text_muted"]
                self._u(natureza)
                return
            natureza.value = "Consultando el padrón…"
            natureza.color = COLORS["text_muted"]
            self._u(natureza)

            def work():
                try:
                    r = sifen_service.ruc_lookup(doc_atual) or {}
                except Exception as ex:  # noqa: BLE001 — preview não bloqueia a emissão
                    print(f"[Caja] ruc_lookup_failed err={ex}")
                    natureza.value = "No se pudo consultar el padrón (se emitirá igual)."
                    natureza.color = COLORS["text_muted"]
                    self._u(natureza)
                    return
                if r.get("es_contribuyente"):
                    dv = r.get("dv")
                    natureza.value = (f"✓ RUC activo {r.get('ruc')}"
                                      + (f"-{dv}" if dv is not None else "")
                                      + f" · {r.get('nombre') or '—'} — se emitirá como contribuyente")
                    natureza.color = COLORS["accent_success"]
                elif r.get("found"):
                    natureza.value = (f"RUC {r.get('ruc')} está {r.get('estado')} — "
                                      "se emitirá como CI (sin DV)")
                    natureza.color = COLORS["accent_warning"]
                else:
                    natureza.value = "Sin RUC en el padrón — se emitirá como CI"
                    natureza.color = COLORS["text_muted"]
                self._u(natureza)

            self._bg(work)

        doc_field.on_blur = _checar_documento

        def _linha(it: dict) -> ft.Control:
            total_linha = int(it.get("cantidad", 1) or 1) * int(it.get("precio_unit", 0) or 0)
            return ft.Row([
                ft.Text(it.get("descripcion") or "—", size=12,
                        color=COLORS["text_secondary"], expand=True),
                ft.Text(_money(total_linha), size=12, weight=ft.FontWeight.W_600,
                        color=COLORS["text_primary"]),
            ], spacing=10)

        total_items = sum(int(i.get("cantidad", 1) or 1) * int(i.get("precio_unit", 0) or 0)
                          for i in items)
        detalle = ft.Container(
            content=ft.Column(
                [ft.Text("Detalle de la factura", size=12, weight=ft.FontWeight.W_600,
                         color=COLORS["text_muted"])]
                + [_linha(i) for i in items]
                + [ft.Divider(height=1, color=COLORS["border"]),
                   ft.Row([
                       ft.Text("Total", size=13, weight=ft.FontWeight.W_700,
                               color=COLORS["text_primary"], expand=True),
                       ft.Text(_money(total_items), size=14, weight=ft.FontWeight.W_700,
                               color=COLORS["accent_primary"]),
                   ], spacing=10)],
                spacing=6, tight=True,
            ),
            padding=12,
            border_radius=RADIUS["md"],
            bgcolor=COLORS["bg_elevated"],
        )

        modal = AppModal(
            page=self.page,
            title="Confirmá los datos de la factura",
            content=ft.Column([
                aviso,
                nombre_field, doc_field, natureza, err,
                ft.Text("Lo que edites acá se guarda en la ficha del cliente.",
                        size=12, color=COLORS["text_muted"]),
                detalle,
                ft.Text("Para cambiar montos, cerrá y ajustá los meses seleccionados.",
                        size=11, color=COLORS["text_muted"]),
            ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
                ModalAction("Emitir factura", primary=True, on_click=lambda e: _save_and_emit()),
            ],
            width_pct=0.45,
        )

        def _save_and_emit():
            new_nombre = (nombre_field.value or "").strip()
            new_doc = (doc_field.value or "").strip()
            if not new_nombre or not new_doc:
                err.value = "Completá nombre y documento."
                err.visible = True
                self._u(err)
                return
            if not items:
                err.value = "No hay ítems para facturar."
                err.visible = True
                self._u(err)
                return
            mudou = (new_nombre != (client.get("nombre_completo") or "").strip()
                     or new_doc != (client.get("ci_ruc") or "").strip())
            self.confirm_btn.disabled = True
            self._u(self.confirm_btn)

            def work():
                # Só grava se o cajero realmente editou — confirmar a factura não
                # é motivo para escrever na ficha do cliente.
                if mudou:
                    try:
                        client_service.update(
                            client_id, {"nombre_completo": new_nombre, "ci_ruc": new_doc})
                    except APIError as ex:
                        self.confirm_btn.disabled = False
                        self._u(self.confirm_btn)
                        self.show_snackbar(friendly_error(ex), error=True)
                        return
                    # reflete a edição no contexto local
                    if self._ctx and self._ctx.get("client"):
                        self._ctx["client"]["nombre_completo"] = new_nombre
                        self._ctx["client"]["ci_ruc"] = new_doc
                self._do_confirm_factura(payload, items, new_doc, new_nombre, client_id)

            modal.close()
            self._bg(work)

        modal.open()
        _checar_documento()   # já mostra a natureza do documento ao abrir

    def _do_confirm_factura(self, payload: dict, items: list, doc: str, nombre: str,
                            client_id: str):
        # 1. registra o cobro
        try:
            result = payment_service.create(payload)
        except APIError as err:
            self.confirm_btn.disabled = False
            self._u(self.confirm_btn)
            self.show_snackbar(friendly_error(err), error=True)
            return
        payment_id = (result.get("payment") or {}).get("id")

        # 2. recibo do sistema: o KuDE é o documento legal e não pode ser
        # substituído, mas ele sai só quando a emissão volta EMITIDA (e pode
        # falhar). O recibo é o que o cliente leva na hora.
        self._print_documents(result)

        # 3. enfileira a factura legal na fila/coordenador SIFEN existente
        try:
            job = sifen_service.emitir(
                client_request_id=uuid.uuid4().hex, doc=doc, items=items,
                nombre=nombre, client_id=client_id, payment_id=payment_id,
            )
        except APIError as err:
            self.show_snackbar(
                f"Cobro registrado, pero la factura no se pudo encolar: {friendly_error(err)}",
                error=True)
            self._reset()
            return

        # 4. tela de progresso: a emissão leva alguns segundos e o cajero precisa
        # ver em que passo está (e poder desistir enquanto nada foi assinado).
        emission_id = job.get("id")
        self._reset()
        if emission_id:
            open_sifen_progress(self.page, self.show_snackbar, emission_id=emission_id,
                                receptor=f"{nombre or '-'} · {doc}")
        else:
            self.show_snackbar("✓ Cobro registrado · factura en cola")

    def _reset(self):
        self._ctx = None
        self._cells = []
        self.client_block.visible = False
        self.search_field.value = ""
        self.recibi_field.value = ""
        self.confirm_btn.disabled = False
        self._recompute()
        self._u(self.client_block)
        self._u(self.search_field)
        self._u(self.confirm_btn)

    # ---------------------------------------------------------------- impressão
    def _print_cierre(self, sesion: dict):
        """Comprobante do turno fechado. Falhar aqui não desfaz o cierre (já gravado)."""
        try:
            payload = dict(sesion)
            payload["company"] = self._get_company()
            pdf = self._g_cierre.generate(payload)
            printer_manager.print_pdf(pdf, printer_type="thermal",
                                      job_name=f"cierre_{sesion.get('numero', '')}")
        except Exception as exc:
            print(f"[Caja] print_cierre_failed err={exc}")
            self.show_snackbar("La caja se cerró, pero no se pudo imprimir el comprobante.",
                               error=True)

    def _print_documents(self, result: dict):
        """Recibo único do cobro — não sai uma via de fatura por mês pago.

        O recibo já lista as facturas afectadas e diz no rodapé que comprova o
        pagamento delas, então imprimir a fatura de cada mês só gasta papel.
        """
        company = self._get_company()
        try:
            payload = dict(result)
            payload["company"] = company
            pdf = self._g_receipt.generate(payload)
            group = (result.get("payment", {}).get("grupo_pagamento") or "payment")[:20]
            printer_manager.print_pdf(pdf, printer_type="thermal", job_name=f"receipt_{group}")
        except Exception as exc:
            print(f"[Caja] print_receipt_failed err={exc}")
            self.show_snackbar("No se pudo imprimir el recibo.", error=True)

        if result.get("reactivation_notice_id"):
            try:
                self._print_reactivation(result, company)
            except Exception as exc:
                print(f"[Caja] print_reactivation_failed err={exc}")

    def _print_reactivation(self, result: dict, company: dict):
        notice = cutoff_service.get_notice(result.get("reactivation_notice_id")) or {}
        try:
            taxa = float((company or {}).get("taxa_reativacao", 0) or 0)
        except Exception:
            taxa = 0.0
        deuda = float(result.get("total_debt_before", 0) or 0)
        token = result.get("reactivation_qr_token")
        qr_url = f"{get_api_url().rstrip('/')}/cutoff/qr/{token}/info" if token else None
        payment = result.get("payment", {}) or {}
        pdf = self._g_react.generate({
            "client_name": notice.get("client_nombre", result.get("client_name", "-")),
            "client_ci_ruc": notice.get("client_ci_ruc", result.get("client_ci_ruc", "-")),
            "client_phone": notice.get("client_telefono"),
            "client_address": notice.get("client_direccion", "-"),
            "total_due": deuda, "reativation_fee": taxa, "paid_value": deuda + taxa,
            "notification_date": notice.get("fecha_aviso_gerado") or notice.get("fecha_entrega_aviso"),
            "payment_date": payment.get("fecha_pago"),
            "comprobante": result.get("reactivation_comprobante"),
            "issue_date": datetime.utcnow(), "qr_url": qr_url, "company": company,
        })
        printer_manager.print_pdf(pdf, printer_type="a4", job_name=f"reactivation_{str(result.get('reactivation_notice_id'))[:12]}")
