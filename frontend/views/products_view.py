from __future__ import annotations

"""
WMApp Frontend - Productos / Servicios
Catálogo faturável (código, precio, IVA). Alimenta a fatura manual e a FE.
"""

import threading

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.data_table import DataTable
from components.theme import COLORS, SPACING, create_button, create_header, create_text_field
from i18n import t
from utils.errors import friendly_error
from services.api_client import APIError
from services.product_service import product_service


IVA_OPCIONES = [("10", "IVA 10%"), ("5", "IVA 5%"), ("0", "Exenta")]


class ProductsView(ft.Container):
    def __init__(self, show_snackbar):
        super().__init__(expand=True, padding=SPACING["md"])
        self.show_snackbar = show_snackbar
        self._products: list[dict] = []

        self.table = DataTable(
            columns=[
                {"key": "codigo", "label": "Código", "min_width": 90, "flex": 1, "priority": 1, "align": "left"},
                {"key": "descripcion", "label": "Descripción", "min_width": 260, "flex": 4, "priority": 1, "hideable": False, "align": "left"},
                {"key": "precio_fmt", "label": "Precio", "min_width": 120, "flex": 1, "priority": 2, "align": "right"},
                {"key": "iva_label", "label": "IVA", "min_width": 90, "flex": 1, "priority": 3, "align": "center"},
                {"key": "estado_label", "label": "Estado", "min_width": 100, "flex": 1, "priority": 3, "align": "center"},
            ],
            data=[],
            on_edit=self._on_edit,
            on_delete=self._on_delete,
            edit_tooltip="Editar",
            delete_tooltip="Desactivar",
            empty_message="Ningún producto todavía.",
        )

        self.content = ft.Column(
            expand=True,
            controls=[
                ft.Row([
                    create_header("Productos / Servicios"),
                    ft.Container(expand=True),
                    create_button("Nuevo producto", icon=ft.Icons.ADD, on_click=lambda e: self._open_modal()),
                    create_button("Actualizar", icon=ft.Icons.REFRESH, primary=False,
                                  on_click=lambda e: self._reload()),
                ]),
                ft.Container(height=SPACING["sm"]),
                self.table,
            ],
        )
        self.on_visible = lambda e: self._reload()

    # ---------------- data ----------------
    def _reload(self):
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            self._products = product_service.listar() or []
        except Exception as ex:  # noqa: BLE001
            self._products = []
            self.show_snackbar(str(ex), error=True)
        rows = []
        for p in self._products:
            precio = p.get("precio_unitario") or 0
            try:
                precio_fmt = f"Gs {int(float(precio)):,}".replace(",", ".")
            except Exception:
                precio_fmt = str(precio)
            tasa = int(p.get("iva_tasa", 10))
            iva_label = "Exenta" if (tasa == 0 or p.get("iva_afectacion") == 3) else f"{tasa}%"
            rows.append({
                **p,
                "precio_fmt": precio_fmt,
                "iva_label": iva_label,
                "estado_label": "Activo" if p.get("activo") else "Inactivo",
            })
        try:
            self.table.set_data(rows)
        except Exception:
            pass

    # ---------------- modal ----------------
    def _open_modal(self, product: dict | None = None):
        editing = product is not None
        codigo = create_text_field("Código", value=(product or {}).get("codigo", ""),
                                   hint_text="auto si vacío", width=140)
        desc = create_text_field("Descripción", value=(product or {}).get("descripcion", ""), width=380)
        precio = create_text_field("Precio (Gs)", width=160,
                                   value=str(int(float((product or {}).get("precio_unitario", 0) or 0))) if editing else "")
        # IVA dropdown
        cur_tasa = str((product or {}).get("iva_tasa", 10))
        if editing and (product or {}).get("iva_afectacion") == 3:
            cur_tasa = "0"
        iva_dd = ft.Dropdown(
            label="IVA", width=160, value=cur_tasa,
            options=[ft.dropdown.Option(key=k, text=txt) for k, txt in IVA_OPCIONES],
        )
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)

        def _save(ev):
            d = (desc.value or "").strip()
            raw = (precio.value or "").strip().replace(".", "").replace(",", "")
            if not d:
                return _err("Ingresá la descripción.")
            if not raw.isdigit():
                return _err("Precio inválido.")
            tasa = int(iva_dd.value or "10")
            payload = {
                "descripcion": d,
                "precio_unitario": int(raw),
                "iva_tasa": 0 if tasa == 0 else tasa,
                "iva_afectacion": 3 if tasa == 0 else 1,
            }
            cod = (codigo.value or "").strip()
            if cod:
                payload["codigo"] = cod
            threading.Thread(target=_save_worker, args=(payload,), daemon=True).start()

        def _err(msg):
            error_text.value = msg
            error_text.visible = True
            try:
                error_text.update()
            except Exception:
                pass

        def _save_worker(payload):
            try:
                if editing:
                    product_service.atualizar(product["id"], payload)
                else:
                    product_service.criar(payload)
                modal.close()
                self.show_snackbar("Producto guardado.")
                self._load()
            except APIError as ex:
                _err(friendly_error(ex))
            except Exception as ex:  # noqa: BLE001
                _err(str(ex))

        modal = AppModal(
            page=self.page,
            title="Editar producto" if editing else "Nuevo producto",
            content=ft.Column([
                ft.Row([codigo, iva_dd], spacing=10),
                desc,
                precio,
                error_text,
            ], spacing=12, tight=True),
            actions=[
                ModalAction("Cancelar", on_click=lambda ev: modal.close()),
                ModalAction("Guardar", on_click=_save, primary=True),
            ],
            width_pct=0.4,
        )
        modal.open()

    def _on_edit(self, row: dict):
        # a row traz os campos originais + derivados; achamos o produto cru
        prod = next((p for p in self._products if p.get("id") == row.get("id")), row)
        self._open_modal(prod)

    def _on_delete(self, row: dict):
        def _worker():
            try:
                product_service.desativar(row["id"])
                self.show_snackbar("Producto desactivado.")
                self._load()
            except APIError as ex:
                self.show_snackbar(friendly_error(ex), error=True)
            except Exception as ex:  # noqa: BLE001
                self.show_snackbar(str(ex), error=True)
        threading.Thread(target=_worker, daemon=True).start()
