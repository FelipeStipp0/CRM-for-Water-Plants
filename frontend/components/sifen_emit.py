from __future__ import annotations

"""
WMApp Frontend - Modal de emissão de factura electrónica (SIFEN).

Reutilizável em Facturación e Finanzas (inclusive p/ faturar itens antigos).
- Itens vêm do **catálogo de produtos** (product_picker) — não há mais texto livre;
  uma FE precisa referenciar uma venda cadastrada.
- Botão **Consultar** resolve o documento no registro DNIT (contribuyente = RUC ACTIVO,
  mostra razón social; senão no contribuyente por CI, com nome do cadastro/editável e
  tipo de documento). O nome aparece na hora.
A emissão em si roda no coordenador local (sessão única); aqui enfileira e acompanha.
"""

import threading
import time
import uuid

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.product_picker import ProductPickerRow
from components.theme import COLORS, create_button, create_text_field
from utils.errors import friendly_error
from services.api_client import APIError
from services.sifen_service import sifen_service
from services.product_service import product_service
from services.client_service import client_service

# iTipIDRec — tipos p/ no contribuyente (espelha TIPO_ID_DESC do backend)
TIPO_ID_OPCIONES = [
    ("1", "Cédula paraguaya"), ("2", "Pasaporte"), ("3", "Cédula extranjera"),
    ("4", "Carnet de residencia"), ("5", "Innominado"),
    ("6", "Tarjeta Diplomática de exoneración fiscal"), ("9", "Otro"),
]


