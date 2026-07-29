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

# O XML normalmente já vem no fim da emissão, com a sessão do portal ainda viva
# (é ela que libera a rota pública do SET — ver `adapter._abrir_janela`). Se não
# veio, insistir aqui só ajuda enquanto essa janela durar: depois que a sessão
# morre, o mesmo CDC volta a dar 401 por tempo indeterminado. Medido 2026-07-29:
# documentos aprovados há semanas dão 401 sem sessão e 200 com ela. Por isso a
# espera é curta — é uma segunda chance, não uma aposta na publicação.
KUDE_ESPERA_S = 45      # teto de espera pelo XML (janela da sessão que emitiu)
KUDE_INTERVALO_S = 5    # ritmo das tentativas


def _bg(page: ft.Page, fn) -> None:
    """
    Roda `fn` em background NO executor da página.

    `threading.Thread` cru não pertence à página: os `update()` feitos de lá não
    chegavam ao cliente, e o progresso só aparecia quando o operador fechava e
    reabria a janela (o que forçava um rebuild). É o mesmo `run_thread` que as
    views usam.
    """
    try:
        page.run_thread(fn)
    except Exception:  # noqa: BLE001 — sem página utilizável, melhor thread solta que nada
        threading.Thread(target=fn, daemon=True).start()


def _mensaje_error(bruto: str | None) -> tuple[str, str]:
    """
    Traduz o erro técnico do job para algo que o cajero entenda.

    Devolve (mensagem, detalhe): a mensagem vai grande na tela, o detalhe fica
    pequeno embaixo — jogar `HTTPError: 401 Client Error` na cara de quem está
    no balcão não ajuda ninguém, mas o técnico ainda precisa do texto original.
    """
    cru = (bruto or "").strip()
    baixo = cru.lower()
    if not cru:
        return "No se pudo emitir la factura electrónica.", ""
    if "401" in baixo and "xml" in baixo:
        return ("La factura se emitió, pero el SET no entregó el documento firmado. "
                "Reimprimí el KuDE desde «Facturación»."), cru
    if any(p in baixo for p in ("connection", "timeout", "network", "getaddrinfo")):
        return "Sin conexión con el portal del SET. Revisá internet y probá de nuevo.", cru
    if "credenc" in baixo or "login" in baixo or "clave" in baixo:
        return "El portal rechazó las credenciales. Revisalas en «Configuración».", cru
    if "firma" in baixo or "sign" in baixo:
        return "No se pudo firmar el documento. Nada llegó al SET.", cru
    return "No se pudo emitir la factura electrónica.", cru


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


def _baixar_xml(emission_id: str) -> bytes:
    """
    XML assinado: tenta o backend e, se ele não tiver, busca aqui mesmo.

    O backend guarda o XML quando consegue, mas quem tem o adapter é ESTA máquina
    (a que emitiu). Sem este fallback, um documento que o SET publicou tarde ficava
    sem KuDE mesmo com o portal já servindo o XML.
    """
    try:
        return sifen_service.get_emision_xml(emission_id)
    except Exception as backend_err:  # noqa: BLE001
        em = sifen_service.get_emision(emission_id) or {}
        cdc = em.get("cdc")
        if not cdc:
            raise
        try:
            from services.sifen_adapter import build_provider
        except Exception:  # noqa: BLE001 — PC sem pipeline: só resta o backend
            raise backend_err
        creds = sifen_service.get_credenciais()
        prov = build_provider(creds["ruc"], creds["clave"], creds["pin"])
        # 1 tentativa: quem insiste é o laço de espera, que dá feedback na tela.
        return prov.baixar_xml(cdc, tries=1, delay=0)


