"""
WMApp Frontend - Modo Caja (cobrança do dia a dia).

Tela do balcão: busca cliente → o que ele deve (meses de água + otros cargos) →
cobro (total ou parcial) → recibo, e factura legal quando for pedida. Marca branca
(logo/nome da junta vêm de SystemSettings).

Premissa que manda no desenho: **a junta não tem setores.** Quem está no caixa
cadastra, cobra, corrige, parcela e administra. Nenhum fluxo depende de "outra
pessoa resolve depois", e por isso a tela tem tudo:

- cadastro de cliente completo, aberto de dentro da cobrança (Fase 1);
- otros cargos da tesouraria (faturas AVULSA) na mesma conta (Fase 2.1), e o
  cargo de **valor livre lançado no balcão** quando ninguém lançou antes;
- cobro parcial: "valor a cobrar" separado de "recibí" (Fase 2.2);
- acuerdo de pago / parcelamento (Fase 3);
- anular cobro no próprio balcão, com motivo (Fase 4);
- reimprimir recibo e KuDE de atendimentos anteriores (Fase 5);
- sangría, reposición, resumo do turno e cierre às cegas (Fase 6);
- teclado ponta a ponta e atendimentos em espera (Fase 7).

Quem só tem o escopo `caja` cai aqui direto no login (tela cheia, sem menu). Quem
tem acesso amplo entra pelo módulo do menu e volta com «Volver al menú»
(`on_exit`).

Reusa a infra já pronta:
- GET /clients/{id}/payment-context  → grade_meses + otros_cargos + saldo + acuerdo
- POST /payments/  com invoice_ids (direcionado) e prepay_periods (adiantamento)
- Impressão P80 (mesmos geradores do payments_view)
"""

import threading
import uuid
from datetime import datetime

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.caja_acuerdo import open_acuerdo_dialog
from components.caja_atenciones import open_atenciones_dialog
from components.caja_cargo import open_cargo_dialog
from components.caja_efectivo import (
    REPOSICION, SANGRIA, open_movimiento_dialog, open_resumen_dialog,
)
from components.client_form import open_client_form
from components.sifen_progress import open_sifen_progress
from components.theme import COLORS, SPACING, RADIUS, create_text_field
from services.sifen_service import sifen_service
from config.local_settings import get_api_url
from services.api_client import APIError
from services.auth_service import auth_service
from services.caja_service import caja_service
from services.client_service import client_service
from services.cutoff_service import cutoff_service
from services.invoice_service import invoice_service
from services.payment_service import payment_service
from services.settings_service import settings_service
from services.pdf_generation.finance import CierreCajaP80Generator
from services.pdf_generation.invoices import InvoiceP80Generator
from services.pdf_generation.receipts import PaymentReceiptP80Generator
from services.pdf_generation.notifications import ReactivationRequestGenerator
from services.pdf_generation.printer_manager import printer_manager
from utils.errors import friendly_error
from utils.formatters import format_currency, format_local, to_local
from i18n import t

_MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
_DIA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

# Fim do mundo para ordenar: pseudo-fatura de adiantamento (que ainda não existe)
# entra depois das faturas reais do mesmo período, igual ao backend, que a cria
# agora e ordena por fecha_emision.
_FUTURO = "9999-12-31T23:59:59"


def _money(v) -> str:
    return format_currency(v or 0, "Gs.")


