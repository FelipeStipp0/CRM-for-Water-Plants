from __future__ import annotations

"""
WMApp Frontend - Painel de configuração da Facturación Electrónica (SIFEN).

Vive dentro de *Configuraciones*: credenciais do portal (só master) e o painel
de dispositivos habilitados (ícone de PC + estado En línea / Desconectado). A
emissão em si mora em Facturación/Finanzas (components/sifen_emit.py).
"""

import threading

import flet as ft

from components.theme import COLORS, create_button, create_text_field
from i18n import t
from utils.errors import friendly_error
from services.api_client import APIError
from services.sifen_service import sifen_service


def _help(msg: str) -> ft.Icon:
    return ft.Icon(ft.Icons.HELP_OUTLINE, size=16, color=COLORS["text_secondary"], tooltip=msg)


def _labeled(label: str, help_msg: str, field: ft.Control) -> ft.Column:
    return ft.Column(
        spacing=4,
        controls=[
            ft.Row([ft.Text(label, size=13, color=COLORS["text_secondary"]), _help(help_msg)],
                   spacing=6),
            field,
        ],
    )


class SifenConfigPanel(ft.Column):
    """Painel embutível em Configuraciones. Chame `.load()` quando ficar visível."""

    def __init__(self, show_snackbar, current_user: dict | None = None):
        super().__init__(spacing=18, tight=True)
        self.show_snackbar = show_snackbar
        self.current_user = current_user or {}

        # credenciais
        self._ruc = create_text_field(label="RUC", hint_text="80012345")
        self._clave = create_text_field(label="Clave", password=True)
        self._pin = create_text_field(label="PIN de firma", password=True)
        self._cred_status = ft.Text("", size=12, color=COLORS["text_secondary"])

        # dispositivos
        self._devices_col = ft.Column(spacing=8)

        self.controls = [self._build_credenciais(), self._build_dispositivos()]

    # ---------------- helpers ----------------
    def _is_master(self) -> bool:
        return self.current_user.get("role") == "master"

    def _safe_update(self, ctrl: ft.Control | None = None):
        try:
            (ctrl or self).update()
        except Exception:
            pass

    def load(self):
        """Carrega estado das credenciais + lista de dispositivos (em background)."""
        threading.Thread(target=self._load_status, daemon=True).start()

    # ---------------- credenciais ----------------
    def _build_credenciais(self) -> ft.Control:
        if not self._is_master():
            return ft.Text("Solo el administrador puede configurar las credenciales del portal.",
                           size=13, color=COLORS["text_secondary"])
        return ft.Column(
            spacing=12,
            controls=[
                _labeled("RUC", "El RUC del emisor (la junta), sin dígito verificador.", self._ruc),
                _labeled("Clave", "La contraseña de acceso al portal de facturación.", self._clave),
                _labeled("PIN de firma", "El código de firma (PIN del certificado).", self._pin),
                self._cred_status,
                ft.Row([create_button("Guardar credenciales", on_click=self._guardar_creds,
                                      icon=ft.Icons.SAVE)]),
            ],
        )

    def _guardar_creds(self, e):
        ruc = (self._ruc.value or "").strip()
        clave = (self._clave.value or "").strip()
        pin = (self._pin.value or "").strip()
        if not (ruc and clave and pin):
            self.show_snackbar("Completá RUC, clave y PIN.", error=True)
            return
        threading.Thread(target=self._guardar_creds_worker, args=(ruc, clave, pin), daemon=True).start()

    def _guardar_creds_worker(self, ruc, clave, pin):
        try:
            sifen_service.salvar_credenciais(ruc, clave, pin)
            self._clave.value = ""
            self._pin.value = ""
            self._cred_status.value = "✓ Credenciales configuradas."
            self._cred_status.color = COLORS["accent_success"]
            self.show_snackbar("Credenciales guardadas.")
        except APIError as ex:
            self.show_snackbar(friendly_error(ex), error=True)
        except Exception as ex:  # noqa: BLE001
            self.show_snackbar(str(ex), error=True)
        finally:
            self._safe_update()

    # ---------------- dispositivos ----------------
    def _build_dispositivos(self) -> ft.Control:
        return ft.Column(
            spacing=10,
            controls=[
                ft.Divider(height=1, color=COLORS["border"]),
                ft.Row([
                    ft.Icon(ft.Icons.DEVICES, size=18, color=COLORS["accent_primary"]),
                    ft.Text("Dispositivos habilitados", size=14, weight=ft.FontWeight.BOLD,
                            color=COLORS["text_primary"]),
                ], spacing=6),
                ft.Text("PCs que pueden generar documentos electrónicos. No afecta el uso "
                        "diario del equipo.", size=12, color=COLORS["text_secondary"]),
                self._devices_col,
                ft.Row([create_button("Actualizar", on_click=lambda e: self._reload_devices(),
                                      icon=ft.Icons.REFRESH, primary=False)]),
            ],
        )

    def _reload_devices(self):
        threading.Thread(target=self._load_devices, daemon=True).start()

    def _load_status(self):
        if self._is_master():
            try:
                sifen_service.get_credenciais()
                self._cred_status.value = "✓ Credenciales configuradas."
                self._cred_status.color = COLORS["accent_success"]
            except APIError as ex:
                if getattr(ex, "status", None) == 404 or getattr(ex, "status_code", None) == 404:
                    self._cred_status.value = "⚠ Credenciales no configuradas."
                    self._cred_status.color = COLORS["text_secondary"]
            except Exception:
                pass
        self._safe_update()
        self._load_devices()

    def _load_devices(self):
        try:
            devs = sifen_service.listar_coordinators() or []
        except Exception:
            devs = []
        rows = []
        for d in devs:
            online = bool(d.get("online"))
            enabled = bool(d.get("enabled"))
            # ícone de PC + estado En línea / Desconectado
            pc = ft.Icon(ft.Icons.COMPUTER, size=20,
                         color=(COLORS["accent_success"] if online else COLORS["text_secondary"]))
            label = ft.Text(d.get("label") or (d.get("machine_id", "")[:12]),
                            size=13, color=COLORS["text_primary"])
            estado = ft.Row(
                [
                    ft.Icon(ft.Icons.CIRCLE, size=9,
                            color=(COLORS["accent_success"] if online else COLORS["text_secondary"])),
                    ft.Text("En línea" if online else "Desconectado", size=12,
                            color=(COLORS["accent_success"] if online else COLORS["text_secondary"])),
                ],
                spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            controls = [pc, label, ft.Container(expand=True), estado]
            if self._is_master():
                controls.append(ft.Switch(
                    value=enabled,
                    tooltip="Habilitar este equipo para emitir",
                    on_change=lambda e, mid=d.get("machine_id"): self._toggle_device(mid, e.control.value),
                ))
            rows.append(ft.Row(controls, spacing=12,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER))
        if not rows:
            rows = [ft.Text("Ningún dispositivo aún. Abrí la app en el PC que va a emitir.",
                            size=12, color=COLORS["text_secondary"])]
        self._devices_col.controls = rows
        self._safe_update()

    def _toggle_device(self, machine_id: str, enabled: bool):
        def _worker():
            try:
                sifen_service.permitir(machine_id, enabled)
                self.show_snackbar("Equipo habilitado." if enabled else "Equipo deshabilitado.")
            except APIError as ex:
                self.show_snackbar(friendly_error(ex), error=True)
            except Exception as ex:  # noqa: BLE001
                self.show_snackbar(str(ex), error=True)
            finally:
                self._load_devices()
        threading.Thread(target=_worker, daemon=True).start()
