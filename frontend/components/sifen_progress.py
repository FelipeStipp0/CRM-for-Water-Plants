from __future__ import annotations

"""
WMApp Frontend - Tela de progresso da emissão de factura electrónica (SIFEN).

Uma emissão leva alguns segundos e passa por etapas que o operador precisa ver:
o cliente está no balcão esperando o papel. Esta tela acompanha o job do começo
ao fim e é o **único** lugar que sabe traduzir fase → texto.

De onde vem cada etapa:
- `Generando/Firmando/Recuperando` são reportadas pelo **coordenador** (que pode
  ser outro PC) e chegam aqui pelo backend, no polling da emissão.
- `Generando/Imprimiendo KuDE` acontecem **neste** PC, depois da emissão fechar —
  o KuDE é a representação impressa e sai na impressora de quem cobrou.

Desistir: enquanto o documento não foi assinado ele não existe para o SET, então
dá para largar o job. Depois da firma o botão some — a partir daí a única saída é
a cancelación fiscal (estorno do pagamento / «Cancelar» na lista de facturas).
"""

import threading
import time

import flet as ft

from components.app_modal import AppModal
from components.theme import COLORS, FONTS, RADIUS, create_button
from services.api_client import APIError
from services.sifen_service import sifen_service
from utils.errors import friendly_error

# Etapas na ordem em que o operador as vê. As três primeiras vêm do coordenador
# (chave = EmissionFase no backend); as duas últimas são locais.
FASES_REMOTAS = ("GENERAR", "FIRMAR", "RECUPERAR")
PASOS = [
    ("GENERAR",   "Generando documento"),
    ("FIRMAR",    "Firmando documento"),
    ("RECUPERAR", "Recuperando documento firmado"),
    ("KUDE",      "Generando KuDE"),
    ("IMPRIMIR",  "Imprimiendo KuDE"),
]

# Estados terminais do job no backend.
TERMINALES = ("EMITIDA", "FALHOU", "ABORTADA", "CANCELADA")

POLL_S = 1.0            # ritmo do polling (a emissão inteira leva ~7s)
POLL_MAX_S = 180        # teto: acima disso a tela para de esperar (o job segue)
AUTOCLOSE_S = 10        # contagem para fechar sozinho depois do sucesso


