from __future__ import annotations

"""
Cargo nuevo no balcão: fatura na hora, com valor livre.

Por que existe: o plano do Modo Caja partiu de que todo cargo (reconexión,
material, cuota de conexión, contribución extraordinaria) nasce na tesouraria
como fatura `AVULSA` e o balcão só cobra. Mas **a junta não tem setores** — quem
está no caixa é a tesouraria. Se aparece alguém para pagar algo que ninguém
lançou, o cajero tem de poder lançar e cobrar no mesmo atendimento.

O que isto faz: cria uma fatura `AVULSA` de verdade (numerada, auditável) para o
cliente do atendimento e devolve o `id`. A caja recarrega o contexto e o cargo
aparece em «OTROS CARGOS» já marcado, entrando no mesmo total, no mesmo recibo e
na mesma factura legal. **Não** existe cobro fora de fatura: o dinheiro sempre
cai em cima de um documento.

Valor e descrição são livres. O catálogo de produtos entra só como atalho, para
preencher descrição, preço e IVA de um cargo que a junta já tem cadastrado —
tudo segue editável depois de escolher.
"""

from datetime import datetime

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, RADIUS, create_text_field
from services.api_client import APIError
from services.invoice_service import invoice_service
from services.product_service import product_service
from utils.errors import friendly_error
from utils.formatters import format_currency
from i18n import t

_MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# (rótulo, tasa, afectación) — o que o SIFEN aceita para um item.
_IVA_OPCIONES = [("IVA 10%", 10, 1), ("IVA 5%", 5, 1), ("Exenta", 0, 3)]


def _money(v) -> str:
    return format_currency(v or 0, "Gs.")


