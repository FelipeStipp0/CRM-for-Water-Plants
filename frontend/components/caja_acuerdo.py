from __future__ import annotations

"""
Acuerdo de pago (parcelamento) — a tela do balcão.

Regras que a tela obedece (e explica ao cajero em voz alta):

- **Total = soma exata das faturas escolhidas.** Sem juros, multa ou ajuste.
- **Entrada opcional:** se o cliente paga algo no ato, isso é um cobro normal
  (com recibo) e reduz o total antes de dividir.
- **Número de parcelas livre** — quem decide é o cajero.
- **Primeira parcela:** neste mês (como fatura própria, porque o mês corrente já
  foi faturado) ou no mês seguinte. Escolha do cajero, no ato.
- **IVA da cuota escolhido em cada acordo:** a parcela não é consumo de água e
  não herda o IVA das configurações.
- **Um acordo ativo por cliente:** se já existe um, este refaz o acordo juntando
  o saldo remanescente com a dívida nova — e aí entra *tudo* o que está em
  aberto, não um pedaço.

Ao fechar, as faturas antigas viram ANULADA com saldo zero: o cliente sai da
dívida e do corte na hora, e a dívida passa a viver nas parcelas, somadas à
fatura do mês correspondente. Parcela vencida cai no fluxo de corte existente
porque quem vence é a própria fatura do mês.
"""

from datetime import date
import threading

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, RADIUS, create_text_field
from services.agreement_service import agreement_service
from services.api_client import APIError
from services.payment_service import payment_service
from services.pdf_generation.agreements import AgreementP80Generator
from services.pdf_generation.printer_manager import printer_manager
from services.pdf_generation.receipts import PaymentReceiptP80Generator
from utils.errors import friendly_error
from utils.formatters import format_currency
from i18n import t

_MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _money(v) -> str:
    return format_currency(v or 0, "Gs.")


def _add_month(mes: int, ano: int, n: int) -> tuple[int, int]:
    idx = ano * 12 + (mes - 1) + n
    return idx % 12 + 1, idx // 12