def generar_kude(emission_id: str) -> bytes:
    """
    Baixa o XML assinado e monta o KuDE no formato configurado. Levanta em falha.

    A4 e P80 são o MESMO documento fiscal — muda só a representação impressa.
    Segue o ajuste de formato de impressão das faturas, para o operador não ter
    dois lugares diferentes para dizer que tipo de papel a impressora tem.
    """
    from services.pdf_generation.kude import KudeA4Generator, KudeP80Generator

    xml = _baixar_xml(emission_id)
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
                        con_kude: bool = True,
                        cerrar_luego: AppModal | None = None) -> AppModal:
    """
    Abre a tela de progresso de uma emissão já enfileirada.

    `emission_id` — job devolvido por `sifen_service.emitir`.
    `receptor`    — nome/documento de quem recebe (subtítulo).
    `on_done`     — chamado com a emissão final quando ela fecha (qualquer status).
    `con_kude`    — inclui gerar+imprimir o KuDE nesta máquina.
    `cerrar_luego` — modal de onde viemos (a conferência da caja). Passe-o em vez
                    de fechá-lo antes: ele é fechado depois, já coberto por este.
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
        """Repinta. Sem argumento, repinta cada controle vivo — não o dialog.

        Pedir o repinte ao dialog (`modal.update()`) não funciona depois que o
        conteúdo dele foi trocado: o patch sai vazio e a tela fica congelada,
        que era o sintoma de "só atualiza se eu minimizar e restaurar". Patch
        direto no controle montado funciona sempre. Falha aqui é esperada só
        quando a tela já fechou — mas engolir calado foi o que escondeu o
        progresso parado, então deixa rastro no log.
        """
        alvos = [ctrl] if ctrl is not None else [
            titulo, subtitulo, contexto, mensaje, footer, *pasos.values()]
        for alvo in alvos:
            try:
                alvo.update()
            except Exception as ex:  # noqa: BLE001
                print(f"[SIFEN] progress_update_failed ctrl={type(alvo).__name__} err={ex}")

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
        _bg(page, _abort_worker)

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
        # Segunda chance para o XML: a factura já está emitida, só falta o papel.
        # Insistir com aviso na tela é melhor que mandar o cajero reimprimir.
        limite = time.monotonic() + KUDE_ESPERA_S
        pdf, ultimo_erro = None, None
        while True:
            try:
                pdf = generar_kude(emission_id)
                break
            except Exception as ex:  # noqa: BLE001
                ultimo_erro = ex
                if time.monotonic() >= limite:
                    break
                espera = int(limite - time.monotonic())
                pasos["KUDE"].detail.value = (
                    f"El SET no entregó el XML — reintentando ({espera}s)")
                mensaje.value = "Buscando el documento firmado en el SET…"
                _u()
                time.sleep(KUDE_INTERVALO_S)
        if pdf is None:
            _falla_kude("KUDE", ultimo_erro or RuntimeError("XML no disponible"))
            return
        pasos["KUDE"].detail.value = ""
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
        pasos[key].detail.value = str(ex)[:120]
        if key == "KUDE":
            pasos["IMPRIMIR"].cancelado()
        mensaje.value = ("La factura SÍ se emitió, pero no se pudo imprimir el KuDE. "
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
            humano, detalhe = _mensaje_error(em.get("error"))
            mensaje.value = humano
            mensaje.color = COLORS["accent_error"]
            if detalhe:
                contexto.value = detalhe[:160]
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
            # Repinta o footer, não o botão: `cerrar_btn` nasce invisível e
            # controle invisível não é montado na página — `cerrar_btn.update()`
            # levantava "Control must be added to the page first" e a contagem
            # (e o próprio botão «Cerrar») nunca apareciam.
            _u(footer)
            time.sleep(1)
        _cerrar()

    cuerpo = ft.Column([
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
    ], spacing=14, tight=True)

    modal = AppModal(page=page, title="Factura electrónica", content=cuerpo,
                     width_pct=0.42)
    modal.open()
    _modal.append(modal)

    # Ordem importa. O modal de onde viemos (a conferência da caja) só é fechado
    # DEPOIS que este já está por cima, e não antes:
    #  - fechar antes e abrir em seguida deixa os dois empilhados no Flet e o
    #    cliente segue desenhando o ANTIGO (o progresso "não atualizava" porque
    #    nem estava sendo mostrado — só aparecia ao minimizar e restaurar);
    #  - trocar o conteúdo do MESMO dialog (`replace`) mostra a troca, mas os
    #    patches seguintes não repintam mais: a tela congela no primeiro quadro.
    # Fechá-lo já escondido atrás deste evita os dois casos. Medido em 2026-07-29.
    if cerrar_luego is not None:
        def _fechar_anterior():
            time.sleep(1.5)
            try:
                cerrar_luego.close()
            except Exception as ex:  # noqa: BLE001
                print(f"[SIFEN] cerrar_anterior_failed err={ex}")
        _bg(page, _fechar_anterior)
    _bg(page, _cargar_contexto)
    _bg(page, _worker)
    return modal
