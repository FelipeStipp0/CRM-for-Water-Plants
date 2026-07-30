from __future__ import annotations

"""
Atendimentos anteriores do balcão: reimprimir, reemitir e anular.

Por que existe: o cajero erra, a impressora engasga e o cliente volta com o papel
molhado. Antes disso só a `payments_view` (tesouraria) sabia anular, e reimprimir
não existia em lugar nenhum — a caja não tem para onde mandar o problema, porque
a junta não tem setores.

O que dá para fazer daqui:
- **reimprimir o recibo** de qualquer atendimento, idêntico ao original (sem marca
  de cópia: é o mesmo recibo, não uma segunda via de outra coisa);
- **reimprimir/reemitir o KuDE** da factura legal, inclusive quando a emissão
  ficou sem o XML na hora (`xml_pendiente`);
- **anular** o cobro, com motivo obrigatório, autor e hora na auditoria.

Sem limite de data: anula também cobro de dias anteriores. O estorno cai na caja
de **hoje**, não na do dia do erro — o cierre antigo fica como foi fechado e
conferido. Controle é a posteriori, pelo relatório do turno.

O prazo fiscal das 72 h vem de `config.fiscal` (a mesma constante que a legenda do
KuDE imprime). Fora da janela a tela explica o que dá para fazer, em espanhol, em
vez de mandar o cajero tentar e colher o erro cru do SIFEN.
"""

from datetime import date

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, RADIUS, create_text_field
from config.fiscal import PLAZO_CANCELACION_HORAS, dentro_del_plazo, horas_restantes
from services.api_client import APIError
from services.payment_service import payment_service
from services.pdf_generation.printer_manager import printer_manager
from services.pdf_generation.receipts import PaymentReceiptP80Generator
from utils.errors import friendly_error
from utils.formatters import format_currency, format_local, local_day_range_utc
from i18n import t


def _money(v) -> str:
    return format_currency(v or 0, "Gs.")