def _num(raw: str):
    raw = (raw or "").strip().replace(".", "").replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def open_acuerdo_dialog(page: ft.Page, show_snackbar, ctx: dict, get_company,
                        metodo: str = "EFECTIVO", on_done=None):
    """
    Abre a tela do acordo para o cliente do `ctx` (payment-context da caja).

    `on_done` é chamado depois de fechar o acordo (a caja recarrega o cliente:
    a dívida virou parcelas e a grade de meses mudou).
    """
    client = ctx.get("client") or {}
    facturas = [f for f in (ctx.get("facturas") or [])
                if float(f.get("saldo_devedor") or 0) > 0]
    acuerdo_activo = ctx.get("acuerdo")
    refacer = bool(acuerdo_activo)

    # Refazer consolida tudo: escolher um pedaço deixaria duas dívidas do mesmo
    # cliente vivas em paralelo, e o corte veria a metade errada.
    sel: dict[str, bool] = {f["id"]: True for f in facturas}

    g_acuerdo = AgreementP80Generator()
    g_receipt = PaymentReceiptP80Generator()

    def _bg(fn):
        try:
            page.run_thread(fn)
        except Exception:  # noqa: BLE001
            fn()

    def _u(ctrl):
        try:
            ctrl.update()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- campos
    entrada_field = create_text_field(
        "Entrada (opcional)", hint_text="0", width=None,
        keyboard_type=ft.KeyboardType.NUMBER)
    n_field = create_text_field(
        "Cuotas", value="3", width=110, keyboard_type=ft.KeyboardType.NUMBER)

    tasa_dd = ft.Dropdown(
        label="IVA de la cuota",
        value="10",
        options=[ft.dropdown.Option("10", "10%"), ft.dropdown.Option("5", "5%"),
                 ft.dropdown.Option("0", "0%")],
        width=150, filled=True, fill_color=COLORS["bg_input"], border_radius=10,
        border_color=COLORS["border"], focused_border_color=COLORS["border_focus"],
    )
    afect_dd = ft.Dropdown(
        label="Afectación",
        value="1",
        options=[ft.dropdown.Option("1", "Gravado"), ft.dropdown.Option("2", "Parcial"),
                 ft.dropdown.Option("3", "Exento")],
        width=170, filled=True, fill_color=COLORS["bg_input"], border_radius=10,
        border_color=COLORS["border"], focused_border_color=COLORS["border_focus"],
    )

    hoy = date.today()
    mes_sig, ano_sig = _add_month(hoy.month, hoy.year, 1)
    inicio = {"corriente": False}

    total_txt = ft.Text("", size=13, color=COLORS["text_secondary"])
    resumen_txt = ft.Text("", size=22, weight=ft.FontWeight.W_800,
                          color=COLORS["text_primary"])
    cronograma = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=150)
    err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
    _sim_timer: list[threading.Timer] = []
    enviando = {"ok": False}

    # ------------------------------------------------------- faturas do acordo
    def _total_sel() -> float:
        return sum(float(f.get("saldo_devedor") or 0) for f in facturas if sel.get(f["id"]))

    def _fila_factura(f: dict) -> ft.Control:
        marcado = sel.get(f["id"], False)
        per = f"{_MES[int(f.get('mes_referencia', 1)) - 1]}/{f.get('ano_referencia', '')}"
        es_cargo = f.get("tipo") != "CONSUMO"
        etiqueta = "otros cargos" if es_cargo else "agua"
        if float(f.get("cuota_valor") or 0):
            etiqueta = "incluye cuota"

        def _toggle(e):
            if refacer:
                return
            sel[f["id"]] = not sel.get(f["id"], False)
            _render_facturas()
            _pedir_simulacion()

        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CHECK_BOX if marcado else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                        size=17,
                        color=COLORS["accent_secondary"] if marcado else COLORS["text_muted"]),
                ft.Text(per, size=12, weight=ft.FontWeight.W_600,
                        color=COLORS["text_primary"], width=70),
                ft.Text(etiqueta, size=11, color=COLORS["text_muted"], expand=True),
                ft.Text(_money(f.get("saldo_devedor")), size=12,
                        weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ], spacing=8),
            padding=ft.Padding.symmetric(horizontal=9, vertical=6),
            bgcolor=COLORS["bg_input"], border_radius=RADIUS["sm"],
            border=ft.Border.all(1, COLORS["accent_secondary"] if marcado else COLORS["border"]),
            ink=not refacer, on_click=None if refacer else _toggle,
        )

    lista_facturas = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, height=140)

    def _render_facturas():
        lista_facturas.controls = ([_fila_factura(f) for f in facturas]
                                   or [ft.Text("Sin facturas en abierto.", size=12,
                                               color=COLORS["text_muted"])])
        _u(lista_facturas)

    # ------------------------------------------------------------- simulação
    def _pedir_simulacion(_=None):
        """Debounce: o cajero digita o número de parcelas, não colamos em cada tecla."""
        for tmr in _sim_timer:
            try:
                tmr.cancel()
            except Exception:  # noqa: BLE001
                pass
        _sim_timer.clear()
        tmr = threading.Timer(0.3, lambda: _bg(_simular))
        tmr.daemon = True
        _sim_timer.append(tmr)
        tmr.start()

    def _simular():
        total = _total_sel()
        if refacer:
            total += float((acuerdo_activo or {}).get("saldo_pendiente") or 0)
        entrada = _num(entrada_field.value) or 0
        try:
            n = int((n_field.value or "0").strip())
        except ValueError:
            n = 0

        total_txt.value = (
            f"Deuda seleccionada {_money(total)}"
            + (f"  ·  entrada {_money(entrada)}" if entrada else ""))
        _u(total_txt)

        if total <= 0 or n < 1:
            resumen_txt.value = "—"
            cronograma.controls = [ft.Text(
                "Elegí las facturas y cuántas cuotas." if n >= 1 else
                "Indicá el número de cuotas.", size=12, color=COLORS["text_muted"])]
            _u(resumen_txt)
            _u(cronograma)
            return
        if entrada >= total:
            resumen_txt.value = "—"
            cronograma.controls = [ft.Text(
                "La entrada cubre toda la deuda: cobralo como pago normal, sin acuerdo.",
                size=12, color=COLORS["accent_warning"])]
            _u(resumen_txt)
            _u(cronograma)
            return

        try:
            r = agreement_service.simular(total, n, entrada)
        except APIError as exc:
            cronograma.controls = [ft.Text(friendly_error(exc), size=12,
                                           color=COLORS["accent_error"])]
            _u(cronograma)
            return

        valores = [float(v) for v in (r.get("valores") or [])]
        mes, ano = (hoy.month, hoy.year) if inicio["corriente"] else (mes_sig, ano_sig)
        filas = []
        for i, valor in enumerate(valores):
            filas.append(ft.Row([
                ft.Text(f"Cuota {i + 1}", size=12, color=COLORS["text_secondary"], width=64),
                ft.Text(f"{_MES[mes - 1]}/{ano}", size=12,
                        color=COLORS["text_muted"], width=70),
                ft.Container(expand=True),
                ft.Text(_money(valor), size=12, weight=ft.FontWeight.W_600,
                        color=COLORS["text_primary"]),
            ], spacing=6))
            mes, ano = _add_month(mes, ano, 1)
        cronograma.controls = filas
        iguales = len(set(valores)) == 1
        resumen_txt.value = (f"{n} × {_money(valores[0])}" if iguales
                            else f"{n} cuotas de {_money(valores[0])} "
                                 f"(última {_money(valores[-1])})")
        _u(resumen_txt)
        _u(cronograma)

    entrada_field.on_change = _pedir_simulacion
    n_field.on_change = _pedir_simulacion

    def _set_n(n: int):
        n_field.value = str(n)
        _u(n_field)
        _pedir_simulacion()

    def _chip(label: str, on_click, on: bool = False) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, size=12, weight=ft.FontWeight.W_600,
                            color=COLORS["text_primary"] if on else COLORS["text_secondary"]),
            padding=ft.Padding.symmetric(horizontal=12, vertical=7),
            bgcolor=(ft.Colors.with_opacity(0.14, COLORS["accent_primary"]) if on
                     else COLORS["bg_input"]),
            border=ft.Border.all(1, COLORS["accent_primary"] if on else COLORS["border"]),
            border_radius=RADIUS["sm"], ink=True, on_click=lambda e: on_click(),
        )

    def _inicio_chips() -> list:
        return [
            _chip(f"Empieza en {_MES[mes_sig - 1]}/{ano_sig}",
                  lambda: _set_inicio(False), not inicio["corriente"]),
            _chip(f"Empieza este mes ({_MES[hoy.month - 1]})",
                  lambda: _set_inicio(True), inicio["corriente"]),
        ]

    inicio_row = ft.Row(_inicio_chips(), spacing=7, wrap=True)

    def _set_inicio(corriente: bool):
        inicio["corriente"] = corriente
        inicio_row.controls = _inicio_chips()
        _u(inicio_row)
        _pedir_simulacion()

    # ------------------------------------------------------------- fechamento
    def _cerrar_acuerdo():
        entrada = _num(entrada_field.value) or 0
        try:
            n = int((n_field.value or "0").strip())
        except ValueError:
            n = 0
        if n < 1:
            err.value = "Indicá cuántas cuotas."
            err.visible = True
            _u(err)
            return
        ids = [f["id"] for f in facturas if sel.get(f["id"])]
        if not ids and not refacer:
            err.value = "Elegí al menos una factura para parcelar."
            err.visible = True
            _u(err)
            return
        # Trava de reentrada: o botão do rodapé é reconstruído pelo AppModal, então
        # `disabled` não sobrevive ao repinte — a guarda é este flag.
        if enviando["ok"]:
            return
        enviando["ok"] = True
        err.value = "Cerrando el acuerdo…"
        err.color = COLORS["text_secondary"]
        err.visible = True
        _u(err)

        def work():
            try:
                r = agreement_service.crear(
                    client_id=client.get("id"),
                    n_parcelas=n,
                    invoice_ids=None if refacer else ids,
                    entrada=entrada,
                    metodo=metodo,
                    primera_en_mes_corriente=inicio["corriente"],
                    cuota_iva_tasa=int(tasa_dd.value or 10),
                    cuota_iva_afectacion=int(afect_dd.value or 1),
                    aplicar_subsidio=bool(client.get("has_sponsor")),
                )
            except APIError as exc:
                enviando["ok"] = False
                err.value = friendly_error(exc)
                err.color = COLORS["accent_error"]
                err.visible = True
                _u(err)
                return

            try:
                modal.close()
            except Exception:  # noqa: BLE001
                pass

            acuerdo = (r or {}).get("acuerdo") or {}
            _imprimir(acuerdo, (r or {}).get("entrada_grupo"))
            show_snackbar(
                f"✓ Acuerdo Nº {acuerdo.get('numero_fmt', '')} — "
                f"{acuerdo.get('n_parcelas', n)} cuotas")
            if on_done:
                on_done(r)

        _bg(work)

    def _imprimir(acuerdo: dict, entrada_grupo):
        """Comprobante do acordo (sempre) + recibo da entrada (quando houve)."""
        company = get_company()
        try:
            payload = dict(acuerdo)
            payload["client"] = client
            payload["company"] = company
            printer_manager.print_pdf(
                g_acuerdo.generate(payload), printer_type="thermal",
                job_name=f"acuerdo_{acuerdo.get('numero', '')}")
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] print_acuerdo_failed err={exc}")
            show_snackbar("El acuerdo quedó registrado, pero no se pudo imprimir "
                          "el comprobante.", error=True)

        if not entrada_grupo:
            return
        try:
            result = payment_service.get_by_group(entrada_grupo)
            payload = dict(result)
            payload["company"] = company
            printer_manager.print_pdf(
                g_receipt.generate(payload), printer_type="thermal",
                job_name=f"receipt_{str(entrada_grupo)[:20]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] print_entrada_receipt_failed err={exc}")
            show_snackbar("No se pudo imprimir el recibo de la entrada.", error=True)

    # -------------------------------------------------------------- montagem
    cabecera = [
        ft.Text(client.get("nombre_completo", "-"), size=16,
                weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
        ft.Text(f"CI {client.get('ci_ruc', '-')} · Medidor "
                f"{client.get('numero_medidor', '-')}", size=12,
                color=COLORS["text_muted"]),
    ]
    if refacer:
        cabecera.append(ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=17, color=COLORS["accent_warning"]),
                    ft.Text(f"Ya tiene el acuerdo Nº {acuerdo_activo.get('numero_fmt')} "
                            "en curso", size=13, weight=ft.FontWeight.W_700,
                            color=COLORS["accent_warning"]),
                ], spacing=8),
                ft.Text(
                    "Un cliente tiene un acuerdo por vez. Este rehace el acuerdo: junta "
                    f"el saldo que falta ({_money(acuerdo_activo.get('saldo_pendiente'))}) "
                    "con la deuda nueva y arma un cronograma solo. Por eso entra todo lo "
                    "que está en abierto, no una parte.",
                    size=12, color=COLORS["text_secondary"]),
            ], spacing=6, tight=True),
            padding=11, border_radius=RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.10, COLORS["accent_warning"]),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, COLORS["accent_warning"])),
        ))

    modal = AppModal(
        page=page,
        title="Acuerdo de pago",
        content=ft.Column([
            ft.Column(cabecera, spacing=4, tight=True),
            ft.Text("DEUDA QUE ENTRA EN EL ACUERDO", size=11,
                    weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
            lista_facturas,
            total_txt,
            ft.Divider(height=1, color=COLORS["border_subtle"]),
            ft.Row([entrada_field, n_field], spacing=10),
            ft.Row([_chip("2 cuotas", lambda: _set_n(2)),
                    _chip("3 cuotas", lambda: _set_n(3)),
                    _chip("6 cuotas", lambda: _set_n(6)),
                    _chip("12 cuotas", lambda: _set_n(12))], spacing=7, wrap=True),
            inicio_row,
            ft.Text("La cuota no es consumo de agua: su IVA se elige acá, en cada acuerdo.",
                    size=11, color=COLORS["text_muted"]),
            ft.Row([tasa_dd, afect_dd], spacing=10, wrap=True),
            ft.Divider(height=1, color=COLORS["border_subtle"]),
            resumen_txt,
            cronograma,
            ft.Text(
                "Al cerrar, las facturas de arriba quedan anuladas con saldo cero y el "
                "cliente sale de la deuda y del corte. La cuota de cada mes se suma a la "
                "factura de ese mes. Total exacto, sin intereses ni recargos.",
                size=11, color=COLORS["text_muted"]),
            err,
        ], spacing=11, tight=True, scroll=ft.ScrollMode.AUTO),
        actions=[
            ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
            ModalAction("Cerrar acuerdo", primary=True,
                        on_click=lambda e: _cerrar_acuerdo()),
        ],
        width_pct=0.5,
    )
    modal.open()
    _render_facturas()
    _pedir_simulacion()
    return modal