class CajaView(ft.Container):
    """Layout de tela cheia do Modo Caja."""

    # Janela futura da grade de meses: começa em 6 e o cajero estica de 12 em 12
    # (teto igual ao do endpoint, que recusa mais que isso).
    MESES_FUTURO_INICIAL = 6
    MESES_FUTURO_MAX = 36

    # Busca: poucos resultados de propósito (a lista tem de caber na tela), mas
    # com o total à vista — esconder do 5º em diante sem avisar era o defeito.
    BUSCA_LIMIT = 20
    BUSCA_ALTURA_FILA = 50   # dois textos + padding 8+8
    BUSCA_ESPACIO = 6
    BUSCA_ALTURA_MAX = 340

    def __init__(self, show_snackbar, current_user: dict, on_logout=None, on_exit=None):
        super().__init__()
        self.show_snackbar = show_snackbar
        self.current_user = current_user or {}
        self.on_logout = on_logout
        # `on_exit` só existe quando a caja foi aberta pelo menu: aí ela é um
        # módulo e tem para onde voltar. No cajero dedicado ele é None.
        self.on_exit = on_exit

        self.expand = True
        self.bgcolor = COLORS["bg_primary"]

        self._alive = True
        self._clock_timer = None
        self._company = None
        self._search_timer = None
        # Corrida entre buscas: cada busca leva um número e o resultado só entra
        # na tela se ainda for o mais novo. Sem isto, a resposta de "jo" chegava
        # depois de "josé" e sobrescrevia a lista certa.
        self._search_seq = 0
        self._search_total = 0

        # turno de caja aberto (None = nada cobrável, mostra a tela de apertura)
        self._sesion = None
        self._pausado = False

        # estado da cobrança atual
        self._ctx = None            # payment-context do cliente selecionado
        self._cells = []            # [{ano,mes,estado,saldo,invoice_ids,sel}]
        self._cargos = []           # otros cargos (AVULSA): [{'f': factura, 'sel': bool}]
        self._facturas = {}         # id -> factura (para o reparto e a factura legal)
        self._tarifa = 0.0
        self._results = []
        self._meses_futuro = self.MESES_FUTURO_INICIAL

        # atendimentos em espera (só na memória do app: nada foi cobrado ainda)
        self._espera = []

        # dialogs abertos por esta tela — os atalhos de teclado não disparam
        # enquanto algum estiver na frente.
        self._dialogs = []
        self._prev_keyboard_handler = None

        # geradores de PDF (mesmos do payments_view)
        self._g_receipt = PaymentReceiptP80Generator()
        self._g_react = ReactivationRequestGenerator()
        self._g_cierre = CierreCajaP80Generator()
        self._g_invoice = InvoiceP80Generator()

        self._build()

    # ---------------------------------------------------------------- helpers
    def _u(self, ctrl: ft.Control):
        try:
            ctrl.update()
        except Exception:
            pass

    def _pagina(self):
        """
        A página, ou `None` se esta view não está (mais) na tela.

        `self.page` **levanta** `RuntimeError` fora da árvore no Flet 0.86 — não
        devolve `None`. Quem lia o atributo direto quebrava justamente no
        caminho de saída (`stop()` no logout, chamado depois de a caja já ter
        sido tirada da tela), e o logout morria no meio.
        """
        try:
            return self.page
        except Exception:
            return None

    def _bg(self, fn):
        page = self._pagina()
        if page is not None:
            try:
                page.run_thread(fn)
                return
            except Exception:
                pass
        fn()

    def _focus(self, ctrl: ft.Control):
        """
        Põe o cursor num campo.

        `focus()` é **corrotina** no Flet 0.86: chamada solta ela nunca roda (só
        deixa um RuntimeWarning) e o cursor não vai para lugar nenhum — o que num
        balcão que trabalha por teclado quebra o ritmo inteiro. Quem agenda é a
        página, com `run_task`.
        """
        page = self._pagina()
        if page is None:
            return
        try:
            page.run_task(ctrl.focus)
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] focus_failed err={exc}")

    def _track(self, modal, esc_cierra: bool = True):
        """
        Guarda o dialog para os atalhos saberem que há algo na frente.

        `esc_cierra=False` para telas que não podem ser largadas com um Esc
        distraído (a emissão da factura legal é a única: fechá-la às cegas deixa
        o cajero sem saber se o KuDE saiu).
        """
        self._podar_dialogs()
        if modal is not None:
            self._dialogs.append((modal, esc_cierra))
        return modal

    def _podar_dialogs(self):
        self._dialogs = [d for d in self._dialogs if getattr(d[0], "is_open", False)]

    def _sin_dialogs(self) -> bool:
        self._podar_dialogs()
        return not self._dialogs

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
        self._restore_keyboard()
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

        # Ações do turno: tudo o que o balcão resolve sozinho.
        self.acciones_row = ft.Row([
            self._accion(ft.Icons.HISTORY, "Atenciones anteriores — reimprimir o anular (F5)",
                         self._open_atenciones),
            self._accion(ft.Icons.SUMMARIZE_OUTLINED, "Resumen del turno (F6)",
                         self._open_resumen),
            self._accion(ft.Icons.CALL_MADE, "Sangría: sacar plata de la gaveta (F9)",
                         lambda: self._open_movimiento(SANGRIA)),
            self._accion(ft.Icons.CALL_RECEIVED, "Reposición: devolver plata a la gaveta",
                         lambda: self._open_movimiento(REPOSICION)),
            self._accion(ft.Icons.PAUSE_CIRCLE_OUTLINE,
                         "Pausar el cobro sin cerrar la caja (F11)", self._pausar),
            self._accion(ft.Icons.KEYBOARD_OUTLINED,
                         "Atajos del teclado", self._open_atajos),
        ], spacing=2, visible=False)

        salida_btn = (
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.ARROW_BACK, size=15, color=COLORS["text_muted"]),
                    ft.Text("Volver al menú", size=12, color=COLORS["text_muted"]),
                ], spacing=6, tight=True),
                on_click=lambda e: self._volver_al_menu(),
            )
            if self.on_exit else
            ft.TextButton(
                content=ft.Text("Salir", size=12, color=COLORS["text_muted"]),
                on_click=lambda e: self._try_logout(),
            )
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
                    self.acciones_row,
                    self.caja_chip,
                    self._clock,
                    ft.Container(width=1, height=20, bgcolor=COLORS["border"]),
                    ft.Text(
                        f"Cajero: {self.current_user.get('full_name') or self.current_user.get('username', '')}",
                        size=13, color=COLORS["text_secondary"],
                    ),
                    self.cerrar_btn,
                    salida_btn,
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
        # A apertura (e a pausa) cobrem a cobrança inteira: sem turno aberto, ou
        # com o turno pausado, não se cobra nada. StackFit.EXPAND para as camadas
        # ocuparem a tela toda (o default LOOSE deixaria só o tamanho do card).
        self.content = ft.Stack(
            [cobranza, self._build_apertura(), self._build_pausa()],
            expand=True, fit=ft.StackFit.EXPAND,
        )
        self._start_clock()

    def _accion(self, icon, tooltip: str, on_click) -> ft.Control:
        return ft.IconButton(
            icon=icon, icon_size=18, tooltip=tooltip,
            icon_color=COLORS["text_secondary"],
            on_click=lambda e: on_click(),
        )

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

        acciones = [
            self.apertura_btn,
        ]
        if self.on_exit:
            acciones.append(ft.TextButton(
                content=ft.Text("Volver al menú", size=12, color=COLORS["text_muted"]),
                on_click=lambda e: self._volver_al_menu(),
            ))
        else:
            acciones.append(ft.TextButton(
                content=ft.Text("Salir", size=12, color=COLORS["text_muted"]),
                on_click=lambda e: self._try_logout(),
            ))

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
                *acciones,
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

    # ------------------------------------------------------------- pausa
    def _build_pausa(self) -> ft.Control:
        """
        Pausa do turno: o cajero sai do balcão sem cerrar a caja.

        A gaveta continua aberta e no nome dele, então quem destranca é ele — com
        a própria senha. É uma pausa nas cobranças, não uma troca de dono: o
        cierre segue sendo do mesmo operador, com o esperado acumulado do turno.
        """
        self.pausa_pass = ft.TextField(
            value="", password=True, can_reveal_password=True,
            hint_text="Tu contraseña", border=ft.InputBorder.NONE,
            text_style=ft.TextStyle(size=17, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            on_submit=lambda e: self._reanudar(),
        )
        self.pausa_err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
        self.pausa_info = ft.Text("", size=13, color=COLORS["text_secondary"])

        card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.PAUSE_CIRCLE_OUTLINE, size=26,
                            color=COLORS["accent_warning"]),
                    ft.Text("Caja en pausa", size=25, weight=ft.FontWeight.W_800,
                            color=COLORS["text_primary"]),
                ], spacing=10),
                self.pausa_info,
                ft.Text("El turno sigue abierto. Nadie cobra hasta que vuelvas.",
                        size=13, color=COLORS["text_muted"]),
                ft.Container(height=8),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.LOCK_OUTLINE, size=18, color=COLORS["text_muted"]),
                        ft.Container(content=self.pausa_pass, expand=True),
                    ], spacing=10),
                    bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["border"]),
                    border_radius=RADIUS["md"],
                    padding=ft.Padding.symmetric(horizontal=15, vertical=0), height=52,
                ),
                self.pausa_err,
                ft.Container(height=4),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PLAY_ARROW, color="#FFFFFF", size=19),
                        ft.Text("Volver a cobrar", size=16, weight=ft.FontWeight.W_700,
                                color="#FFFFFF"),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=9),
                    height=54, border_radius=RADIUS["md"], bgcolor=COLORS["accent_primary"],
                    alignment=ft.Alignment.CENTER, ink=True,
                    on_click=lambda e: self._reanudar(),
                ),
            ], spacing=9, tight=True),
            width=430, padding=ft.Padding.symmetric(horizontal=30, vertical=28),
            bgcolor=COLORS["bg_secondary"], border_radius=RADIUS["lg"],
            border=ft.Border.all(1, COLORS["border"]),
        )
        self.pausa_layer = ft.Container(
            content=card, alignment=ft.Alignment.CENTER, expand=True,
            bgcolor=COLORS["bg_primary"], visible=False,
        )
        return self.pausa_layer

    def _pausar(self):
        if not self._sesion:
            return
        self._pausado = True
        numero = self._sesion.get("numero_fmt", "")
        self.pausa_info.value = f"Caja {numero} · {self.current_user.get('full_name') or self.current_user.get('username', '')}"
        self.pausa_pass.value = ""
        self.pausa_err.visible = False
        self.pausa_layer.visible = True
        self._u(self.pausa_info)
        self._u(self.pausa_pass)
        self._u(self.pausa_err)
        self._u(self.pausa_layer)
        self._focus(self.pausa_pass)

    def _reanudar(self):
        senha = self.pausa_pass.value or ""
        if not senha:
            self.pausa_err.value = "Ingresá tu contraseña para volver."
            self.pausa_err.visible = True
            self._u(self.pausa_err)
            return

        def work():
            if not auth_service.verify_password(senha):
                self.pausa_err.value = "Contraseña incorrecta."
                self.pausa_err.visible = True
                self.pausa_pass.value = ""
                self._u(self.pausa_err)
                self._u(self.pausa_pass)
                return
            self._pausado = False
            self.pausa_pass.value = ""
            self.pausa_err.visible = False
            self.pausa_layer.visible = False
            self._u(self.pausa_pass)
            self._u(self.pausa_err)
            self._u(self.pausa_layer)
            self._focus(self.search_field)

        self._bg(work)

    def did_mount(self):
        self._install_keyboard()
        threading.Thread(target=self._load_sesion, daemon=True).start()

    def will_unmount(self):
        self._restore_keyboard()

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
        self.acciones_row.visible = abierta
        self.apertura_layer.visible = not abierta
        self._u(self.caja_chip)
        self._u(self.cerrar_btn)
        self._u(self.acciones_row)
        self._u(self.apertura_layer)
        self._guard_window(abierta)

    # --------------------------------------------------- não sair sem cerrar
    def _guard_window(self, abierta: bool):
        """
        Com turno aberto, o X da janela não fecha o app — o dinheiro na gaveta
        precisa ser contado antes. Sem turno aberto, a janela volta ao normal.
        """
        page = self._pagina()
        if page is None:
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

    def _volver_al_menu(self):
        """
        Volta ao menu. O turno pode ficar aberto — o cajero só saiu da tela.

        Quem impede fechar o app com a gaveta aberta é o guard da janela, que
        `main.py` mantém instalado enquanto houver turno aberto.
        """
        if self._sesion:
            self.show_snackbar(
                f"La Caja {self._sesion.get('numero_fmt', '')} sigue abierta — "
                "volvé para cerrarla al final del turno.")
        if self.on_exit:
            self.on_exit(self._sesion)

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
        self._track(modal)
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
            self._focus(self.search_field)

        self._bg(work)

    def _open_cierre(self):
        """
        Cierre às cegas: o cajero digita o que contou ANTES de ver o esperado.

        Mostrar o esperado primeiro transforma a contagem numa conferência de
        gabarito — quem conta olhando o número certo tende a "achar" que fecha.
        Só depois de registrar a contagem aparecem o esperado e a diferença.
        """
        if not self._sesion:
            return

        fisico = ft.TextField(
            value="", hint_text="0", border=ft.InputBorder.NONE, autofocus=True,
            text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=lambda e: _revelar(),
        )
        obs = create_text_field("Observaciones (opcional)", width=None)
        err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
        resumen = ft.Column(spacing=7, tight=True, visible=False)
        estado = {"esperado": None, "revelado": False}

        ciego_hint = ft.Text(
            "Contá la plata de la gaveta y escribí el total. El sistema te muestra "
            "después lo que esperaba, para que la cuenta sea tuya y no una copia.",
            size=12, color=COLORS["text_muted"],
        )

        def _line(label: str, value: str, strong: bool = False) -> ft.Control:
            return ft.Row([
                ft.Text(label, size=13, color=COLORS["text_secondary"]),
                ft.Container(expand=True),
                ft.Text(value, size=14 if strong else 13,
                        weight=ft.FontWeight.W_700 if strong else ft.FontWeight.W_500,
                        color=COLORS["text_primary"]),
            ])

        def _pintar_resumen(r: dict, contado: float):
            esperado = float(r.get("efectivo_esperado") or 0)
            estado["esperado"] = esperado
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
            if float(r.get("sangrias_total") or 0):
                filas.append(_line(f"Sangrías ({r.get('sangrias_cantidad', 0)})",
                                   f"− {_money(r.get('sangrias_total'))}"))
            if float(r.get("reposiciones_total") or 0):
                filas.append(_line(f"Reposiciones ({r.get('reposiciones_cantidad', 0)})",
                                   _money(r.get("reposiciones_total"))))
            filas.append(ft.Divider(height=1, color=COLORS["border_subtle"]))
            filas.append(_line("Efectivo esperado", _money(esperado), strong=True))
            filas.append(_line("Efectivo contado", _money(contado), strong=True))

            dif = contado - esperado
            if dif == 0:
                txt, col = "Cuadra exacto.", COLORS["accent_success"]
            elif dif > 0:
                txt, col = f"Sobra {_money(dif)}", COLORS["accent_warning"]
            else:
                txt, col = f"Falta {_money(abs(dif))}", COLORS["accent_error"]
            filas.append(ft.Text(txt, size=15, weight=ft.FontWeight.W_700, color=col))
            if dif != 0:
                filas.append(ft.Text(
                    "Anotá en las observaciones qué explica la diferencia — el cierre "
                    "queda guardado como está.", size=12, color=COLORS["text_muted"]))
            resumen.controls = filas
            resumen.visible = True
            ciego_hint.visible = False
            self._u(resumen)
            self._u(ciego_hint)
            modal.update()

        def _revelar():
            contado = self._parse_amount(fisico.value)
            if contado is None:
                err.value = "Ingresá el efectivo contado."
                err.visible = True
                self._u(err)
                return
            err.visible = False
            self._u(err)

            def work():
                try:
                    r = caja_service.preview()
                except APIError as exc:
                    err.value = friendly_error(exc)
                    err.visible = True
                    self._u(err)
                    return
                estado["revelado"] = True
                _pintar_resumen(r, contado)

            self._bg(work)

        def _cerrar():
            contado = self._parse_amount(fisico.value)
            if contado is None:
                err.value = "Ingresá el efectivo contado."
                err.visible = True
                self._u(err)
                return
            if not estado["revelado"]:
                _revelar()
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
                est = ("cuadró exacto" if dif == 0
                       else f"sobra {_money(dif)}" if dif > 0
                       else f"falta {_money(abs(dif))}")
                self.show_snackbar(
                    f"Caja {cerrada.get('numero_fmt')} cerrada — {est}.", error=dif != 0)

            self._bg(work)

        modal = AppModal(
            page=self.page,
            title=f"Cerrar Caja {self._sesion.get('numero_fmt', '')}",
            content=ft.Column([
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
                ciego_hint,
                resumen,
                obs, err,
            ], spacing=11, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
                ModalAction("Ver esperado", on_click=lambda e: _revelar()),
                ModalAction("Cerrar caja", primary=True, on_click=lambda e: _cerrar()),
            ],
            width_pct=0.42,
        )
        self._track(modal)
        modal.open()

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

    # ------------------------------------------------------------- teclado
    def _install_keyboard(self):
        """
        Atalhos do balcão. Só teclas de função e Esc: o resto do ritmo é o
        próprio Enter dos campos (buscar → seleccionar → valor → cobrar).

        Não disparam com um dialog na frente — senão F5 abriria uma tela em cima
        da outra.
        """
        page = self._pagina()
        if page is None:
            return
        try:
            self._prev_keyboard_handler = getattr(page, "on_keyboard_event", None)
            page.on_keyboard_event = self._on_key
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] keyboard_hook_failed err={exc}")

    def _restore_keyboard(self):
        page = self._pagina()
        if page is None:
            return
        try:
            page.on_keyboard_event = self._prev_keyboard_handler
        except Exception:
            pass

    # Atalhos do turno, na ordem em que aparecem no painel de ajuda.
    ATAJOS = [
        ("F1", "Registrar cliente nuevo"),
        ("F2", "Marcar todo lo que debe"),
        ("F3", "Limpiar la selección"),
        ("F4", "Plan de pagos (acuerdo)"),
        ("F5", "Atenciones anteriores"),
        ("F6", "Resumen del turno"),
        ("F7", "Dejar en espera"),
        ("F8", "Retomar el primero en espera"),
        ("F9", "Sangría de la gaveta"),
        ("F10", "Cerrar caja"),
        ("F11", "Pausar la caja"),
        ("F12", "Cargo nuevo (valor libre)"),
        ("Enter", "Buscar → primer cliente → cobrar"),
        ("Esc", "Volver un paso atrás"),
    ]

    def _on_key(self, e):
        key = getattr(e, "key", "")
        # Esc é o único que trabalha com dialog na frente: é ele que fecha.
        if key == "Escape":
            try:
                self._escape()
            except Exception as exc:  # noqa: BLE001
                print(f"[Caja] escape_failed err={exc}")
            return
        if not self._sin_dialogs() or self._pausado:
            return
        if not self._sesion:
            return
        acciones = {
            "F1": self._nuevo_cliente_desde_busqueda,
            "F2": self._select_pendientes,
            "F3": self._clear_selection,
            "F4": self._open_acuerdo,
            "F5": self._open_atenciones,
            "F6": self._open_resumen,
            "F7": self._parkear,
            "F8": self._retomar,
            "F9": lambda: self._open_movimiento(SANGRIA),
            "F10": self._open_cierre,
            "F11": self._pausar,
            "F12": self._open_cargo,
        }
        fn = acciones.get(key)
        if not fn:
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] shortcut_failed key={key} err={exc}")

    # ------------------------------------------------------------- Esc
    def _escape(self):
        """
        Esc é o «volver» do balcão: um passo atrás por vez, nunca dois.

        A ordem importa. Antes, Esc só sabia largar o atendimento — e como os
        dialogs deste app são `modal=True` (o barrier não dispensa), Esc com uma
        tela aberta na frente não fazia nada: o cajero tinha de achar o
        «Cancelar» com o mouse, o que num balcão que trabalha por teclado é o
        passo que quebra o ritmo.

        1. dialog na frente  → fecha o de cima (e só ele);
        2. atendimento aberto → larga e volta o foco à busca;
        3. busca digitada    → limpa a busca;
        4. tela limpa        → devolve o cursor à busca.

        Não sai da caja nem cancela um cobro já enviado: Esc é para desfazer o
        que ainda é intenção, não o que já é dinheiro.
        """
        self._podar_dialogs()
        if self._dialogs:
            # O último aberto é o de cima. `page.pop_dialog()` fecha o topo real
            # da pilha da página — inclusive um prompt aberto de dentro de outro
            # dialog, que esta lista não conhece.
            if not self._dialogs[-1][1]:
                return
            page = self._pagina()
            try:
                if page is not None:
                    page.pop_dialog()
            except Exception as exc:  # noqa: BLE001
                print(f"[Caja] esc_pop_dialog_failed err={exc}")
            return

        # A pausa só sai com a senha do cajero — Esc não é a porta dos fundos.
        if self._pausado or not self._sesion:
            return

        if self._ctx:
            self._nuevo_atendimiento()
            return

        if (self.search_field.value or "").strip():
            self.search_field.value = ""
            self._results = []
            self._search_total = 0
            self._render_results()
            self._u(self.search_field)

        self._focus(self.search_field)

    def _open_atajos(self):
        """Painel com os atalhos — o teclado do balcão precisa de onde ser lido."""
        filas = [
            ft.Row([
                ft.Container(
                    content=ft.Text(tecla, size=12, weight=ft.FontWeight.W_800,
                                    color="#CFE4FF"),
                    width=54, alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    bgcolor="#0B1834", border=ft.Border.all(1, "#24406E"),
                    border_radius=RADIUS["sm"],
                ),
                ft.Text(texto, size=13, color=COLORS["text_secondary"], expand=True),
            ], spacing=11, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            for tecla, texto in self.ATAJOS
        ]
        modal = AppModal(
            page=self.page,
            title="Atajos del mostrador",
            content=ft.Column(
                filas + [
                    ft.Container(height=4),
                    ft.Text("Los atajos no disparan mientras hay una ventana abierta "
                            "adelante — ahí Esc la cierra.",
                            size=12, color=COLORS["text_muted"]),
                ],
                spacing=8, tight=True, scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
            width_pct=0.36,
        )
        self._track(modal)
        modal.open()

    def _nuevo_atendimiento(self):
        """Larga o atendimento atual e volta o foco para a busca."""
        self._reset()
        self._focus(self.search_field)

    # ------------------------------------------------------------- esquerda
    def _build_left(self) -> ft.Control:
        self.search_field = create_text_field(
            "", hint_text="Buscar cliente o Nº de factura…", width=None, autofocus=True,
        )
        self.search_field.on_change = self._on_search_change
        self.search_field.on_submit = lambda e: self._on_search_submit()
        self.search_results = ft.Column(spacing=self.BUSCA_ESPACIO, height=0,
                                        scroll=ft.ScrollMode.AUTO)
        self.search_footer = ft.Row([], spacing=9, visible=False, wrap=True)

        # Atendimentos em espera: o cliente foi buscar dinheiro no carro, o
        # próximo já está no balcão.
        self.espera_row = ft.Row([], spacing=7, wrap=True, visible=False)

        # cartão cliente + saldo (ocultos até selecionar)
        self.client_name = ft.Text("", size=21, weight=ft.FontWeight.W_700, color=COLORS["text_primary"])
        self.client_sub = ft.Text("", size=13, color=COLORS["text_secondary"])
        self.client_chip = ft.Container(visible=False)
        self.saldo_big = ft.Text("Gs. 0", size=26, weight=ft.FontWeight.W_800, color=COLORS["text_primary"])
        self.saldo_cnt = ft.Text("", size=13, color=COLORS["text_secondary"])
        self.acuerdo_box = ft.Container(visible=False)
        self.cargos_list = ft.Column(spacing=6)
        self.cargos_block = ft.Column(spacing=6, visible=False)
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

        self.cargos_block.controls = [
            ft.Row([
                ft.Column([
                    ft.Text("OTROS CARGOS", size=12, weight=ft.FontWeight.W_700,
                            color=COLORS["text_secondary"]),
                    ft.Text("Reconexión, materiales, cuota de conexión… No es "
                            "consumo de agua.",
                            size=11, color=COLORS["text_muted"]),
                ], spacing=1, expand=True),
                # O balcão também lança: a junta não tem setores, e quem cobra é
                # quem tem de poder faturar o que ninguém lançou antes.
                ft.TextButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ADD_CARD, size=15,
                                color=COLORS["accent_secondary"]),
                        ft.Text("Cargo nuevo (F12)", size=12,
                                color=COLORS["accent_secondary"]),
                    ], spacing=6, tight=True),
                    tooltip="Facturar acá mismo un cargo con valor libre",
                    on_click=lambda e: self._open_cargo(),
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
            self.cargos_list,
        ]

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
                # Rótulo em cima, montante embaixo. Antes era tudo na mesma Row
                # com `vertical_alignment=END`, e alinhar pelo rodapé da caixa de
                # texto três tamanhos diferentes (11/26/13) deixava as linhas de
                # base escalonadas — o "torto". Flet não expõe `text_baseline` na
                # Row, então CrossAxisAlignment.BASELINE não é opção: quem
                # resolve é o empilhamento.
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("SALDO PENDIENTE", size=11,
                                        weight=ft.FontWeight.W_700,
                                        color=COLORS["text_muted"]),
                                self.saldo_big,
                                self.saldo_cnt,
                            ],
                            spacing=1, expand=True,
                        ),
                        ft.TextButton(
                            content=ft.Row([
                                ft.Icon(ft.Icons.CALENDAR_MONTH, size=15,
                                        color=COLORS["accent_secondary"]),
                                ft.Text("Plan de pagos (F4)", size=12,
                                        color=COLORS["accent_secondary"]),
                            ], spacing=6, tight=True),
                            tooltip="Parcelar la deuda en cuotas",
                            on_click=lambda e: self._open_acuerdo(),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=13,
                ),
                self.acuerdo_box,
                self.cargos_block,
                ft.Container(height=2),
                ft.Row([
                    ft.Column([
                        ft.Text("MESES DE AGUA", size=12, weight=ft.FontWeight.W_700,
                                color=COLORS["text_secondary"]),
                        self.months_sub,
                    ], spacing=1, expand=True),
                    ft.TextButton(
                        content=ft.Text("Todo lo que debe (F2)", size=12, color=COLORS["accent_secondary"]),
                        on_click=lambda e: self._select_pendientes(),
                    ),
                    ft.TextButton(
                        content=ft.Text("Limpiar (F3)", size=12, color=COLORS["text_muted"]),
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
                    self.espera_row,
                    ft.Row([
                        ft.Icon(ft.Icons.SEARCH, color=COLORS["text_muted"], size=21),
                        ft.Container(content=self.search_field, expand=True),
                    ], spacing=10),
                    self.search_results,
                    self.search_footer,
                    self.client_block,
                ],
                spacing=SPACING["md"], scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding.symmetric(horizontal=26, vertical=20),
            expand=True,
        )

    # -------------------------------------------------------------- direita
    def _build_right(self) -> ft.Control:
        # Lista item a item do que entra no cobro — o cajero tem que poder ler
        # em voz alta pro cliente antes de apertar o botão.
        self.detail_list = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, height=0)
        self.brk_deuda = ft.Text("Gs. 0", size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"])
        self.brk_cargos = ft.Text("Gs. 0", size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"])
        self.brk_adv = ft.Text("Gs. 0", size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"])
        self.brk_adv_n = ft.Text("", size=12, color=COLORS["text_muted"])
        self.brk_adv_lbl = ft.Text("Adelanto", size=13, color=COLORS["text_secondary"])
        self.brk_cargos_row = ft.Row([
            ft.Text("Otros cargos", size=13, color=COLORS["text_secondary"]),
            ft.Container(expand=True), self.brk_cargos,
        ], visible=False)
        self.brk_adv_row = ft.Row([
            self.brk_adv_lbl, self.brk_adv_n, ft.Container(expand=True), self.brk_adv,
        ], visible=False)
        self.brk_box = ft.Column([
            ft.Row([ft.Text("Deuda", size=13, color=COLORS["text_secondary"]),
                    ft.Container(expand=True), self.brk_deuda]),
            self.brk_cargos_row,
            self.brk_adv_row,
        ], spacing=5, visible=False)
        self.total_text = ft.Text("Gs. 0", size=30, weight=ft.FontWeight.W_800, color=COLORS["text_primary"])

        # Fase 2.2: "valor a cobrar" ≠ "recibí". Um é o que se lança na conta do
        # cliente (pode ser menos que o total: pagamento parcial); o outro é o
        # papel-moeda que entrou na gaveta, que só serve para o troco.
        self.cobrar_field = ft.TextField(
            value="", hint_text="0", border=ft.InputBorder.NONE,
            text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_cobrar_change,
            on_submit=lambda e: self._focus_recibi(),
        )
        cobrar_box = ft.Container(
            content=ft.Row([
                ft.Text("Gs.", size=17, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                ft.Container(content=self.cobrar_field, expand=True),
            ], spacing=10),
            bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["accent_primary"]),
            border_radius=RADIUS["md"], padding=ft.Padding.symmetric(horizontal=15, vertical=0),
            height=52,
        )
        self.parcial_txt = ft.Text("", size=12, color=COLORS["accent_warning"], visible=False)
        self.cobrar_quick = ft.Row([
            self._chip_mini("Todo", lambda: self._set_cobrar(None)),
            self._chip_mini("Mitad", lambda: self._set_cobrar(-0.5)),
        ], spacing=7)

        self.recibi_field = ft.TextField(
            value="", hint_text="0", border=ft.InputBorder.NONE,
            text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_recibi_change,
            on_submit=lambda e: self._confirm(),
        )
        recibi_box = ft.Container(
            content=ft.Row([
                ft.Text("Gs.", size=17, weight=ft.FontWeight.W_600, color=COLORS["text_muted"]),
                ft.Container(content=self.recibi_field, expand=True),
            ], spacing=10),
            bgcolor=COLORS["bg_input"], border=ft.Border.all(1, COLORS["border"]),
            border_radius=RADIUS["md"], padding=ft.Padding.symmetric(horizontal=15, vertical=0), height=52,
        )

        quick = ft.Row(
            [self._quick_chip("Exacto", None)] +
            [self._quick_chip(_money(v).replace("Gs. ", ""), v) for v in (100000, 150000, 200000)],
            spacing=7,
        )

        self.vuelto_lbl = ft.Text("VUELTO", size=12, weight=ft.FontWeight.W_700, color="#5FD6AB")
        self.vuelto_val = ft.Text("Gs. 0", size=30, weight=ft.FontWeight.W_800, color=COLORS["accent_success"])
        self.vuelto_box = ft.Container(
            content=ft.Row([self.vuelto_lbl, ft.Container(expand=True), self.vuelto_val],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=17, vertical=13), border_radius=RADIUS["lg"],
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
        self.espera_btn = ft.TextButton(
            content=ft.Row([
                ft.Icon(ft.Icons.PAUSE_PRESENTATION, size=15, color=COLORS["text_muted"]),
                ft.Text("Dejar en espera (F7)", size=12, color=COLORS["text_muted"]),
            ], spacing=6, tight=True),
            tooltip="Guarda este atendimiento y libera el mostrador para el siguiente",
            on_click=lambda e: self._parkear(),
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("COBRANDO", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    self.detail_list,
                    self.brk_box,
                    ft.Container(
                        # CENTER, não END: 13 contra 30 alinhados pelo rodapé da
                        # caixa de texto sai escalonado (mesma causa do saldo).
                        content=ft.Row([ft.Text("SELECCIONADO", size=13, weight=ft.FontWeight.W_700, color=COLORS["text_secondary"]),
                                        ft.Container(expand=True), self.total_text],
                                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding.symmetric(horizontal=0, vertical=13),
                        border=ft.Border.only(top=ft.BorderSide(1, COLORS["border"]),
                                              bottom=ft.BorderSide(1, COLORS["border"])),
                    ),
                    ft.Text("VALOR A COBRAR", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    cobrar_box,
                    self.cobrar_quick,
                    self.parcial_txt,
                    ft.Text("RECIBÍ", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    recibi_box,
                    quick,
                    self.vuelto_box,
                    ft.Text("MÉTODO", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    self.metodo_row,
                    ft.Text("COMPROBANTE", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
                    self.comprobante_row,
                    self.comprobante_help,
                    ft.Container(height=6),
                    self.confirm_btn,
                    ft.Row([self.espera_btn], alignment=ft.MainAxisAlignment.CENTER),
                ],
                spacing=11, scroll=ft.ScrollMode.AUTO,
            ),
            width=384, bgcolor=COLORS["bg_secondary"],
            border=ft.Border.only(left=ft.BorderSide(1, COLORS["border"])),
            padding=ft.Padding.symmetric(horizontal=22, vertical=20),
        )

    def _chip_mini(self, label: str, on_click) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, size=12, weight=ft.FontWeight.W_600,
                            color=COLORS["text_secondary"]),
            padding=ft.Padding.symmetric(horizontal=0, vertical=7), expand=True,
            alignment=ft.Alignment.CENTER, bgcolor=COLORS["bg_input"],
            border=ft.Border.all(1, COLORS["border"]), border_radius=RADIUS["sm"], ink=True,
            on_click=lambda e: on_click(),
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
        # Transferencia/cheque não têm troco: o "recibí" acompanha o que se cobra.
        if value != "EFECTIVO":
            self.recibi_field.value = self.cobrar_field.value
            self._u(self.recibi_field)
        self._recompute()

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
            self._search_total = 0
            self._render_results()
            return
        self._search_timer = threading.Timer(0.35, lambda: self._bg(self._run_search))
        self._search_timer.daemon = True
        self._search_timer.start()

    def _on_search_submit(self):
        """
        Enter na busca: se já há resultado, entra no primeiro — o cajero digita o
        nome e aperta Enter, sem tocar no mouse.
        """
        if self._results:
            cid = self._results[0].get("id")
            self._bg(lambda: self._select_client(cid))
            return
        self._bg(self._run_search)

    def _run_search(self):
        q = (self.search_field.value or "").strip()
        if len(q) < 2:
            return
        self._search_seq += 1
        seq = self._search_seq
        try:
            rows, total = client_service.search_paged(query=q, limit=self.BUSCA_LIMIT)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
            return
        # Resposta atrasada de uma busca anterior não sobrescreve a atual.
        if seq != self._search_seq:
            return
        self._results = rows
        self._search_total = total or len(rows)
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

        q = (self.search_field.value or "").strip()
        pie = []
        if not self._results:
            if len(q) >= 2:
                rows = [ft.Text("Ningún cliente encontrado.", size=12, color=COLORS["text_muted"])]
                # O botão nasce do resultado vazio, já com o que foi digitado:
                # quem chega para se ligar à rede não está no cadastro ainda.
                pie.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PERSON_ADD_ALT, size=16, color="#FFFFFF"),
                        ft.Text(f"Registrar «{q}» (F1)", size=13,
                                weight=ft.FontWeight.W_700, color="#FFFFFF"),
                    ], spacing=8, tight=True),
                    padding=ft.Padding.symmetric(horizontal=14, vertical=9),
                    bgcolor=COLORS["accent_primary"], border_radius=RADIUS["sm"], ink=True,
                    on_click=lambda e: self._nuevo_cliente_desde_busqueda(),
                ))
            else:
                rows = []
        elif self._search_total > len(self._results):
            # Nunca esconder resultado sem dizer: o cajero precisa saber que há
            # mais gente com aquele nome antes de cobrar do homônimo errado.
            pie.append(ft.Text(
                f"Mostrando {len(self._results)} de {self._search_total} — afiná la "
                "búsqueda (CI o nº de medidor son únicos).",
                size=12, color=COLORS["accent_warning"]))

        self.search_results.controls = rows
        # Altura pela linha real (dois textos + padding) e não por um chute: era
        # o que cortava a última linha no meio.
        n = len(rows)
        alto = (n * self.BUSCA_ALTURA_FILA + max(0, n - 1) * self.BUSCA_ESPACIO) if n else 0
        self.search_results.height = min(self.BUSCA_ALTURA_MAX, alto)
        self.search_footer.controls = pie
        self.search_footer.visible = bool(pie)
        self._u(self.search_results)
        self._u(self.search_footer)

    def _nuevo_cliente_desde_busqueda(self):
        """
        Cadastro completo, igual ao administrativo — e volta ao atendimento com o
        cliente já selecionado, sem recomeçar a busca.
        """
        q = (self.search_field.value or "").strip()
        prefill = {}
        if q:
            # Só dígitos (e traço) parece documento; o resto é nome.
            solo_doc = q.replace("-", "").replace(".", "").isdigit()
            prefill = {"ci_ruc": q} if solo_doc else {"nombre_completo": q}

        def _after(saved: dict):
            self.search_field.value = ""
            self._results = []
            self._search_total = 0
            self._render_results()
            self._u(self.search_field)
            cid = (saved or {}).get("id")
            if cid:
                self._bg(lambda: self._select_client(cid))

        self._track(open_client_form(self.page, self.show_snackbar, prefill=prefill,
                                     on_saved=_after))

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
    def _select_client(self, client_id: str, meses_futuro: int | None = None,
                       preservar: dict | None = None):
        self._meses_futuro = meses_futuro or self.MESES_FUTURO_INICIAL
        try:
            ctx = client_service.get_payment_context(client_id, self._meses_futuro)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
            return
        self._apply_context(ctx, preservar)

    def _apply_context(self, ctx: dict, preservar: dict | None = None):
        self._ctx = ctx
        self._tarifa = float(ctx.get("tarifa_base", 0) or 0)
        client = ctx.get("client") or {}

        # índice de faturas por id: é o que permite simular o reparto de um
        # pagamento parcial e montar a factura legal com os valores reais.
        self._facturas = {f["id"]: f for f in (ctx.get("facturas") or []) if f.get("id")}

        self._build_cells(ctx, (preservar or {}).get("meses"))
        self._build_cargos(ctx, (preservar or {}).get("cargos"))

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
        n_pend = int(ctx.get("facturas_pendientes", 0) or 0)
        self.saldo_cnt.value = (
            "Sin deuda" if not n_pend
            else "1 factura pendiente" if n_pend == 1
            else f"{n_pend} facturas pendientes")
        self.saldo_cnt.color = (COLORS["accent_success"] if not n_pend
                                else COLORS["text_secondary"])

        self._render_acuerdo(ctx.get("acuerdo"))

        self._results = []
        self._search_total = 0
        self.search_results.controls = []
        self.search_results.height = 0
        self.search_footer.visible = False
        self.client_block.visible = True
        self._render_months()
        self._render_cargos()
        client_id = client.get("id")
        self._load_recent(client_id)
        self._load_consumo(client_id)
        # pré-preenche o valor a cobrar com o total selecionado
        self._recompute(prefill=True)
        self._u(self.search_results)
        self._u(self.search_footer)
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
                "cuota": float(m.get("cuota", 0) or 0),
                "invoice_ids": m.get("invoice_ids", []),
                "sel": sel and m["estado"] != "pagada",
            })

    def _build_cargos(self, ctx: dict, seleccionados: set | None = None):
        """
        Otros cargos: faturas AVULSA da tesouraria. Ficam fora da grade de meses
        (não são consumo de água) mas entram no mesmo total, no mesmo recibo e na
        mesma factura legal. Vêm marcados: é dívida como qualquer outra.
        """
        self._cargos = []
        for f in ctx.get("otros_cargos") or []:
            fid = f.get("id")
            sel = (fid in seleccionados) if seleccionados is not None else True
            self._cargos.append({"f": f, "sel": bool(sel)})

    def _cargo_label(self, f: dict) -> str:
        items = f.get("items") or []
        if items:
            desc = str(items[0].get("descripcion") or "Cargo")
            if len(items) > 1:
                desc += f" (+{len(items) - 1})"
            return desc
        nro = f.get("numero_factura")
        return f"Factura {nro}" if nro else "Cargo de tesorería"

    def _render_cargos(self):
        filas = []
        for i, c in enumerate(self._cargos):
            f = c["f"]
            per = f"{_MES[int(f.get('mes_referencia', 1)) - 1]}/{f.get('ano_referencia', '')}"
            parcial = str(f.get("status")) == "PARCIAL"
            filas.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK_BOX if c["sel"] else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                            size=18,
                            color=COLORS["accent_secondary"] if c["sel"] else COLORS["text_muted"]),
                    ft.Column([
                        ft.Text(self._cargo_label(f), size=13, weight=ft.FontWeight.W_600,
                                color=COLORS["text_primary"],
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(per + (" · pago parcial" if parcial else "")
                                + (f" · Fact. {f.get('numero_factura')}"
                                   if f.get("numero_factura") else ""),
                                size=11, color=COLORS["text_muted"]),
                    ], spacing=1, expand=True),
                    ft.Text(_money(f.get("saldo_devedor")), size=13,
                            weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                bgcolor=COLORS["bg_input"], border_radius=RADIUS["sm"],
                border=ft.Border.all(
                    1, COLORS["accent_secondary"] if c["sel"] else COLORS["accent_warning"]),
                ink=True, on_click=lambda e, idx=i: self._toggle_cargo(idx),
            ))
        if not filas:
            # O bloco não some mais quando não há cargo: é dele que sai o botão
            # de lançar um, e um bloco invisível é um botão que não existe.
            filas = [ft.Text("Sin cargos aparte del agua.", size=12,
                             color=COLORS["text_muted"])]
        self.cargos_list.controls = filas
        self.cargos_block.visible = bool(self._ctx)
        self._u(self.cargos_list)
        self._u(self.cargos_block)

    def _toggle_cargo(self, idx: int):
        self._cargos[idx]["sel"] = not self._cargos[idx]["sel"]
        self._render_cargos()
        self._recompute(prefill=True)

    def _render_acuerdo(self, acuerdo: dict | None):
        """Faixa do acordo ativo: quantas parcelas pagas e quanto falta."""
        if not acuerdo:
            self.acuerdo_box.visible = False
            self._u(self.acuerdo_box)
            return
        parcelas = acuerdo.get("parcelas") or []
        pagas = len([p for p in parcelas if p.get("status") == "PAGADA"])
        proxima = next((p for p in parcelas if p.get("status") != "PAGADA"), None)
        prox_txt = (f" · próxima {_MES[int(proxima['mes']) - 1]}/{proxima['ano']} "
                    f"({_money(proxima['valor'])})" if proxima else "")
        self.acuerdo_box.content = ft.Row([
            ft.Icon(ft.Icons.CALENDAR_MONTH, size=17, color=COLORS["accent_secondary"]),
            ft.Text(f"Acuerdo Nº {acuerdo.get('numero_fmt')} — {pagas}/{len(parcelas)} "
                    f"cuotas pagas{prox_txt}", size=12,
                    color=COLORS["text_secondary"], expand=True),
            ft.Text(f"falta {_money(acuerdo.get('saldo_pendiente'))}", size=12,
                    weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
        ], spacing=9)
        self.acuerdo_box.padding = ft.Padding.symmetric(horizontal=11, vertical=8)
        self.acuerdo_box.bgcolor = ft.Colors.with_opacity(0.10, COLORS["accent_secondary"])
        self.acuerdo_box.border = ft.Border.all(
            1, ft.Colors.with_opacity(0.3, COLORS["accent_secondary"]))
        self.acuerdo_box.border_radius = RADIUS["sm"]
        self.acuerdo_box.visible = True
        self._u(self.acuerdo_box)

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
        cargos = {c["f"]["id"] for c in self._cargos if c["sel"]}

        def work():
            try:
                ctx = client_service.get_payment_context(client_id, nuevo)
            except APIError as err:
                self.show_snackbar(friendly_error(err), error=True)
                return
            self._meses_futuro = nuevo
            self._ctx = ctx
            self._facturas = {f["id"]: f for f in (ctx.get("facturas") or []) if f.get("id")}
            self._build_cells(ctx, marcados)
            self._build_cargos(ctx, cargos)
            self._render_months()
            self._render_cargos()
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
            if c.get("cuota"):
                tooltip += f"  (incluye cuota del acuerdo: {_money(c['cuota'])})"
        if not pagada:
            tooltip += "  —  tocá para " + ("sacarlo del cobro" if c["sel"] else "agregarlo al cobro")

        etiqueta = ft.Row([
            ft.Text(_MES[c["mes"] - 1].upper(), size=13, weight=ft.FontWeight.W_800,
                    color=COLORS["text_muted"] if pagada else COLORS["text_primary"]),
            ft.Container(expand=True),
            ft.Icon(icon, size=15, color=icon_col),
        ], spacing=4)

        cuerpo = [
            etiqueta,
            ft.Text(valor, size=13, weight=ft.FontWeight.W_700,
                    # sem seleção, adelanto e mês pago ficam apagados: só o
                    # que entra no cobro (e o que ele deve) puxa o olho.
                    color=COLORS["text_primary"] if kind == "deuda" else COLORS["text_muted"]),
            ft.Text(estado_txt, size=10, weight=ft.FontWeight.W_600, color=estado_col),
        ]
        if c.get("cuota") and not pagada:
            cuerpo.append(ft.Text("incluye cuota", size=9,
                                  color=COLORS["accent_secondary"]))

        return ft.Container(
            data=idx,
            content=ft.Column(cuerpo, spacing=2),
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
                # `wrap`: seis células de 112 + o rótulo do ano dão ~760 px. Numa
                # janela estreita (a caja aberta pelo menu não é tela cheia) a
                # linha estourava o painel e o Flet pintava a faixa de overflow
                # em cima da grade. Com wrap ela dobra em vez de estourar.
                rows.append(ft.Row(
                    [etiqueta] + [self._month_cell(i, c) for i, c in bloque],
                    spacing=8, run_spacing=8, wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
            self.months_sub.value = f"Sin deuda de agua · {n_sel} en este cobro"
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
        for c in self._cargos:
            c["sel"] = True
        self._render_months()
        self._render_cargos()
        self._recompute(prefill=True)

    def _clear_selection(self):
        for c in self._cells:
            c["sel"] = False
        for c in self._cargos:
            c["sel"] = False
        self._render_months()
        self._render_cargos()
        self._recompute(prefill=True)

    def _load_recent(self, client_id: str):
        """
        Últimos pagos — e cada linha reimprime o recibo dela.

        Era texto morto: o cajero via a data e o valor e não podia fazer nada com
        aquilo. O caso mais comum do balcão é "perdí el recibo".
        """
        fallo = False
        try:
            pays = payment_service.list_by_client(client_id, limit=3)
        except Exception as exc:  # noqa: BLE001
            # "Sin pagos registrados" quando a chamada falhou é mentira no
            # balcão — quem perdeu o recibo ouviria que nunca pagou.
            print(f"[Caja] recent_payments_failed err={exc}")
            pays, fallo = [], True
        rows = []
        for p in pays:
            nro = p.get("numero_recibo")
            rec = f"Rec. {int(nro):05d}" if nro not in (None, "") else "Rec. —"
            fecha = format_local(p.get("fecha_pago"), "%d/%m/%Y")
            grupo = p.get("grupo_pagamento")
            rows.append(ft.Container(
                content=ft.Row([
                    ft.Text(fecha, size=13, color=COLORS["text_secondary"], width=90),
                    ft.Text(rec, size=11, color=COLORS["text_muted"]),
                    ft.Container(expand=True),
                    ft.Text(_money(p.get("valor_total", 0)), size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
                    ft.Icon(ft.Icons.PRINT_OUTLINED, size=14, color=COLORS["text_muted"]),
                ], spacing=10),
                padding=ft.Padding.symmetric(horizontal=0, vertical=7),
                border=ft.Border.only(top=ft.BorderSide(1, COLORS["border_subtle"])) if rows else None,
                tooltip="Reimprimir este recibo" if grupo else None,
                ink=bool(grupo),
                on_click=(lambda e, g=grupo, r=rec: self._bg(lambda: self._reimprimir_recibo(g, r)))
                if grupo else None,
            ))
        if not rows:
            rows = [ft.Text(
                "No se pudieron cargar los últimos pagos." if fallo
                else "Sin pagos registrados.",
                size=12,
                color=COLORS["accent_warning"] if fallo else COLORS["text_muted"])]
        self.recent_pays.controls = rows
        self._u(self.recent_pays)

    def _reimprimir_recibo(self, grupo: str, etiqueta: str = ""):
        try:
            result = payment_service.get_by_group(grupo)
            payload = dict(result)
            payload["company"] = self._get_company()
            printer_manager.print_pdf(self._g_receipt.generate(payload),
                                      printer_type="thermal",
                                      job_name=f"receipt_{str(grupo)[:20]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] reprint_receipt_failed err={exc}")
            self.show_snackbar("No se pudo reimprimir el recibo.", error=True)
            return
        self.show_snackbar(f"{etiqueta or 'Recibo'} reimpreso.")

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
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] readings_failed err={exc}")
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
        """(deuda de agua, otros cargos, adelanto, nº de meses adelantados)."""
        deuda = sum(c["saldo"] for c in self._cells if c["estado"] == "pendente" and c["sel"])
        cargos = sum(float(c["f"].get("saldo_devedor") or 0)
                     for c in self._cargos if c["sel"])
        adv_cells = [c for c in self._cells if c["estado"] == "sem_factura" and c["sel"]]
        adv = self._tarifa * len(adv_cells)
        return deuda, cargos, adv, len(adv_cells)

    def _total_seleccionado(self) -> float:
        deuda, cargos, adv, _ = self._selected_total()
        return deuda + cargos + adv

    def _targets(self) -> list:
        """
        O que vai ser pago, na MESMA ordem que o backend usa (ano, mês, emissão).

        Serve para duas coisas que precisam bater com a realidade: mostrar o que
        sobra na fatura mais antiga num pagamento parcial, e montar a factura
        legal com os valores realmente aplicados.
        """
        alvos = []
        for c in self._cells:
            if not c["sel"] or c["estado"] == "pagada":
                continue
            if c["estado"] == "pendente":
                for iid in c["invoice_ids"]:
                    f = self._facturas.get(iid)
                    if not f:
                        continue
                    alvos.append({
                        "kind": "deuda", "id": iid, "ano": c["ano"], "mes": c["mes"],
                        "emision": str(f.get("fecha_emision") or ""),
                        "saldo": float(f.get("saldo_devedor") or 0),
                        "cuota": float(f.get("cuota_valor") or 0), "factura": f,
                    })
            elif c["estado"] == "sem_factura":
                # Fatura que ainda não existe: o backend cria agora, então ela
                # entra depois das reais do mesmo período.
                alvos.append({
                    "kind": self._kind(c), "id": None, "ano": c["ano"], "mes": c["mes"],
                    "emision": _FUTURO, "saldo": float(self._tarifa), "cuota": 0.0,
                    "factura": None,
                })
        for c in self._cargos:
            if not c["sel"]:
                continue
            f = c["f"]
            alvos.append({
                "kind": "cargo", "id": f.get("id"),
                "ano": int(f.get("ano_referencia") or 0),
                "mes": int(f.get("mes_referencia") or 1),
                "emision": str(f.get("fecha_emision") or ""),
                "saldo": float(f.get("saldo_devedor") or 0), "cuota": 0.0, "factura": f,
            })
        alvos.sort(key=lambda a: (a["ano"], a["mes"], a["emision"]))
        return alvos

    def _reparto(self, monto: float) -> list:
        """Distribui `monto` nos alvos, da mais antiga para a mais nova."""
        restante = float(monto or 0)
        salida = []
        for a in self._targets():
            if restante <= 0:
                aplicado = 0.0
            else:
                aplicado = min(restante, a["saldo"])
                restante -= aplicado
            item = dict(a)
            item["aplicado"] = aplicado
            item["resto"] = a["saldo"] - aplicado
            salida.append(item)
        return salida

    def _render_detail(self):
        """Uma linha por item cobrado, na ordem em que o dinheiro vai cair."""
        cobrar = self._cobro_amount()
        rows = []
        for a in self._reparto(cobrar):
            if a["aplicado"] <= 0 and a["resto"] > 0 and cobrar > 0:
                tag, tag_col = "queda pendiente", COLORS["text_muted"]
            elif a["kind"] == "cargo":
                tag, tag_col = "otros cargos", COLORS["accent_secondary"]
            elif a["kind"] == "adelanto":
                tag, tag_col = "adelanto", COLORS["accent_secondary"]
            elif a["kind"] == "sin_factura":
                tag, tag_col = "sin factura", COLORS["accent_secondary"]
            elif a["cuota"]:
                tag, tag_col = "incluye cuota", COLORS["accent_secondary"]
            else:
                tag, tag_col = "deuda", COLORS["accent_warning"]

            # Sem corte na mão: o `width` + ELLIPSIS do Text já resolve, e cortar
            # antes deixava o texto truncado sem as reticências.
            etiqueta = (self._cargo_label(a["factura"]) if a["kind"] == "cargo"
                        else f"{_MES[a['mes'] - 1]} {a['ano']}")
            valor = a["aplicado"] if cobrar > 0 else a["saldo"]
            rows.append(ft.Row([
                ft.Text(etiqueta, size=13, weight=ft.FontWeight.W_600,
                        color=COLORS["text_primary"], width=96,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(tag, size=11, color=tag_col),
                ft.Container(expand=True),
                ft.Text(_money(valor), size=13, weight=ft.FontWeight.W_600,
                        color=COLORS["text_primary"] if valor > 0 else COLORS["text_muted"]),
            ], spacing=7, height=26))
        if not rows:
            rows = [ft.Container(
                content=ft.Text("Nada seleccionado.", size=12, color=COLORS["text_muted"]),
                height=26,
            )]
        self.detail_list.controls = rows
        self.detail_list.height = min(182, 26 * len(rows))
        self._u(self.detail_list)

    def _cobro_amount(self) -> float:
        """O que vai ser lançado na conta do cliente (default: tudo o selecionado)."""
        v = self._parse_amount(self.cobrar_field.value)
        if v is None:
            return self._total_seleccionado()
        return max(0.0, v)

    def _recompute(self, prefill: bool = False):
        deuda, cargos, adv, adv_n = self._selected_total()
        total = deuda + cargos + adv
        self.brk_deuda.value = _money(deuda)
        self.brk_cargos.value = _money(cargos)
        self.brk_adv.value = _money(adv)
        self.brk_adv_n.value = f"({adv_n} {'mes' if adv_n == 1 else 'meses'})" if adv_n else ""
        # O rótulo segue o que de fato está na conta: adelanto, mês não faturado ou os dois.
        kinds = {self._kind(c) for c in self._cells if c["sel"] and c["estado"] == "sem_factura"}
        self.brk_adv_lbl.value = {
            frozenset({"adelanto"}): "Adelanto",
            frozenset({"sin_factura"}): "Meses no facturados",
        }.get(frozenset(kinds), "Adelanto y no facturados")
        self.brk_adv_row.visible = adv_n > 0
        self.brk_cargos_row.visible = cargos > 0
        # Só vale a pena abrir a conta quando há mais de uma natureza nela.
        self.brk_box.visible = adv_n > 0 or cargos > 0
        self._u(self.brk_adv_lbl)
        self.total_text.value = _money(total)

        if prefill:
            self.cobrar_field.value = f"{int(round(total))}" if total else ""
            self._u(self.cobrar_field)
            self.recibi_field.value = self.cobrar_field.value
            self._u(self.recibi_field)

        self._render_detail()
        self._render_months_header()
        self._render_parcial(total)
        self._u(self.brk_box)
        self._u(self.brk_adv_row)
        self._u(self.brk_cargos_row)
        self._update_vuelto()
        for c in (self.brk_deuda, self.brk_cargos, self.brk_adv, self.brk_adv_n,
                  self.total_text):
            self._u(c)

    def _render_parcial(self, total: float):
        """
        Diz em voz alta o que um pagamento parcial deixa em aberto.

        O backend sempre soube receber menos que o total (aplica na mais antiga e
        deixa a fatura PARCIAL); o que faltava era a tela contar isso ao cajero,
        que precisa avisar o cliente antes, não depois.
        """
        cobrar = self._cobro_amount()
        if total <= 0:
            self.parcial_txt.visible = False
            self._u(self.parcial_txt)
            return
        if cobrar > total:
            self.parcial_txt.value = (
                f"Estás cobrando {_money(cobrar - total)} más de lo seleccionado. "
                "Agregá otro mes o bajá el valor.")
            self.parcial_txt.color = COLORS["accent_error"]
            self.parcial_txt.visible = True
            self._u(self.parcial_txt)
            return
        if abs(cobrar - total) < 1:
            self.parcial_txt.visible = False
            self._u(self.parcial_txt)
            return

        pendientes = [a for a in self._reparto(cobrar) if a["resto"] > 0]
        if not pendientes:
            self.parcial_txt.visible = False
            self._u(self.parcial_txt)
            return
        primera = pendientes[0]
        etiqueta = (self._cargo_label(primera["factura"]) if primera["kind"] == "cargo"
                    else f"{_MES[primera['mes'] - 1]}/{primera['ano']}")
        resto_total = sum(a["resto"] for a in pendientes)
        extra = (f" (y {len(pendientes) - 1} más, {_money(resto_total - primera['resto'])})"
                 if len(pendientes) > 1 else "")
        self.parcial_txt.value = (
            f"Pago parcial: quedan {_money(primera['resto'])} en {etiqueta}{extra}. "
            "La factura queda como pago parcial y sigue en deuda.")
        self.parcial_txt.color = COLORS["accent_warning"]
        self.parcial_txt.visible = True
        self._u(self.parcial_txt)

    def _update_vuelto(self):
        cobrar = self._cobro_amount()
        recibi = self._parse_amount(self.recibi_field.value)
        if self.metodo != "EFECTIVO":
            # Transferencia/cheque não têm gaveta: não existe vuelto.
            self.vuelto_lbl.value = "SIN VUELTO"
            self.vuelto_val.value = _money(0)
            self.vuelto_val.color = COLORS["text_muted"]
            self.vuelto_lbl.color = COLORS["text_muted"]
            self.vuelto_box.bgcolor = COLORS["bg_input"]
            self.vuelto_box.border = ft.Border.all(1, COLORS["border"])
        else:
            diff = (recibi or 0) - cobrar
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

    def _on_cobrar_change(self, e):
        self._render_detail()
        self._render_parcial(self._total_seleccionado())
        if self.metodo != "EFECTIVO":
            self.recibi_field.value = self.cobrar_field.value
            self._u(self.recibi_field)
        self._update_vuelto()

    def _on_recibi_change(self, e):
        self._update_vuelto()

    def _focus_recibi(self):
        self._focus(self.recibi_field)

    def _set_cobrar(self, factor):
        """`None` = tudo o selecionado; negativo = fração (−0.5 = metade)."""
        total = self._total_seleccionado()
        valor = total if factor is None else total * abs(factor)
        self.cobrar_field.value = f"{int(round(valor))}" if valor else ""
        self._u(self.cobrar_field)
        self.recibi_field.value = self.cobrar_field.value
        self._u(self.recibi_field)
        self._render_detail()
        self._render_parcial(total)
        self._update_vuelto()

    def _set_recibi(self, value):
        if value is None:  # "Exacto"
            value = self._cobro_amount()
        self.recibi_field.value = f"{int(round(value))}"
        self._u(self.recibi_field)
        self._update_vuelto()

    # ------------------------------------------------------------- em espera
    def _parkear(self):
        """
        Guarda o atendimento atual e libera o balcão.

        Só na memória do app: nada foi cobrado ainda, então não há dinheiro nem
        documento para perder se o app fechar.
        """
        if not self._ctx:
            return
        client = self._ctx.get("client") or {}
        self._espera.append({
            "ctx": self._ctx,
            "meses": {(c["ano"], c["mes"]) for c in self._cells if c["sel"]},
            "cargos": {c["f"]["id"] for c in self._cargos if c["sel"]},
            "cobrar": self.cobrar_field.value,
            "meses_futuro": self._meses_futuro,
            "nombre": client.get("nombre_completo", "-"),
        })
        self._render_espera()
        self._reset()
        self.show_snackbar(f"{client.get('nombre_completo', 'Atención')} quedó en espera.")
        self._focus(self.search_field)

    def _render_espera(self):
        chips = []
        for i, item in enumerate(self._espera):
            chips.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.PAUSE_CIRCLE_OUTLINE, size=14,
                            color=COLORS["accent_warning"]),
                    ft.Text(item["nombre"][:22], size=12, weight=ft.FontWeight.W_600,
                            color=COLORS["text_primary"]),
                    # Era um X, e um X promete descartar — o chip retoma.
                    ft.Icon(ft.Icons.PLAY_ARROW, size=13,
                            color=COLORS["accent_secondary"]),
                ], spacing=6, tight=True),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                bgcolor=COLORS["bg_input"], border_radius=RADIUS["pill"],
                border=ft.Border.all(1, ft.Colors.with_opacity(0.4, COLORS["accent_warning"])),
                tooltip="Retomar este atendimiento (F8 retoma el primero)",
                ink=True, on_click=lambda e, idx=i: self._retomar(idx),
            ))
        self.espera_row.controls = chips
        self.espera_row.visible = bool(chips)
        self._u(self.espera_row)

    def _retomar(self, idx: int = 0):
        if not self._espera or idx >= len(self._espera):
            return
        item = self._espera.pop(idx)
        self._render_espera()
        self._meses_futuro = item.get("meses_futuro", self.MESES_FUTURO_INICIAL)
        cid = (item["ctx"].get("client") or {}).get("id")

        def work():
            # Recarrega o contexto: entre o parkeo e a volta pode ter entrado
            # pagamento, leitura ou cargo novo — a tela não pode cobrar por um
            # retrato velho.
            self._select_client(cid, self._meses_futuro,
                                preservar={"meses": item["meses"], "cargos": item["cargos"]})
            if item.get("cobrar"):
                self.cobrar_field.value = item["cobrar"]
                self._u(self.cobrar_field)
                self._on_cobrar_change(None)

        self._bg(work)

    # ---------------------------------------------------------------- acordo
    def _open_acuerdo(self):
        if not self._ctx:
            self.show_snackbar("Elegí un cliente para armar el plan de pagos.", error=True)
            return
        if not self._sesion:
            self.show_snackbar("Abrí la caja antes de cerrar un acuerdo.", error=True)
            return
        facturas = [f for f in (self._ctx.get("facturas") or [])
                    if float(f.get("saldo_devedor") or 0) > 0]
        if not facturas and not self._ctx.get("acuerdo"):
            self.show_snackbar("Este cliente no tiene deuda para parcelar.")
            return

        def _after(_r):
            cid = (self._ctx.get("client") or {}).get("id")
            if cid:
                self._bg(lambda: self._select_client(cid))

        self._track(open_acuerdo_dialog(
            self.page, self.show_snackbar, self._ctx, self._get_company,
            metodo=self.metodo, on_done=_after))

    # ------------------------------------------------- cargo de valor livre
    def _open_cargo(self):
        """
        Fatura um cargo na hora, com valor livre, e cobra no mesmo atendimento.

        Vira uma fatura `AVULSA` de verdade — numerada, auditável, e cobrada
        pelo mesmo caminho dos cargos da tesouraria. Não existe cobro fora de
        fatura no balcão: o dinheiro sempre cai em cima de um documento.
        """
        if not self._ctx:
            self.show_snackbar("Elegí un cliente para lanzar el cargo.", error=True)
            return
        if not self._sesion:
            self.show_snackbar("Abrí la caja antes de lanzar un cargo.", error=True)
            return
        client = self._ctx.get("client") or {}

        def _after(invoice_id: str | None):
            # Recarrega o contexto preservando o que já estava marcado e deixa o
            # cargo novo marcado também — foi lançado para ser cobrado agora.
            meses = {(c["ano"], c["mes"]) for c in self._cells if c["sel"]}
            cargos = {c["f"]["id"] for c in self._cargos if c["sel"]}
            if invoice_id:
                cargos.add(invoice_id)
            self._bg(lambda: self._select_client(
                client.get("id"), self._meses_futuro,
                preservar={"meses": meses, "cargos": cargos}))

        self._track(open_cargo_dialog(self.page, self.show_snackbar, client,
                                      on_done=_after))

    # ------------------------------------------------------- turno / gaveta
    def _open_atenciones(self):
        page = self._pagina()
        if page is None:
            return
        self._track(open_atenciones_dialog(
            page, self.show_snackbar, self._get_company,
            on_changed=self._refrescar_cliente))

    def _refrescar_cliente(self):
        """Depois de anular algo, o cliente na tela pode ter voltado a dever."""
        if not self._ctx:
            return
        cid = (self._ctx.get("client") or {}).get("id")
        if cid:
            self._bg(lambda: self._select_client(cid, self._meses_futuro))

    def _open_resumen(self):
        if not self._sesion:
            self.show_snackbar("No hay turno abierto.", error=True)
            return
        self._track(open_resumen_dialog(self.page, self.show_snackbar, self._sesion))

    def _open_movimiento(self, categoria: str):
        if not self._sesion:
            self.show_snackbar("Abrí la caja antes de mover plata de la gaveta.", error=True)
            return
        self._track(open_movimiento_dialog(self.page, self.show_snackbar, categoria))

    # ---------------------------------------------------------------- cobrar
    def _confirm(self):
        if not self._ctx:
            self.show_snackbar("Elegí un cliente para cobrar.", error=True)
            return
        if not self._sesion:
            self.show_snackbar("Abrí la caja antes de cobrar.", error=True)
            return
        total = self._total_seleccionado()
        if total <= 0:
            self.show_snackbar(
                "Seleccioná al menos un mes o un cargo para cobrar.", error=True)
            return

        cobrar = self._parse_amount(self.cobrar_field.value)
        if cobrar is None:
            cobrar = total
        if cobrar <= 0:
            self.show_snackbar("El valor a cobrar tiene que ser mayor a cero.", error=True)
            return
        if cobrar - total > 0.5:
            self.show_snackbar(
                f"Estás cobrando más de lo seleccionado ({_money(cobrar)} sobre "
                f"{_money(total)}). Agregá otro mes o bajá el valor.", error=True)
            return

        if self.metodo == "EFECTIVO":
            recibi = self._parse_amount(self.recibi_field.value)
            if recibi is None or recibi < cobrar - 0.5:
                self.show_snackbar(
                    "El efectivo recibido no cubre el valor a cobrar. "
                    "Corregí «Recibí» o bajá el valor a cobrar.", error=True)
                return

        # Alvos que de fato recebem dinheiro: num pagamento parcial não se manda
        # ao backend a fatura que não vai receber nada.
        reparto = [a for a in self._reparto(cobrar) if a["aplicado"] > 0]
        invoice_ids = [a["id"] for a in reparto if a["id"]]
        prepay = [{"mes": a["mes"], "ano": a["ano"]} for a in reparto if not a["id"]]

        client = self._ctx.get("client") or {}
        payload = {
            "client_id": client.get("id"),
            "valor_total": cobrar,
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
        self._open_conferencia(client, payload, self._build_factura_items(reparto))

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
    def _build_factura_items(self, reparto: list) -> list:
        """
        Linhas da factura legal a partir do que REALMENTE vai ser aplicado.

        O total do DTE tem de casar com o cobro — se o cliente paga parcial, a
        linha sai com o valor aplicado, não com o saldo cheio.

        IVA por natureza: água usa o das configurações; a cuota do acordo usa o
        que foi escolhido no acordo; otros cargos usam o IVA dos próprios itens da
        fatura AVULSA. Quando um cargo recebe pagamento parcial não há como
        ratear itens de IVA diferente com honestidade, então sai uma linha só, com
        o IVA do primeiro item.
        """
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
        for a in reparto:
            aplicado = int(round(a["aplicado"]))
            if aplicado <= 0:
                continue
            per = f"{_MES[a['mes'] - 1]}/{a['ano']}"
            f = a["factura"] or {}

            if a["kind"] == "cargo":
                sub_items = f.get("items") or []
                completo = a["resto"] <= 0.5
                if sub_items and completo:
                    for it in sub_items:
                        precio = int(round(float(it.get("precio_unitario") or 0)))
                        cant = int(it.get("cantidad") or 1)
                        if precio * cant <= 0:
                            continue
                        items.append({
                            "descripcion": str(it.get("descripcion") or "Cargo")[:120],
                            "cantidad": cant, "precio_unit": precio,
                            "tasa_iva": int(it.get("iva_tasa") or tasa),
                            "afectacion": int(it.get("iva_afectacion") or afect),
                            "codigo": "2",
                        })
                    continue
                primero = sub_items[0] if sub_items else {}
                items.append({
                    "descripcion": f"{self._cargo_label(f)} {per}"[:120],
                    "cantidad": 1, "precio_unit": aplicado,
                    "tasa_iva": int(primero.get("iva_tasa") or tasa),
                    "afectacion": int(primero.get("iva_afectacion") or afect),
                    "codigo": "2",
                })
                continue

            # Água: separa a parte que é cuota de acordo, com o IVA do acordo.
            cuota = float(a.get("cuota") or 0)
            agua = aplicado
            cuota_aplicada = 0
            if cuota > 0:
                # A cuota é a última parte a ser coberta dentro da fatura do mês:
                # o que o cliente paga vai primeiro no consumo.
                parte_agua = max(0.0, a["saldo"] - cuota)
                agua = int(round(min(aplicado, parte_agua)))
                cuota_aplicada = aplicado - agua
            if agua > 0:
                desc = (f"Servicio de agua (adelanto) {per}" if a["kind"] == "adelanto"
                        else f"Servicio de agua {per}")
                items.append({"descripcion": desc, "cantidad": 1, "precio_unit": int(agua),
                              "tasa_iva": tasa, "afectacion": afect, "codigo": "1"})
            if cuota_aplicada > 0:
                numero = f.get("cuota_numero")
                items.append({
                    "descripcion": (f"Cuota {numero} de acuerdo de pago {per}"
                                    if numero else f"Cuota de acuerdo de pago {per}"),
                    "cantidad": 1, "precio_unit": int(cuota_aplicada),
                    "tasa_iva": int(f.get("cuota_iva_tasa") or tasa),
                    "afectacion": int(f.get("cuota_iva_afectacion") or afect),
                    "codigo": "3",
                })
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

        Editável é só o receptor. Os itens saem do que vai ser cobrado e o total
        tem de casar com o cobro que vai ser registrado — mexer no preço aqui faria
        a factura divergir do recibo. Para mudar valores, fecha e muda a seleção.
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
                ft.Text("Para cambiar montos, cerrá y ajustá lo seleccionado.",
                        size=11, color=COLORS["text_muted"]),
            ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
                ModalAction("Emitir factura", primary=True, on_click=lambda e: _save_and_emit()),
            ],
            width_pct=0.45,
        )
        self._track(modal)

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
            # Sem Esc: a emissão tem os próprios botões («Cancelar emisión» antes
            # da firma, «Cerrar» no fim). Fechar às cegas deixaria o cajero sem
            # saber se o KuDE saiu.
            self._track(open_sifen_progress(
                self.page, self.show_snackbar, emission_id=emission_id,
                receptor=f"{nombre or '-'} · {doc}"), esc_cierra=False)
        else:
            self.show_snackbar("✓ Cobro registrado · factura en cola")

    def _reset(self):
        self._ctx = None
        self._cells = []
        self._cargos = []
        self._facturas = {}
        self.client_block.visible = False
        self.cargos_block.visible = False
        self.acuerdo_box.visible = False
        self.search_field.value = ""
        self.cobrar_field.value = ""
        self.recibi_field.value = ""
        self.parcial_txt.visible = False
        self.confirm_btn.disabled = False
        self._recompute()
        self._u(self.client_block)
        self._u(self.cargos_block)
        self._u(self.acuerdo_box)
        self._u(self.search_field)
        self._u(self.parcial_txt)
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

        # Acordo quitado por este pagamento: as faturas antigas saem junto do
        # recibo da última parcela, como prova de que aquela dívida acabou.
        if result.get("acuerdo_quitado"):
            try:
                self._print_acuerdo_quitado(result["acuerdo_quitado"], company)
            except Exception as exc:  # noqa: BLE001
                print(f"[Caja] print_acuerdo_quitado_failed err={exc}")
                self.show_snackbar(
                    "El acuerdo quedó saldado, pero no se pudieron imprimir las "
                    "facturas viejas.", error=True)

    def _print_acuerdo_quitado(self, acuerdo: dict, company: dict):
        facturas = acuerdo.get("facturas_anuladas") or []
        impresas = 0
        for f in facturas:
            try:
                detalle = invoice_service.get_with_balance(f.get("invoice_id"))
            except Exception as exc:  # noqa: BLE001
                print(f"[Caja] acuerdo_invoice_fetch_failed err={exc}")
                continue
            client = self._ctx.get("client") if self._ctx else {}
            payload = {
                "invoice": detalle,
                "client": {
                    "name": (client or {}).get("nombre_completo", "-"),
                    "ci_ruc": (client or {}).get("ci_ruc", "-"),
                    "address": (client or {}).get("direccion", "-"),
                    "meter": (client or {}).get("numero_medidor", "-"),
                    "manzana": (client or {}).get("manzana", "-"),
                    "lote": (client or {}).get("lote", "-"),
                },
                "company": company,
            }
            printer_manager.print_pdf(
                self._g_invoice.generate(payload), printer_type="thermal",
                job_name=f"acuerdo_{acuerdo.get('numero', '')}_inv_{impresas}")
            impresas += 1
        self.show_snackbar(
            f"✓ Acuerdo Nº {acuerdo.get('numero_fmt', '')} saldado — "
            f"{impresas} factura(s) vieja(s) impresa(s) como comprobante.")

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