def open_atenciones_dialog(page: ft.Page, show_snackbar, get_company, on_changed=None):
    """
    Abre a lista de atendimentos.

    `get_company` é chamado só quando se imprime (os documentos precisam do
    cabeçalho da junta). `on_changed` avisa a caja que algo mudou — uma anulação
    muda o efectivo esperado do turno.
    """
    g_receipt = PaymentReceiptP80Generator()

    busca = create_text_field("", hint_text="Nº de recibo, nombre o CI…", width=None)
    lista = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=380)
    estado = ft.Text("", size=12, color=COLORS["text_muted"])
    filtros = {"dia": None, "solo_mi_caja": False}

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

    # ---------------------------------------------------------------- carga
    def _cargar():
        estado.value = "Buscando…"
        _u(estado)
        desde = hasta = None
        if filtros["dia"]:
            desde, hasta = local_day_range_utc(filtros["dia"])
        try:
            rows = payment_service.atenciones(
                q=(busca.value or "").strip() or None,
                desde=desde, hasta=hasta,
                solo_mi_caja=filtros["solo_mi_caja"], limit=30,
            )
        except APIError as exc:
            estado.value = friendly_error(exc)
            estado.color = COLORS["accent_error"]
            _u(estado)
            return
        estado.color = COLORS["text_muted"]
        estado.value = ("Ningún cobro con esos filtros." if not rows
                        else f"{len(rows)} cobro(s).")
        lista.controls = [_fila(r) for r in rows]
        _u(estado)
        _u(lista)

    busca.on_change = lambda e: _bg(_cargar)
    busca.on_submit = lambda e: _bg(_cargar)

    def _set_dia(dia):
        filtros["dia"] = dia
        chips.controls = _chips()
        _u(chips)
        _bg(_cargar)

    def _toggle_mi_caja():
        filtros["solo_mi_caja"] = not filtros["solo_mi_caja"]
        chips.controls = _chips()
        _u(chips)
        _bg(_cargar)

    def _chip(label: str, on: bool, on_click) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, size=12, weight=ft.FontWeight.W_600,
                            color=COLORS["text_primary"] if on else COLORS["text_secondary"]),
            padding=ft.Padding.symmetric(horizontal=12, vertical=7),
            bgcolor=(ft.Colors.with_opacity(0.14, COLORS["accent_primary"]) if on
                     else COLORS["bg_input"]),
            border=ft.Border.all(1, COLORS["accent_primary"] if on else COLORS["border"]),
            border_radius=RADIUS["sm"], ink=True, on_click=lambda e: on_click(),
        )

    def _chips() -> list:
        hoy = date.today()
        return [
            _chip("Todos", filtros["dia"] is None, lambda: _set_dia(None)),
            _chip("Hoy", filtros["dia"] == hoy, lambda: _set_dia(hoy)),
            _chip("Ayer", filtros["dia"] == date.fromordinal(hoy.toordinal() - 1),
                  lambda: _set_dia(date.fromordinal(hoy.toordinal() - 1))),
            _chip("Mi caja", filtros["solo_mi_caja"], _toggle_mi_caja),
        ]

    chips = ft.Row(_chips(), spacing=7, wrap=True)

    # ---------------------------------------------------------------- linha
    def _fila(r: dict) -> ft.Control:
        anulada = bool(r.get("anulada"))
        em_status = r.get("emission_status")
        emitida = em_status == "EMITIDA"
        xml_pend = bool(r.get("emission_xml_pendiente"))

        etiquetas = [
            ft.Text(f"Rec. {r.get('numero_recibo_fmt', '—')}", size=13,
                    weight=ft.FontWeight.W_700, color=COLORS["text_primary"]),
            ft.Text(format_local(r.get("fecha_pago"), "%d/%m %H:%M"), size=12,
                    color=COLORS["text_secondary"]),
            ft.Text(str(r.get("metodo", "")).capitalize(), size=11,
                    color=COLORS["text_muted"]),
        ]
        if r.get("mi_caja"):
            etiquetas.append(ft.Text("· mi caja", size=11, color=COLORS["text_muted"]))
        if emitida:
            etiquetas.append(ft.Text(
                f"· Fact. {r.get('emission_numero') or '—'}"
                + (" (sin KuDE)" if xml_pend else ""),
                size=11, color=COLORS["accent_secondary"]))
        elif em_status:
            etiquetas.append(ft.Text(f"· factura {em_status.lower()}", size=11,
                                     color=COLORS["accent_warning"]))

        acciones = [
            _mini("Recibo", ft.Icons.PRINT_OUTLINED,
                  lambda: _bg(lambda: _reimprimir_recibo(r))),
        ]
        if r.get("emission_id") and emitida:
            acciones.append(_mini(
                "Reemitir KuDE" if xml_pend else "Factura", ft.Icons.RECEIPT_LONG_OUTLINED,
                lambda: _bg(lambda: _reimprimir_kude(r))))
        if not anulada:
            acciones.append(_mini("Anular", ft.Icons.BLOCK, lambda: _pedir_anular(r),
                                  danger=True))

        cuerpo = [
            ft.Row(etiquetas, spacing=8, wrap=True),
            ft.Row([
                ft.Text(r.get("client_name", "-"), size=12,
                        color=COLORS["text_secondary"], expand=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(_money(r.get("valor_total")), size=13,
                        weight=ft.FontWeight.W_700,
                        color=COLORS["text_muted"] if anulada else COLORS["text_primary"]),
            ], spacing=8),
        ]
        if anulada:
            cuerpo.append(ft.Text(
                f"ANULADO por {r.get('anulada_por') or '—'} · "
                f"{format_local(r.get('anulada_at'), '%d/%m %H:%M')}"
                + (f" · {r.get('motivo_anulacion')}" if r.get("motivo_anulacion") else ""),
                size=11, color=COLORS["accent_error"]))
        cuerpo.append(ft.Row(acciones, spacing=6, wrap=True))

        return ft.Container(
            content=ft.Column(cuerpo, spacing=5, tight=True),
            padding=ft.Padding.symmetric(horizontal=11, vertical=9),
            bgcolor=COLORS["bg_elevated"], border_radius=RADIUS["sm"],
            border=ft.Border.all(1, COLORS["accent_error"] if anulada else COLORS["border"]),
            opacity=0.65 if anulada else 1.0,
        )

    def _mini(label: str, icon, on_click, danger: bool = False) -> ft.Control:
        col = COLORS["accent_error"] if danger else COLORS["accent_secondary"]
        return ft.Container(
            content=ft.Row([ft.Icon(icon, size=13, color=col),
                            ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=col)],
                           spacing=5, tight=True),
            padding=ft.Padding.symmetric(horizontal=9, vertical=5),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.4, col)),
            border_radius=RADIUS["sm"], ink=True, on_click=lambda e: on_click(),
        )

    # ------------------------------------------------------------ impressão
    def _reimprimir_recibo(r: dict):
        try:
            result = payment_service.get_by_group(r["grupo_pagamento"])
            payload = dict(result)
            payload["company"] = get_company()
            pdf = g_receipt.generate(payload)
            printer_manager.print_pdf(
                pdf, printer_type="thermal",
                job_name=f"receipt_{r['grupo_pagamento'][:20]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] reprint_receipt_failed err={exc}")
            show_snackbar(
                f"No se pudo reimprimir el recibo {r.get('numero_recibo_fmt', '')}: "
                f"{exc}", error=True)
            return
        show_snackbar(f"Recibo {r.get('numero_recibo_fmt', '')} reimpreso.")

    def _reimprimir_kude(r: dict):
        # Import local: `sifen_progress` puxa o pipeline de emissão, e esta tela
        # abre em máquinas que só reimprimem.
        from components.sifen_progress import imprimir_kude

        show_snackbar("Generando el KuDE…")
        try:
            imprimir_kude(r["emission_id"])
        except Exception as exc:  # noqa: BLE001
            print(f"[Caja] reprint_kude_failed err={exc}")
            show_snackbar(
                "No se pudo generar el KuDE: el SET todavía no entrega el XML "
                f"firmado de esta factura ({exc}). Probá de nuevo en unos minutos.",
                error=True)
            return
        show_snackbar(f"Factura Nº {r.get('emission_numero') or ''} reimpresa.")

    # -------------------------------------------------------------- anulação
    def _aviso_fiscal(r: dict) -> ft.Control | None:
        """O que a anulação faz (ou não) com a factura legal deste cobro."""
        if not r.get("emission_id") or r.get("emission_status") != "EMITIDA":
            return None
        emitida_en = r.get("emission_at")
        if dentro_del_plazo(emitida_en):
            restante = horas_restantes(emitida_en)
            plazo = (f" Quedan unas {int(restante)} h del plazo de "
                     f"{PLAZO_CANCELACION_HORAS} h." if restante is not None else "")
            return ft.Text(
                f"Este cobro tiene factura electrónica Nº {r.get('emission_numero') or '—'}. "
                "Al anular se solicita la cancelación en el SET." + plazo,
                size=12, color=COLORS["text_secondary"])
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=17,
                            color=COLORS["accent_warning"]),
                    ft.Text(f"Pasaron más de {PLAZO_CANCELACION_HORAS} horas de la emisión",
                            size=13, weight=ft.FontWeight.W_700,
                            color=COLORS["accent_warning"]),
                ], spacing=8),
                ft.Text(
                    f"La factura Nº {r.get('emission_numero') or '—'} ya no se puede "
                    "cancelar en el SET: el plazo que la propia SET imprime en el KuDE "
                    f"es de {PLAZO_CANCELACION_HORAS} horas desde la emisión.\n\n"
                    "Podés anular el cobro acá: la plata vuelve a la caja y las facturas "
                    "se restauran. Pero la factura electrónica sigue vigente ante el SET "
                    "— para corregirla hace falta una nota de crédito, que se emite en el "
                    "portal del SET.",
                    size=12, color=COLORS["text_secondary"]),
            ], spacing=7, tight=True),
            padding=11, border_radius=RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.10, COLORS["accent_warning"]),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, COLORS["accent_warning"])),
        )

    def _pedir_anular(r: dict):
        motivo = create_text_field("Motivo de la anulación (obligatorio)",
                                   multiline=True, min_lines=2, max_lines=3, width=None)
        err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
        aviso = _aviso_fiscal(r)

        contenido = [
            ft.Text(
                "Se restauran las facturas cobradas y se registra un estorno en la caja "
                "de hoy. El cierre del día del cobro no cambia. Queda constancia de quién "
                "anuló, cuándo y por qué.",
                size=13, color=COLORS["text_secondary"]),
        ]
        if aviso:
            contenido.append(aviso)
        contenido += [motivo, err]

        def _confirmar(e):
            texto = (motivo.value or "").strip()
            if len(texto) < 3:
                err.value = "Indicá el motivo (mín. 3 caracteres)."
                err.visible = True
                _u(err)
                return
            prompt.close()

            def work():
                try:
                    result = payment_service.anular(r["id"], texto)
                except APIError as exc:
                    show_snackbar(friendly_error(exc), error=True)
                    return
                sifen = (result or {}).get("sifen")
                recibo = r.get("numero_recibo_fmt", "")
                if not sifen:
                    show_snackbar(f"✓ Recibo {recibo} anulado")
                elif sifen.get("cancelacion") == "solicitada":
                    show_snackbar(f"✓ Recibo {recibo} anulado — cancelación de la "
                                  "factura electrónica solicitada.")
                else:
                    show_snackbar(
                        f"Recibo {recibo} anulado, pero la cancelación de la factura "
                        "electrónica falló — revisala en «Facturación».", error=True)
                _cargar()
                if on_changed:
                    on_changed()

            _bg(work)

        prompt = AppModal(
            page=page,
            title=f"Anular recibo {r.get('numero_recibo_fmt', '')}",
            content=ft.Column(contenido, spacing=12, tight=True,
                              scroll=ft.ScrollMode.AUTO),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: prompt.close()),
                ModalAction("Anular cobro", danger=True, on_click=_confirmar),
            ],
            width_pct=0.44,
        )
        prompt.open()

    modal = AppModal(
        page=page,
        title="Atenciones anteriores",
        content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.SEARCH, size=19, color=COLORS["text_muted"]),
                    ft.Container(content=busca, expand=True)], spacing=9),
            chips,
            estado,
            lista,
        ], spacing=11, tight=True),
        actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
        width_pct=0.55,
    )
    modal.open()
    _bg(_cargar)
    return modal