def _entero(raw: str):
    """Valor em guaranis: sem centavos, e tolerante ao ponto de milhar."""
    raw = (raw or "").strip().replace(".", "").replace(",", "")
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def open_cargo_dialog(page: ft.Page, show_snackbar, client: dict, on_done=None):
    """
    Lança um cargo de valor livre para `client` e chama `on_done(invoice_id)`.

    `on_done` recebe o id da fatura criada — é o que a caja usa para deixar o
    cargo novo marcado quando recarrega o contexto.
    """
    hoy = datetime.now()
    productos: list[dict] = []

    descripcion = create_text_field(
        "¿Qué se cobra?", width=None,
        hint_text="Ej.: reconexión, caño de 1/2, multa por conexión clandestina")
    cantidad = create_text_field("Cantidad", value="1", width=110,
                                 keyboard_type=ft.KeyboardType.NUMBER)
    precio = ft.TextField(
        value="", hint_text="0", border=ft.InputBorder.NONE, autofocus=True,
        text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_700,
                                color=COLORS["text_primary"]),
        content_padding=ft.Padding.symmetric(horizontal=0, vertical=8),
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    err = ft.Text("", size=12, color=COLORS["accent_error"], visible=False)
    total_txt = ft.Text("", size=12, color=COLORS["text_muted"])

    catalogo = ft.Dropdown(
        label="Traer del catálogo (opcional)", width=None, options=[],
        hint_text="Cargando productos…",
    )

    estado = {"iva": (10, 1)}
    iva_row = ft.Row([], spacing=8)

    def _u(ctrl):
        try:
            ctrl.update()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- IVA
    def _iva_chip(label: str, tasa: int, afect: int) -> ft.Control:
        on = estado["iva"] == (tasa, afect)
        return ft.Container(
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=COLORS["text_primary"] if on else COLORS["text_secondary"]),
            padding=ft.Padding.symmetric(horizontal=0, vertical=9), expand=True,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.14, COLORS["accent_primary"]) if on
            else COLORS["bg_input"],
            border=ft.Border.all(1, COLORS["accent_primary"] if on else COLORS["border"]),
            border_radius=RADIUS["sm"], ink=True,
            on_click=lambda e, tt=tasa, aa=afect: _set_iva(tt, aa),
        )

    def _render_iva():
        iva_row.controls = [_iva_chip(*o) for o in _IVA_OPCIONES]
        _u(iva_row)

    def _set_iva(tasa: int, afect: int):
        estado["iva"] = (tasa, afect)
        _render_iva()

    # ------------------------------------------------------- total da linha
    def _render_total(_=None):
        val = _entero(precio.value)
        cant = _entero(cantidad.value) or 1
        total_txt.value = (f"Total del cargo: {_money(val * cant)}"
                           if val else "El valor es libre — lo escribís vos.")
        _u(total_txt)

    precio.on_change = _render_total
    cantidad.on_change = _render_total

    # ------------------------------------------------------------ catálogo
    def _cargar_productos():
        nonlocal productos
        try:
            productos = product_service.listar(activo=True) or []
        except Exception as exc:  # noqa: BLE001
            # Falhar aqui não impede lançar o cargo: o catálogo é só atalho.
            print(f"[Caja] cargo_products_failed err={exc}")
            productos = []
        catalogo.options = [
            ft.dropdown.Option(key=str(p["id"]),
                               text=f'{p.get("descripcion", "-")} · {_money(p.get("precio_unitario"))}')
            for p in productos
        ]
        catalogo.hint_text = ("Elegí para prellenar (o escribí a mano)" if productos
                              else "Sin productos en el catálogo — escribí a mano")
        catalogo.disabled = not productos
        _u(catalogo)

    def _pick_producto(e):
        p = next((x for x in productos if str(x["id"]) == str(catalogo.value)), None)
        if not p:
            return
        descripcion.value = p.get("descripcion", "")
        try:
            precio.value = str(int(float(p.get("precio_unitario") or 0)))
        except Exception:  # noqa: BLE001
            precio.value = ""
        estado["iva"] = (int(p.get("iva_tasa", 10)), int(p.get("iva_afectacion", 1)))
        _u(descripcion)
        _u(precio)
        _render_iva()
        _render_total()

    catalogo.on_change = _pick_producto

    # ------------------------------------------------------------- gravar
    def _confirmar(e=None):
        desc = (descripcion.value or "").strip()
        val = _entero(precio.value)
        cant = _entero(cantidad.value) or 1
        if len(desc) < 3:
            err.value = "Escribí qué se está cobrando — sale así en el recibo y en la factura."
            err.visible = True
            _u(err)
            return
        if not val or val <= 0:
            err.value = "Ingresá un valor mayor a cero."
            err.visible = True
            _u(err)
            return
        err.visible = False
        _u(err)

        tasa, afect = estado["iva"]
        payload = {
            "client_id": client.get("id"),
            "tipo": "AVULSA",
            "mes_referencia": hoy.month,
            "ano_referencia": hoy.year,
            "items": [{
                "descripcion": desc[:200], "cantidad": cant,
                "precio_unitario": float(val),
                "iva_tasa": tasa, "iva_afectacion": afect,
            }],
        }

        def work():
            try:
                factura = invoice_service.create_custom(payload)
            except APIError as exc:
                err.value = friendly_error(exc)
                err.visible = True
                _u(err)
                return
            try:
                modal.close()
            except Exception:  # noqa: BLE001
                pass
            nro = factura.get("numero_factura")
            show_snackbar(
                f"✓ Cargo de {_money(val * cant)} lanzado"
                + (f" (Fact. {nro})" if nro else "")
                + " — ya está en «Otros cargos».")
            if on_done:
                on_done(factura.get("id"))

        try:
            page.run_thread(work)
        except Exception:  # noqa: BLE001
            work()

    precio.on_submit = _confirmar

    _render_iva()
    _render_total()

    modal = AppModal(
        page=page,
        title="Cargo nuevo (valor libre)",
        content=ft.Column([
            ft.Text(
                f"{client.get('nombre_completo', '-')} · CI {client.get('ci_ruc', '-')}",
                size=13, weight=ft.FontWeight.W_600, color=COLORS["text_primary"]),
            ft.Text(
                "Se emite una factura del período "
                f"{_MES[hoy.month - 1]}/{hoy.year} y queda en «Otros cargos», lista "
                "para cobrar en este mismo atendimiento.",
                size=12, color=COLORS["text_muted"]),
            catalogo,
            descripcion,
            ft.Text("VALOR", size=11, weight=ft.FontWeight.W_700, color=COLORS["text_muted"]),
            ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Text("Gs.", size=16, weight=ft.FontWeight.W_600,
                                color=COLORS["text_muted"]),
                        ft.Container(content=precio, expand=True),
                    ], spacing=10),
                    bgcolor=COLORS["bg_input"],
                    border=ft.Border.all(1, COLORS["accent_primary"]),
                    border_radius=RADIUS["md"],
                    padding=ft.Padding.symmetric(horizontal=15, vertical=0),
                    height=50, expand=True,
                ),
                cantidad,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            total_txt,
            ft.Text("IVA DEL CARGO", size=11, weight=ft.FontWeight.W_700,
                    color=COLORS["text_muted"]),
            iva_row,
            ft.Text("Es el IVA que sale en la factura legal de este cargo — el agua "
                    "sigue con el de las configuraciones.",
                    size=11, color=COLORS["text_muted"]),
            err,
        ], spacing=11, tight=True, scroll=ft.ScrollMode.AUTO),
        actions=[
            ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
            ModalAction("Lanzar cargo", primary=True, on_click=_confirmar),
        ],
        width_pct=0.42,
    )
    modal.open()
    try:
        page.run_thread(_cargar_productos)
    except Exception:  # noqa: BLE001
        _cargar_productos()
    return modal