def open_sifen_emit_modal(page: ft.Page, show_snackbar, *,
                          default_doc: str | None = None, on_done=None):
    doc_field = create_text_field(label="Documento (CI/RUC)", value=default_doc or "",
                                  hint_text="7184730", width=220)
    natureza_badge = ft.Container(visible=False, padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                  border_radius=12)
    natureza_text = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
    natureza_badge.content = natureza_text
    nombre_field = create_text_field(label="Nombre / Razón social", width=380)
    tipo_id_dd = ft.Dropdown(
        label="Tipo de documento", width=240, value="1", visible=False,
        options=[ft.dropdown.Option(key=k, text=txt) for k, txt in TIPO_ID_OPCIONES],
    )
    consultar_progress = ft.ProgressRing(width=16, height=16, visible=False)

    # estado da consulta
    state = {"es_contribuyente": None}  # None=não consultado, True/False

    items_column = ft.Column(spacing=8)
    picker_rows: list[ProductPickerRow] = []
    products: list[dict] = []
    total_text = ft.Text("Total: Gs 0", size=13, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
    status_text = ft.Text("", size=13)
    progress = ft.ProgressRing(width=16, height=16, visible=False)
    add_btn = create_button("Agregar ítem", icon=ft.Icons.ADD, primary=False, disabled=True,
                            on_click=lambda e: _add_row())

    _modal_ref: list[AppModal] = []

    def _safe_update(ctrl=None):
        try:
            (ctrl or _modal_ref[0]).update()
        except Exception:
            pass

    def _set_status(msg, color=None):
        status_text.value = msg
        status_text.color = color or COLORS["text_secondary"]
        _safe_update(status_text)

    # ---------- total ----------
    def _recalc(ev=None):
        total = 0
        for r in picker_rows:
            raw = (r.precio.value or "").strip().replace(".", "").replace(",", "")
            qty = (r.qty.value or "1").strip()
            if raw.isdigit():
                total += int(raw) * (int(qty) if qty.isdigit() and int(qty) > 0 else 1)
        total_text.value = f"Total: Gs {total:,}".replace(",", ".")
        _safe_update(total_text)

    # ---------- itens ----------
    def _remove_row(row):
        if len(picker_rows) <= 1:
            return
        picker_rows.remove(row)
        items_column.controls.remove(row)
        _recalc()
        _safe_update(items_column)

    def _add_row():
        row = ProductPickerRow(products, on_change=_recalc, on_remove=_remove_row)
        picker_rows.append(row)
        items_column.controls.append(row)
        _safe_update(items_column)

    def _load_products():
        nonlocal products
        try:
            products = product_service.listar(activo=True) or []
        except Exception as ex:  # noqa: BLE001
            products = []
            _set_status(str(ex), COLORS["accent_error"])
        if not products:
            items_column.controls = [ft.Text(
                "No hay productos activos. Creá uno en «Productos» primero.",
                size=12, color=COLORS["accent_error"])]
            add_btn.disabled = True
        else:
            items_column.controls = []
            add_btn.disabled = False
            _add_row()
        _safe_update()

    # ---------- consultar documento ----------
    def _set_natureza(es_contrib: bool, nombre: str, editable_nombre: bool):
        state["es_contribuyente"] = es_contrib
        natureza_badge.visible = True
        if es_contrib:
            natureza_text.value = "Contribuyente (RUC)"
            natureza_text.color = COLORS["text_primary"]
            natureza_badge.bgcolor = COLORS["accent_success"]
            tipo_id_dd.visible = False
        else:
            natureza_text.value = "No contribuyente (CI)"
            natureza_text.color = COLORS["text_primary"]
            natureza_badge.bgcolor = COLORS["text_secondary"]
            tipo_id_dd.visible = True
        nombre_field.value = nombre or ""
        nombre_field.read_only = es_contrib  # contribuyente: nome vem do gov (travado)
        _safe_update()

    def _consultar(ev=None):
        doc = (doc_field.value or "").strip()
        if not doc:
            _set_status("Ingresá el documento.", COLORS["accent_error"])
            return
        consultar_progress.visible = True
        _safe_update(consultar_progress)
        threading.Thread(target=_consultar_worker, args=(doc,), daemon=True).start()

    def _consultar_worker(doc):
        try:
            r = sifen_service.ruc_lookup(doc) or {}
            if r.get("es_contribuyente"):
                _set_natureza(True, r.get("nombre") or "", editable_nombre=False)
                _set_status("✓ Contribuyente ACTIVO.", COLORS["accent_success"])
            else:
                # no contribuyente: tenta nome do cadastro do cliente
                nombre = ""
                try:
                    hits = client_service.search(query=doc, limit=10) or []
                    exact = next((c for c in hits if str(c.get("ci_ruc", "")).strip() == doc), None)
                    nombre = (exact or (hits[0] if hits else {})).get("nombre_completo", "") if hits else ""
                except Exception:
                    pass
                _set_natureza(False, nombre, editable_nombre=True)
                estado = r.get("estado")
                msg = "No está en el registro (CI)." if not r.get("found") \
                    else f"RUC {estado} → se factura como no contribuyente."
                _set_status(msg, COLORS["text_secondary"])
        except APIError as ex:
            _set_status(friendly_error(ex), COLORS["accent_error"])
        except Exception as ex:  # noqa: BLE001
            _set_status(str(ex), COLORS["accent_error"])
        finally:
            consultar_progress.visible = False
            _safe_update(consultar_progress)

    # ---------- emitir ----------
    def _emitir(ev):
        doc = (doc_field.value or "").strip()
        if not doc:
            _set_status("Ingresá el documento.", COLORS["accent_error"])
            return
        try:
            items = []
            for r in picker_rows:
                v = r.get_values()
                if v is None:
                    continue
                items.append({"descripcion": v["descripcion"], "cantidad": v["cantidad"],
                              "precio_unit": v["precio"], "tasa_iva": v["iva_tasa"],
                              "afectacion": v["iva_afectacion"], "codigo": v["codigo"] or "1"})
        except ValueError as ve:
            _set_status(str(ve), COLORS["accent_error"])
            return
        if not items:
            _set_status("Agregá al menos un ítem.", COLORS["accent_error"])
            return

        tipo_id = int(tipo_id_dd.value or "1") if state["es_contribuyente"] is False else 1
        nombre = (nombre_field.value or "").strip() or None
        progress.visible = True
        _set_status("En cola…")
        _safe_update(progress)
        threading.Thread(target=_emitir_worker, args=(doc, items, tipo_id, nombre), daemon=True).start()

    def _emitir_worker(doc, items, tipo_id, nombre):
        try:
            job = sifen_service.emitir(client_request_id=uuid.uuid4().hex, doc=doc,
                                       items=items, tipo_id=tipo_id, nombre=nombre)
            emission_id = job["id"]
            st = job
            for _ in range(80):
                if st.get("status") in ("EMITIDA", "FALHOU", "CANCELADA"):
                    break
                time.sleep(1.5)
                st = sifen_service.get_emision(emission_id)
            status = st.get("status")
            if status == "EMITIDA":
                _set_status(f"✓ Factura Nº {st.get('numero_documento')} "
                            f"(CDC …{(st.get('cdc') or '')[-6:]})", COLORS["accent_success"])
                show_snackbar("Factura electrónica emitida.")
                if on_done:
                    try:
                        on_done(st)
                    except Exception:
                        pass
            elif status == "FALHOU":
                _set_status(f"✗ Falló: {st.get('error')}", COLORS["accent_error"])
            else:
                _set_status(f"… {status} (aún procesando). Podés cerrar; sigue en la cola.",
                            COLORS["text_secondary"])
        except APIError as ex:
            _set_status(friendly_error(ex), COLORS["accent_error"])
        except Exception as ex:  # noqa: BLE001
            _set_status(str(ex), COLORS["accent_error"])
        finally:
            progress.visible = False
            _safe_update(progress)

    modal = AppModal(
        page=page,
        title="Emitir factura electrónica",
        content=ft.Column([
            ft.Row([doc_field,
                    create_button("Consultar", icon=ft.Icons.SEARCH, primary=False, on_click=_consultar),
                    consultar_progress, natureza_badge],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([nombre_field, tipo_id_dd], spacing=10),
            ft.Divider(height=1, color=COLORS["border"]),
            ft.Row([ft.Text("Ítems", weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                    ft.Container(expand=True), add_btn]),
            items_column,
            ft.Row([ft.Container(expand=True), total_text]),
            ft.Row([progress, status_text], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
        actions=[
            ModalAction("Cerrar", on_click=lambda ev: modal.close()),
            ModalAction("Emitir", on_click=_emitir, primary=True),
        ],
        width_pct=0.5,
    )
    _modal_ref.append(modal)
    modal.open()
    threading.Thread(target=_load_products, daemon=True).start()
    if default_doc:
        _consultar()
    return modal