class _Paso(ft.Row):
    """Uma linha da lista: ícone de estado + rótulo (+ detalhe opcional)."""

    def __init__(self, label: str):
        self.icon_slot = ft.Container(width=22, height=22, alignment=ft.Alignment.CENTER)
        self.label = ft.Text(label, size=FONTS["size_base"], color=COLORS["text_muted"])
        self.detail = ft.Text("", size=FONTS["size_xs"], color=COLORS["text_muted"])
        super().__init__(
            [self.icon_slot, ft.Column([self.label, self.detail], spacing=1, tight=True)],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.pendiente()

    # -- estados visuais --
    def pendiente(self):
        self.icon_slot.content = ft.Icon(ft.Icons.CIRCLE_OUTLINED, size=15,
                                         color=COLORS["border"])
        self.label.color = COLORS["text_muted"]

    def activo(self):
        self.icon_slot.content = ft.ProgressRing(width=16, height=16, stroke_width=2,
                                                 color=COLORS["accent_primary"])
        self.label.color = COLORS["text_primary"]

    def hecho(self):
        self.icon_slot.content = ft.Icon(ft.Icons.CHECK_CIRCLE, size=18,
                                         color=COLORS["accent_success"])
        self.label.color = COLORS["text_secondary"]

    def fallido(self):
        self.icon_slot.content = ft.Icon(ft.Icons.ERROR, size=18,
                                         color=COLORS["accent_error"])
        self.label.color = COLORS["accent_error"]

    def cancelado(self):
        self.icon_slot.content = ft.Icon(ft.Icons.REMOVE_CIRCLE_OUTLINE, size=17,
                                         color=COLORS["text_muted"])
        self.label.color = COLORS["text_muted"]


def _formato_kude() -> str:
    """'a4' ou 'p80' — o mesmo ajuste de «Configuración» que vale para faturas."""
    from config.local_settings import get_invoice_print_format

    return "a4" if get_invoice_print_format() == "a4" else "p80"


def _logo_cuadrada() -> bytes | None:
    """Logo 1×1 da junta para o cabeçalho do KuDE A4 (o P80 não usa)."""
    import base64

    from services.settings_service import settings_service

    try:
        b64 = (settings_service.get() or {}).get("logo_cuadrado_base64")
        return base64.b64decode(b64) if b64 else None
    except Exception:  # noqa: BLE001 — sem logo o A4 sai igual, só sem a marca
        return None


def generar_kude(emission_id: str) -> bytes:
    """
    Baixa o XML assinado e monta o KuDE no formato configurado. Levanta em falha.

    A4 e P80 são o MESMO documento fiscal — muda só a representação impressa.
    Segue o ajuste de formato de impressão das faturas, para o operador não ter
    dois lugares diferentes para dizer que tipo de papel a impressora tem.
    """
    from services.pdf_generation.kude import KudeA4Generator, KudeP80Generator

    xml = sifen_service.get_emision_xml(emission_id)
    if _formato_kude() == "a4":
        pdf = KudeA4Generator().generate(xml, _logo_cuadrada())
    else:
        pdf = KudeP80Generator().generate(xml)
    if not pdf:
        raise RuntimeError("KuDE vacío (XML sin datos para imprimir)")
    return pdf


def imprimir_kude(emission_id: str, pdf: bytes | None = None) -> None:
    """
    Imprime o KuDE de uma emissão. Levanta em falha.

    Único ponto de impressão do KuDE no app — a factura legal sai igual venha de
    onde vier (caja, facturación, finanzas).
    """
    from services.pdf_generation.printer_manager import printer_manager

    impressora = "a4" if _formato_kude() == "a4" else "thermal"
    printer_manager.print_pdf(pdf if pdf is not None else generar_kude(emission_id),
                              printer_type=impressora, job_name=f"kude_{emission_id[:8]}")


def open_sifen_progress(page: ft.Page, show_snackbar, *, emission_id: str,
                        receptor: str | None = None, on_done=None,
                        con_kude: bool = True) -> AppModal:
    """
    Abre a tela de progresso de uma emissão já enfileirada.

    `emission_id` — job devolvido por `sifen_service.emitir`.
    `receptor`    — nome/documento de quem recebe (subtítulo).
    `on_done`     — chamado com a emissão final quando ela fecha (qualquer status).
    `con_kude`    — inclui gerar+imprimir o KuDE nesta máquina.
    """
    pasos_def = PASOS if con_kude else PASOS[:3]
    pasos = {key: _Paso(label) for key, label in pasos_def}

    titulo = ft.Text("Generando factura electrónica", size=FONTS["size_lg"],
                     weight=ft.FontWeight.W_700, color=COLORS["text_primary"])
    subtitulo = ft.Text(receptor or "", size=FONTS["size_sm"], color=COLORS["text_secondary"])
    contexto = ft.Text("", size=FONTS["size_xs"], color=COLORS["text_muted"])
    mensaje = ft.Text("En cola — esperando al PC que emite…", size=FONTS["size_sm"],
                      color=COLORS["text_secondary"])

    cancelar_btn = create_button("Cancelar emisión", icon=ft.Icons.CLOSE, primary=False,
                                 on_click=lambda e: _pedir_abort())
    cerrar_btn = create_button("Cerrar", icon=ft.Icons.CHECK, primary=True,
                               on_click=lambda e: _cerrar())
    cerrar_btn.visible = False
    footer = ft.Row([ft.Container(expand=True), cancelar_btn, cerrar_btn], spacing=10)

    estado = {"abortando": False, "cerrado": False}
    _modal: list[AppModal] = []

    def _u(ctrl=None):
        try:
            (ctrl or _modal[0]).update()
        except Exception:
            pass

    def _avisar(msg: str, error: bool = False):
        if not show_snackbar:
            return
        try:
            show_snackbar(msg, error=True) if error else show_snackbar(msg)
        except Exception:  # noqa: BLE001
            pass

    def _cerrar(_=None):
        if estado["cerrado"]:
            return
        estado["cerrado"] = True
        try:
            _modal[0].close()
        except Exception:
            pass

    # ---------------- desistência (só antes da firma) ----------------
    def _puede_abortar(em: dict) -> bool:
        return (em.get("status") in ("PENDENTE", "PROCESSANDO")
                and em.get("fase") in (None, "GENERAR")
                and not em.get("abort_solicitado"))

    def _pedir_abort(_=None):
        estado["abortando"] = True
        cancelar_btn.disabled = True
        mensaje.value = "Cancelando… (solo se puede antes de la firma)"
        mensaje.color = COLORS["text_secondary"]
        _u()
        threading.Thread(target=_abort_worker, daemon=True).start()

    def _abort_worker():
        try:
            sifen_service.abortar(emission_id)
        except APIError as ex:
            # 409 = já assinou no meio do caminho: segue emitindo, e o operador
            # precisa saber que agora só sai por cancelación fiscal.
            estado["abortando"] = False
            cancelar_btn.visible = False
            mensaje.value = friendly_error(ex)
            mensaje.color = COLORS["accent_warning"]
            _u()
        except Exception as ex:  # noqa: BLE001
            estado["abortando"] = False
            cancelar_btn.disabled = False
            mensaje.value = str(ex)
            mensaje.color = COLORS["accent_error"]
            _u()

    # ---------------- pintura das etapas ----------------
    def _pintar_remotas(em: dict):
        """
        Traduz (fase, status) para a lista de etapas.

        Enquanto o job está na fila não há fase: mostramos a primeira etapa já
        girando — do ponto de vista do operador o trabalho começou.
        """
        fase, status = em.get("fase"), em.get("status")
        terminal = status in TERMINALES
        alcanzada = FASES_REMOTAS.index(fase) if fase in FASES_REMOTAS else (
            -1 if terminal else 0)
        for i, key in enumerate(FASES_REMOTAS):
            if status == "EMITIDA" or i < alcanzada:
                pasos[key].hecho()
            elif i == alcanzada and not terminal:
                pasos[key].activo()
            elif i == alcanzada and status == "FALHOU":
                pasos[key].fallido()
            else:
                pasos[key].cancelado() if terminal else pasos[key].pendiente()

    def _titulo_numero(em: dict):
        num = em.get("numero_formateado") or em.get("numero_documento")
        if num:
            titulo.value = f"Generando Factura Nº {num}"

    def _cargar_contexto():
        """Último número emitido: dá referência enquanto o novo não existe."""
        try:
            u = sifen_service.ultimo_numero() or {}
        except Exception:  # noqa: BLE001 — contexto é decorativo
            return
        num = u.get("numero_formateado") or u.get("numero_documento")
        contexto.value = f"Última emitida: Nº {num}" if num else "Primera factura de este sistema"
        _u(contexto)

    # ---------------- loop principal ----------------
    def _worker():
        em: dict = {}
        limite = time.monotonic() + POLL_MAX_S
        # Segue até o fim mesmo se a tela fechar: o KuDE tem de sair de qualquer
        # jeito, e as atualizações de UI viram no-op sozinhas.
        while time.monotonic() < limite:
            try:
                em = sifen_service.get_emision(emission_id) or {}
            except Exception as ex:  # noqa: BLE001 — rede instável não mata a tela
                mensaje.value = f"Reintentando… ({ex})"
                _u(mensaje)
                time.sleep(POLL_S)
                continue

            _titulo_numero(em)
            _pintar_remotas(em)
            if not estado["abortando"]:
                cancelar_btn.visible = _puede_abortar(em)
                mensaje.value = ("En cola — esperando al PC que emite…"
                                 if em.get("status") == "PENDENTE"
                                 else "Emitiendo el documento — no apagues la PC.")
            _u()

            if em.get("status") in TERMINALES:
                break
            time.sleep(POLL_S)

        cancelar_btn.visible = False
        status = em.get("status")

        if con_kude:
            if status == "EMITIDA":
                _paso_kude()
            else:
                pasos["KUDE"].cancelado()
                pasos["IMPRIMIR"].cancelado()
        _finalizar(em, status)

    def _paso_kude():
        """Etapas locais. Falhar aqui NÃO invalida a factura — só o papel."""
        pasos["KUDE"].activo()
        mensaje.value = "Generando la representación impresa…"
        _u()
        try:
            pdf = generar_kude(emission_id)
        except Exception as ex:  # noqa: BLE001
            _falla_kude("KUDE", ex)
            return
        pasos["KUDE"].hecho()
        pasos["IMPRIMIR"].activo()
        _u()
        try:
            imprimir_kude(emission_id, pdf)
        except Exception as ex:  # noqa: BLE001
            _falla_kude("IMPRIMIR", ex)
            return
        pasos["IMPRIMIR"].hecho()
        _u()

    def _falla_kude(key: str, ex: Exception):
        pasos[key].fallido()
        pasos[key].detail.value = str(ex)
        if key == "KUDE":
            pasos["IMPRIMIR"].cancelado()
        mensaje.value = ("Factura emitida, pero no se pudo imprimir el KuDE. "
                         "Reimprimila desde «Facturación».")
        mensaje.color = COLORS["accent_warning"]
        _u()

    def _finalizar(em: dict, status):
        cerrar_btn.visible = True

        if status == "EMITIDA":
            num = em.get("numero_formateado") or em.get("numero_documento") or ""
            titulo.value = f"✓ Factura Nº {num} emitida" if num else "✓ Factura emitida"
            titulo.color = COLORS["accent_success"]
            # Snackbar também: a tela fecha sozinha e o registro tem de sobrar.
            _avisar(f"✓ Factura Nº {num} emitida" if num else "✓ Factura emitida")
            if em.get("cdc"):
                contexto.value = f"CDC …{em['cdc'][-8:]}"
            if mensaje.color != COLORS["accent_warning"]:
                mensaje.value = "Entregá el KuDE al cliente."
                mensaje.color = COLORS["text_secondary"]
        elif status in ("ABORTADA", "CANCELADA"):
            titulo.value = "Emisión cancelada"
            titulo.color = COLORS["text_secondary"]
            mensaje.value = "No se emitió ningún documento — nada llegó al SET."
            mensaje.color = COLORS["text_secondary"]
        elif status == "FALHOU":
            titulo.value = "La factura no se emitió"
            titulo.color = COLORS["accent_error"]
            mensaje.value = em.get("error") or "Error desconocido."
            mensaje.color = COLORS["accent_error"]
            _avisar("✗ La factura electrónica no se emitió.", error=True)
        else:
            titulo.value = "Sigue en proceso"
            mensaje.value = ("Podés cerrar: la emisión continúa y aparece en "
                             "«Facturación» cuando termine.")
            mensaje.color = COLORS["text_secondary"]
        _u()

        if on_done:
            try:
                on_done(em)
            except Exception:  # noqa: BLE001
                pass

        # Só o sucesso fecha sozinho: erro e cancelación precisam ser lidos.
        if status == "EMITIDA":
            _autocierre()

    def _autocierre():
        for restante in range(AUTOCLOSE_S, 0, -1):
            if estado["cerrado"]:
                return
            cerrar_btn.content = ft.Row(
                [ft.Icon(ft.Icons.CHECK, color="#FFFFFF", size=18),
                 ft.Text(f"Cerrar ({restante})", size=FONTS["size_sm"],
                         weight=ft.FontWeight.W_600, color="#FFFFFF")],
                alignment=ft.MainAxisAlignment.CENTER, spacing=8, tight=True)
            _u(cerrar_btn)
            time.sleep(1)
        _cerrar()

    modal = AppModal(
        page=page,
        title="Factura electrónica",
        content=ft.Column([
            ft.Column([titulo, subtitulo, contexto], spacing=2, tight=True),
            ft.Divider(height=1, color=COLORS["border"]),
            ft.Container(
                content=ft.Column(list(pasos.values()), spacing=14, tight=True),
                padding=ft.Padding.symmetric(vertical=6),
                border_radius=RADIUS["md"],
            ),
            ft.Divider(height=1, color=COLORS["border"]),
            mensaje,
            footer,
        ], spacing=14, tight=True),
        width_pct=0.42,
    )
    _modal.append(modal)
    modal.open()
    threading.Thread(target=_cargar_contexto, daemon=True).start()
    threading.Thread(target=_worker, daemon=True).start()
    return modal
