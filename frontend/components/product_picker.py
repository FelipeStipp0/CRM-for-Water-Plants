from __future__ import annotations

"""
WMApp Frontend - Product Picker
Linha reutilizável de item por **produto do catálogo** (dropdown) + cantidad +
precio (editável). Usada na fatura manual e na facturación electrónica.

`get_values()` devolve um dict normalizado
    {codigo, descripcion, cantidad, precio, iva_tasa, iva_afectacion}
ou None se a linha estiver vazia. Cada chamador mapeia p/ o payload que precisa.
"""

from typing import Callable, Optional

import flet as ft

from components.theme import COLORS, create_text_field


class ProductPickerRow(ft.Row):
    def __init__(self, products: list[dict], *, on_change: Optional[Callable] = None,
                 on_remove: Optional[Callable] = None):
        self._products = {str(p["id"]): p for p in products}
        self._codigo = ""
        self._descripcion = ""
        self.iva_tasa = 10
        self.iva_afectacion = 1

        self.dd = ft.Dropdown(
            label="Producto", width=320,
            options=[ft.dropdown.Option(key=str(p["id"]),
                                        text=f'{p.get("codigo","")} · {p.get("descripcion","")}')
                     for p in products],
        )
        self.dd.on_change = self._pick  # Flet 0.84: on_change é atributo, não kwarg
        self.qty = create_text_field("Cant.", value="1", width=70, on_change=on_change)
        self.precio = create_text_field("Precio (Gs)", width=140, on_change=on_change)
        self._on_change = on_change

        controls = [self.dd, self.qty, self.precio]
        if on_remove is not None:
            controls.append(ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_size=18, icon_color=COLORS["accent_error"],
                tooltip="Quitar", on_click=lambda e: on_remove(self)))
        super().__init__(controls, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _pick(self, e):
        p = self._products.get(str(self.dd.value))
        if not p:
            return
        self._codigo = p.get("codigo", "")
        self._descripcion = p.get("descripcion", "")
        self.iva_tasa = int(p.get("iva_tasa", 10))
        self.iva_afectacion = int(p.get("iva_afectacion", 1))
        try:
            self.precio.value = str(int(float(p.get("precio_unitario") or 0)))
            self.precio.update()
        except Exception:
            pass
        if self._on_change:
            self._on_change(e)

    def get_values(self) -> Optional[dict]:
        raw = (self.precio.value or "").strip().replace(".", "").replace(",", "")
        if not self.dd.value and not raw:
            return None  # linha vazia → ignorar
        if not self.dd.value:
            raise ValueError("Elegí un producto en cada línea.")
        if not raw.isdigit() or int(raw) <= 0:
            raise ValueError(f"Precio inválido en «{self._descripcion}».")
        qty_raw = (self.qty.value or "1").strip()
        cantidad = int(qty_raw) if qty_raw.isdigit() and int(qty_raw) > 0 else 1
        return {
            "codigo": self._codigo,
            "descripcion": self._descripcion,
            "cantidad": cantidad,
            "precio": int(raw),
            "iva_tasa": self.iva_tasa,
            "iva_afectacion": self.iva_afectacion,
        }
