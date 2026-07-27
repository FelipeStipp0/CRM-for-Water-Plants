from __future__ import annotations

"""
WMApp Frontend - Bloco «Otras conexiones» + «Agregar residencia».

Um titular costuma ter várias ligações: residência, imóveis de aluguel, comércio.
Cada uma é um cliente próprio (medidor, leitura, fatura, corte) — o que faltava
era ver as outras casas da mesma pessoa e acrescentar uma sem redigitar nome,
documento e telefone.

Usado na ficha do cliente (`clients_view`).
"""

import threading

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, FONTS, SPACING, create_button, create_text_field
from services.api_client import APIError
from services.titular_service import titular_service
from utils.errors import friendly_error

CATEGORIAS = ("RESIDENCIAL", "COMERCIAL", "SOCIAL")


def bloco_conexiones(page: ft.Page, client: dict, show_snackbar,
                     on_change=None) -> ft.Control:
    """
    Bloco para a ficha do cliente. Devolve um Container que se preenche sozinho.

    `on_change` é chamado depois de criar uma residência, para a lista de
    clientes atrás recarregar.
    """
    titular_id = client.get("titular_id")
    lista = ft.Column(spacing=4, tight=True)
    titulo = ft.Text("", size=FONTS["size_sm"], weight=ft.FontWeight.W_600,
                     color=COLORS["text_primary"])

    add_btn = create_button("Agregar residencia", icon=ft.Icons.ADD_HOME_OUTLINED,
                            primary=False,
                            on_click=lambda e: _modal_residencia(
                                page, titular_id, show_snackbar, _recarregar, on_change))
    add_btn.visible = bool(titular_id)

    caixa = ft.Container(
        content=ft.Column([titulo, lista, add_btn], spacing=SPACING["sm"], tight=True),
        padding=SPACING["sm"],
    )

    def _u(ctrl=None):
        try:
            (ctrl or caixa).update()
        except Exception:
            pass

    def _pintar(conexiones: list[dict]):
        outras = [c for c in conexiones if str(c.get("id")) != str(client.get("id"))]
        titulo.value = (f"Otras conexiones de este titular ({len(outras)})"
                        if outras else "Única conexión de este titular")
        lista.controls = [
            ft.Row([
                ft.Icon(ft.Icons.HOME_OUTLINED, size=15, color=COLORS["text_muted"]),
                ft.Text(c.get("nombre_completo", "")[:34], size=FONTS["size_xs"],
                        color=COLORS["text_secondary"], expand=True),
                ft.Text(f"M{c.get('manzana') or '-'}/L{c.get('lote') or '-'}",
                        size=FONTS["size_xs"], color=COLORS["text_muted"]),
            ], spacing=6)
            for c in outras
        ]
        _u()

    def _recarregar():
        if not titular_id:
            titulo.value = "Sin titular vinculado"
            _u()
            return
        try:
            _pintar(titular_service.conexiones(titular_id) or [])
        except Exception as ex:  # noqa: BLE001 — o bloco é acessório, não pode derrubar a ficha
            titulo.value = f"No se pudieron cargar las conexiones ({ex})"
            _u()

    threading.Thread(target=_recarregar, daemon=True).start()
    return caixa


def _modal_residencia(page: ft.Page, titular_id: str, show_snackbar,
                      on_saved=None, on_change=None):
    """Só o que muda de casa para casa — o resto vem do titular."""
    etiqueta = create_text_field(label="Etiqueta (ej: Casa 02)", width=200)
    direccion = create_text_field(label="Dirección", width=420)
    manzana = create_text_field(label="Manzana", width=110)
    lote = create_text_field(label="Lote", width=110)
    medidor = create_text_field(label="Nº de medidor", value="SIN_MEDIDOR", width=190)
    categoria = ft.Dropdown(
        label="Categoría", width=190, value="RESIDENCIAL",
        options=[ft.dropdown.Option(key=c, text=c.capitalize()) for c in CATEGORIAS],
    )
    aluguel = ft.Checkbox(label="Es alquiler", value=False)
    estado = ft.Text("", size=FONTS["size_xs"], color=COLORS["accent_error"])

    def salvar(ev):
        if len((direccion.value or "").strip()) < 5:
            estado.value = "Ingresá la dirección."
            estado.update()
            return
        payload = {
            "direccion": direccion.value.strip(),
            "manzana": (manzana.value or "").strip(),
            "lote": (lote.value or "").strip(),
            "numero_medidor": (medidor.value or "SIN_MEDIDOR").strip() or "SIN_MEDIDOR",
            "categoria": categoria.value,
            "is_aluguel": bool(aluguel.value),
        }
        if (etiqueta.value or "").strip():
            payload["etiqueta"] = etiqueta.value.strip()
        try:
            titular_service.agregar_residencia(titular_id, payload)
        except APIError as ex:
            estado.value = friendly_error(ex)
            estado.update()
            return
        except Exception as ex:  # noqa: BLE001
            estado.value = str(ex)
            estado.update()
            return
        modal.close()
        show_snackbar("✓ Residencia agregada.")
        for cb in (on_saved, on_change):
            if cb:
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    pass

    modal = AppModal(
        page=page,
        title="Agregar residencia",
        content=ft.Column([
            ft.Text("Nombre, documento y contacto se copian del titular.",
                    size=FONTS["size_xs"], color=COLORS["text_secondary"]),
            ft.Row([etiqueta, medidor], spacing=10),
            direccion,
            ft.Row([manzana, lote, categoria], spacing=10),
            aluguel,
            estado,
        ], spacing=12, tight=True),
        actions=[
            ModalAction("Cancelar", on_click=lambda e: modal.close()),
            ModalAction("Agregar", on_click=salvar, primary=True),
        ],
        width_pct=0.45,
    )
    modal.open()
    return modal
