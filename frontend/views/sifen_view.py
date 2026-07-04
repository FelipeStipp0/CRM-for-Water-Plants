from __future__ import annotations

"""
WMApp Frontend - Facturación Electrónica (SIFEN).

Centro de controle: credenciais do portal (admin), emissão (teste/manual) e
painel de dispositivos permitidos. A emissão de verdade roda no coordenador em
background (services/sifen_coordinator); aqui o operador dispara e acompanha.
"""

import threading
import time
import uuid

import flet as ft

from components.theme import COLORS, create_button, create_header, create_text_field
from i18n import t
from utils.errors import friendly_error
from services.api_client import APIError
from services.sifen_service import sifen_service


def _help(msg: str) -> ft.Icon:
    """Ícone '?' com dica (tooltip universal)."""
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


class SifenView(ft.Container):
    def __init__(self, show_snackbar, current_user: dict | None = None):
        super().__init__(expand=True, padding=24)
        self.show_snackbar = show_snackbar
        self.current_user = current_user or {}

        # ---- credenciais ----
        self._ruc = create_text_field(label="RUC", hint_text="80012345")
        self._clave = create_text_field(label="Clave", password=True)
        self._pin = create_text_field(label="PIN de firma", password=True)
        self._cred_status = ft.Text("", size=12, color=COLORS["text_secondary"])

        # ---- emitir ----
        self._doc = create_text_field(label="Documento (CI/RUC)", hint_text="7184730")
        self._desc = create_text_field(label="Descripción",
                                       value="SUMINISTRO DE AGUA POTABLE")
        self._monto = create_text_field(label="Monto (Gs)", hint_text="150000")
        self._emit_result = ft.Text("", size=13)
        self._emit_progress = ft.ProgressRing(width=18, height=18, visible=False)

        # ---- dispositivos ----
        self._devices_col = ft.Column(spacing=8)

        self.content = ft.Column(
            expand=True, scroll=ft.ScrollMode.AUTO, spacing=24,
            controls=[
                create_header("Facturación Electrónica"),
                self._card_credenciais(),
                self._card_emitir(),
                self._card_dispositivos(),
            ],
        )

    # ---------------- helpers ----------------
    def _is_master(self) -> bool:
        return self.current_user.get("role") == "master"

    def _safe_update(self, ctrl: ft.Control | None = None):
        try:
            (ctrl or self).update()
        except Exception:
            pass

    def did_mount(self):
        # ao abrir: estado das creds + lista de dispositivos
        threading.Thread(target=self._load_status, daemon=True).start()

    def _card(self, title: str, *controls: ft.Control) -> ft.Container:
        return ft.Container(
            padding=20, border_radius=12, bgcolor=COLORS["bg_secondary"],
            content=ft.Column(spacing=14, controls=[
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                *controls,
            ]),
        )

    # ---------------- credenciais ----------------
    def _card_credenciais(self) -> ft.Container:
        if not self._is_master():
            return self._card("Credenciales del portal",
                              ft.Text("Solo el administrador puede configurar las credenciales.",
                                      size=13, color=COLORS["text_secondary"]))
        return self._card(
            "Credenciales del portal",
            _labeled("RUC", "El RUC del emisor (la junta), sin dígito verificador.", self._ruc),
            _labeled("Clave", "La contraseña de acceso al portal de facturación.", self._clave),
            _labeled("PIN de firma", "El código de firma (PIN del certificado). Teclado del portal.", self._pin),
            self._cred_status,
            ft.Row([create_button("Guardar", on_click=self._guardar_creds, icon=ft.Icons.SAVE)]),
        )

    def _guardar_creds(self, e):
        ruc, clave, pin = self._ruc.value.strip(), self._clave.value.strip(), self._pin.value.strip()
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

    # ---------------- emitir ----------------
    def _card_emitir(self) -> ft.Container:
        return self._card(
            "Emitir factura",
            _labeled("Documento (CI/RUC)",
                     "El documento del cliente. El sistema resuelve solo si es RUC o CI.", self._doc),
            _labeled("Descripción", "Descripción del ítem a facturar.", self._desc),
            _labeled("Monto (Gs)", "Monto total con IVA incluido (guaraníes).", self._monto),
            ft.Row([
                create_button("Emitir", on_click=self._emitir, icon=ft.Icons.RECEIPT_LONG),
                self._emit_progress,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self._emit_result,
        )

    def _emitir(self, e):
        doc = self._doc.value.strip()
        desc = self._desc.value.strip()
        monto_raw = (self._monto.value or "").strip().replace(".", "").replace(",", "")
        if not doc or not desc or not monto_raw.isdigit():
            self.show_snackbar("Completá documento, descripción y monto válido.", error=True)
            return
        self._emit_progress.visible = True
        self._emit_result.value = "En cola…"
        self._emit_result.color = COLORS["text_secondary"]
        self._safe_update()
        threading.Thread(target=self._emitir_worker,
                         args=(doc, desc, int(monto_raw)), daemon=True).start()

    def _emitir_worker(self, doc, desc, monto):
        try:
            job = sifen_service.emitir(
                client_request_id=uuid.uuid4().hex,
                doc=doc,
                items=[{"descripcion": desc, "cantidad": 1, "precio_unit": monto,
                        "tasa_iva": 10, "afectacion": 1}],
            )
            emission_id = job["id"]
            st = job
            for _ in range(80):  # ~2 min
                if st.get("status") in ("EMITIDA", "FALHOU", "CANCELADA"):
                    break
                time.sleep(1.5)
                st = sifen_service.get_emision(emission_id)

            status = st.get("status")
            if status == "EMITIDA":
                self._emit_result.value = (f"✓ Factura Nº {st.get('numero_documento')} "
                                           f"(CDC …{(st.get('cdc') or '')[-6:]})")
                self._emit_result.color = COLORS["accent_success"]
            elif status == "FALHOU":
                self._emit_result.value = f"✗ Falló: {st.get('error')}"
                self._emit_result.color = COLORS["accent_error"]
            else:
                self._emit_result.value = f"… {status} (aún procesando)"
                self._emit_result.color = COLORS["text_secondary"]
        except APIError as ex:
            self._emit_result.value = friendly_error(ex)
            self._emit_result.color = COLORS["accent_error"]
        except Exception as ex:  # noqa: BLE001
            self._emit_result.value = str(ex)
            self._emit_result.color = COLORS["accent_error"]
        finally:
            self._emit_progress.visible = False
            self._safe_update()

    # ---------------- dispositivos ----------------
    def _card_dispositivos(self) -> ft.Container:
        return self._card(
            "Dispositivos habilitados",
            ft.Text("PCs que pueden generar documentos. No afecta el uso diario del PC.",
                    size=12, color=COLORS["text_secondary"]),
            self._devices_col,
            ft.Row([create_button("Actualizar", on_click=lambda e: self._reload_devices(),
                                  icon=ft.Icons.REFRESH, primary=False)]),
        )

    def _reload_devices(self):
        threading.Thread(target=self._load_devices, daemon=True).start()

    def _load_status(self):
        # estado das credenciais
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
            online = d.get("online")
            enabled = d.get("enabled")
            dot = ft.Icon(ft.Icons.CIRCLE, size=10,
                          color=("#3ecf8e" if online else COLORS["text_secondary"]))
            label = ft.Text(d.get("label") or d.get("machine_id", "")[:12],
                            size=13, color=COLORS["text_primary"])
            estado = ft.Text("habilitado" if enabled else "no habilitado", size=12,
                             color=(COLORS["accent_success"] if enabled else COLORS["text_secondary"]))
            controls = [dot, label, ft.Container(expand=True), estado]
            if self._is_master():
                controls.append(ft.Switch(
                    value=bool(enabled),
                    on_change=lambda e, mid=d.get("machine_id"): self._toggle_device(mid, e.control.value),
                ))
            rows.append(ft.Row(controls, spacing=10,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER))
        if not rows:
            rows = [ft.Text("Ningún dispositivo aún.", size=12, color=COLORS["text_secondary"])]
        self._devices_col.controls = rows
        self._safe_update()

    def _toggle_device(self, machine_id: str, enabled: bool):
        def _worker():
            try:
                sifen_service.permitir(machine_id, enabled)
                self.show_snackbar("Habilitado." if enabled else "Deshabilitado.")
            except APIError as ex:
                self.show_snackbar(friendly_error(ex), error=True)
            except Exception as ex:  # noqa: BLE001
                self.show_snackbar(str(ex), error=True)
            finally:
                self._load_devices()
        threading.Thread(target=_worker, daemon=True).start()
