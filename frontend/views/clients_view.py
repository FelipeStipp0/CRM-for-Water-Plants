"""
WMApp Frontend - Clients View
Tela de gestao de clientes com sponsor/subsidio.
"""
import flet as ft

from components.custom_tabs import CustomTabs, TabItem
from components.data_table import DataTable
from components.gps_picker_dialog import open_gps_picker_dialog
from components.image_viewer import ImageViewer
from components.loading_overlay import LoadingOverlay
from components.pagination import Pagination
from components.search_bar import SearchBar
from components.app_modal import AppModal, ModalAction
from components.theme import COLORS, FONTS, SPACING, create_badge, create_button, create_header, create_text_field, get_status_color
from services.api_client import APIError
from utils.errors import friendly_error
from services.client_service import client_service
from utils.excel_import import normalize_identifier, pick_first_value, read_excel_rows
from utils.formatters import format_currency
from i18n import t


class ClientsView(ft.Container):
    """Tela de gestao de clientes."""

    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self.clients = []
        self.selected_client = None
        self._loading_clients = False
        self._page_size = 100
        self._current_query: str | None = None

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        # Regra operacional: atualizar sempre que a tela for aberta/ficar visivel.
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._run_load_clients()

    def _on_page_change(self, skip: int):
        self._run_load_clients(query=self._current_query, skip=skip)

    def _run_load_clients(self, query: str | None = None, skip: int = 0):
        self._current_query = query
        # Skeleton pinta o esqueleto da tabela imediatamente, antes da
        # request bater na API. So aparece quando ainda nao ha dado em tela.
        if not self.clients:
            try:
                self.table.show_skeleton(rows=10)
            except Exception as err:
                print(f"[ClientsView] skeleton_error err={err}")
        if self.page:
            try:
                self.page.run_thread(lambda: self._load_clients(query, skip))
                return
            except Exception as err:
                print(f"[ClientsView] run_thread_error err={err}")
        self._load_clients(query, skip)

    def _safe_update(self, control: ft.Control | None):
        if control is None:
            return
        try:
            control.update()
        except Exception as err:
            print(f"[ClientsView] safe_update_error control={type(control).__name__} err={err}")
            if self.page:
                try:
                    self.page.update()
                except Exception as page_err:
                    print(f"[ClientsView] page_update_fallback_error err={page_err}")

    def _build(self):
        header = ft.Row(
            [
                create_header(t("clients.title")),
                ft.Container(expand=True),
                create_button(t("clients.import_excel"), icon=ft.Icons.UPLOAD_FILE, on_click=self._open_import_excel, primary=False),
                create_button(t("clients.new"), icon=ft.Icons.ADD, on_click=self._open_form),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self.load_status = ft.Text("", size=12, color=COLORS["text_secondary"], visible=False)

        self.search_bar = SearchBar(
            placeholder=t("clients.search_placeholder"),
            on_search=self._search_clients,
        )

        self.table = DataTable(
            columns=[
                {"key": "nombre_completo", "label": t("clients.col.name"), "min_width": 220, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "ci_ruc", "label": t("clients.col.ci_ruc"), "min_width": 110, "flex": 1, "priority": 2, "align": "center"},
                {"key": "numero_medidor", "label": t("clients.col.meter"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
                {"key": "manzana", "label": t("clients.col.mz"), "min_width": 48, "flex": 1, "priority": 3, "align": "center"},
                {"key": "lote", "label": t("clients.col.lt"), "min_width": 48, "flex": 1, "priority": 3, "align": "center"},
                {"key": "categoria", "label": t("clients.col.category"), "min_width": 110, "flex": 1, "priority": 3, "align": "center"},
                {"key": "status", "label": t("clients.col.status"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
            ],
            data=[],
            on_row_click=self._view_client,
            on_edit=self._edit_client,
            on_delete=self._delete_client,
        )

        self.loading_overlay = LoadingOverlay(t("clients.loading"))
        self.detail_panel = ft.Container(visible=False)
        self.pagination = Pagination(page_size=self._page_size, on_change=self._on_page_change)

        main_content = ft.Column(
            [
                header,
                self.load_status,
                self.search_bar,
                ft.Stack(
                    [
                        self.table,
                        self.loading_overlay,
                    ],
                    expand=True,
                ),
                self.pagination,
            ],
            spacing=SPACING["sm"],
            expand=True,
        )

        self.content = ft.Row(
            [
                ft.Container(content=main_content, expand=True),
                self.detail_panel,
            ],
            expand=True,
        )
        self.padding = ft.padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["sm"])
        self.expand = True

    def _load_clients(self, query: str | None = None, skip: int = 0):
        if self._loading_clients:
            return
        self._loading_clients = True
        print(f"[ClientsView] load_start query={query!r} skip={skip}")
        # Skeleton cobre o vazio; overlay sobreposto na carga foi removido.
        try:
            if query:
                self.clients = client_service.search(query=query)
                total = len(self.clients)
            else:
                self.clients, total = client_service.list_paged(skip=skip, limit=self._page_size)
            print(f"[ClientsView] load_ok count={len(self.clients)}")
            table_rows = [self._decorate_client_row(c) for c in self.clients]
            self.table.set_data(table_rows)
            current_page = skip // self._page_size
            self.pagination.update_state(current_page=current_page, total_items=total)
            self.load_status.visible = False
            self._safe_update(self.load_status)
        except APIError as err:
            print(f"[ClientsView] load_api_error detail={err.detail}")
            self.table.set_error(t("clients.load_failed"), on_retry=lambda: self._run_load_clients(query, skip))
            self.load_status.value = t("clients.load_failed")
            self.load_status.color = COLORS["accent_error"]
            self.load_status.visible = True
            self._safe_update(self.load_status)
            self.show_snackbar(friendly_error(err), error=True)
        except Exception as err:
            print(f"[ClientsView] load_unexpected_error err={err}")
            self.table.set_error(t("clients.load_failed_unexpected"), on_retry=lambda: self._run_load_clients(query, skip))
            self.load_status.value = t("clients.load_failed_unexpected")
            self.load_status.color = COLORS["accent_error"]
            self.load_status.visible = True
            self._safe_update(self.load_status)
            self.show_snackbar(t("clients.load_failed_unexpected"), error=True)
        finally:
            self._loading_clients = False
            if self.page:
                try:
                    self.page.update()
                except Exception as err:
                    print(f"[ClientsView] final_page_update_error err={err}")
            print("[ClientsView] load_end")

    def _decorate_client_row(self, client: dict) -> dict:
        row = dict(client)

        if client.get("foto_medidor_url"):
            row["foto_medidor"] = ft.IconButton(
                icon=ft.Icons.PHOTO_CAMERA,
                icon_size=16,
                tooltip=t("clients.meter_photo_tooltip"),
                icon_color=COLORS["accent_secondary"],
                on_click=lambda e, c=row: self._show_client_photo_dialog(c),
            )
        else:
            row["foto_medidor"] = ft.Text("-", color=COLORS["text_muted"], size=12)

        if client.get("instalacao_latitude") is not None and client.get("instalacao_longitude") is not None:
            row["gps"] = ft.Icon(
                ft.Icons.LOCATION_ON,
                size=16,
                color=COLORS["accent_success"],
            )
        else:
            row["gps"] = ft.Text("-", color=COLORS["text_muted"], size=12)
        return row

    def _search_clients(self, query: str):
        q = (query or "").strip()
        self.pagination.reset()
        self._run_load_clients(q if len(q) >= 2 else None, skip=0)

    def _fetch_all_clients(self, limit: int = 200, max_total: int = 5000) -> list[dict]:
        all_clients: list[dict] = []
        skip = 0
        while len(all_clients) < max_total:
            batch = client_service.list(skip=skip, limit=limit)
            if not batch:
                break
            all_clients.extend(batch)
            if len(batch) < limit:
                break
            skip += limit
        return all_clients

    @staticmethod
    def _parse_bool(value) -> bool | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        if text in {"1", "true", "sim", "yes", "y", "x"}:
            return True
        if text in {"0", "false", "nao", "não", "no", "n"}:
            return False
        return None

    async def _open_import_excel(self, e=None):
        if not self.page:
            self.show_snackbar(t("clients.import.not_ready"), error=True)
            return

        # Flet 0.84: FilePicker é serviço; pick_files é async e retorna os arquivos.
        picker = ft.FilePicker()
        if picker not in self.page.services:
            self.page.services.append(picker)
        files = await picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx", "xlsm", "xls"],
            dialog_title=t("clients.import.pick_title"),
        )
        if picker in self.page.services:
            self.page.services.remove(picker)

        if not files:
            return
        selected = files[0]
        if not selected.path:
            self.show_snackbar(t("clients.import.no_access"), error=True)
            return
        if self.page:
            try:
                self.page.run_thread(lambda: self._import_clients_excel(selected.path))
                return
            except Exception:
                pass
        self._import_clients_excel(selected.path)

    def _import_clients_excel(self, file_path: str):
        self.loading_overlay.show(t("clients.import.importing"))
        created = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        try:
            rows = read_excel_rows(file_path)
            if not rows:
                self.show_snackbar(t("clients.import.empty"), error=True)
                return

            existing_clients = self._fetch_all_clients()
            by_ci: dict[str, dict] = {}
            by_meter: dict[str, dict] = {}
            for client in existing_clients:
                ci_key = normalize_identifier(client.get("ci_ruc"))
                meter_key = normalize_identifier(client.get("numero_medidor"))
                if ci_key:
                    by_ci[ci_key] = client
                if meter_key:
                    by_meter[meter_key] = client

            for idx, row in enumerate(rows, start=2):
                try:
                    name = str(
                        pick_first_value(
                            row,
                            ["nombre_completo", "nome_completo", "nome", "nombre", "cliente"],
                            "",
                        )
                    ).strip()
                    ci_ruc = str(
                        pick_first_value(
                            row,
                            ["ci_ruc", "ci", "ruc", "documento", "doc", "cedula"],
                            "",
                        )
                    ).strip()
                    meter = str(
                        pick_first_value(
                            row,
                            ["numero_medidor", "medidor", "relogio", "nro_medidor"],
                            "",
                        )
                    ).strip()
                    direccion = str(
                        pick_first_value(
                            row,
                            ["direccion", "endereco", "endereco_instalacao"],
                            "",
                        )
                    ).strip()
                    manzana = str(pick_first_value(row, ["manzana", "mz", "quadra"], "")).strip()
                    lote = str(pick_first_value(row, ["lote", "lt"], "")).strip()
                    telefono = str(pick_first_value(row, ["telefono", "telefone"], "") or "").strip()
                    celular = str(pick_first_value(row, ["celular", "whatsapp"], "") or "").strip()
                    categoria = str(
                        pick_first_value(row, ["categoria", "category", "tipo"], "RESIDENCIAL")
                    ).strip().upper()
                    if categoria not in {"RESIDENCIAL", "COMERCIAL", "SOCIAL"}:
                        categoria = "RESIDENCIAL"

                    is_sponsor = self._parse_bool(
                        pick_first_value(row, ["is_sponsor", "es_sponsor", "sponsor"], None)
                    )
                    subsidio_raw = pick_first_value(
                        row,
                        ["subsidio_porcentagem", "subsidio", "subsidio_pct"],
                        None,
                    )
                    subsidio = None
                    if subsidio_raw not in (None, ""):
                        subsidio = int(float(str(subsidio_raw).replace(",", ".")))

                    ci_key = normalize_identifier(ci_ruc)
                    meter_key = normalize_identifier(meter)
                    existing = by_ci.get(ci_key) if ci_key else None
                    if not existing and meter_key:
                        existing = by_meter.get(meter_key)

                    if existing:
                        update_payload: dict = {}
                        if name:
                            update_payload["nombre_completo"] = name
                        if ci_ruc:
                            update_payload["ci_ruc"] = ci_ruc
                        if telefono:
                            update_payload["telefono"] = telefono
                        if celular:
                            update_payload["celular"] = celular
                        if direccion:
                            update_payload["direccion"] = direccion
                        if manzana:
                            update_payload["manzana"] = manzana
                        if lote:
                            update_payload["lote"] = lote
                        if meter:
                            update_payload["numero_medidor"] = meter
                        update_payload["categoria"] = categoria
                        if is_sponsor is not None:
                            update_payload["is_sponsor"] = bool(is_sponsor)
                            if is_sponsor:
                                update_payload["sponsor_id"] = None
                                update_payload["subsidio_porcentagem"] = None
                        if subsidio is not None and not update_payload.get("is_sponsor", False):
                            update_payload["subsidio_porcentagem"] = subsidio
                        if not update_payload:
                            skipped += 1
                            continue
                        client_service.update(existing["id"], update_payload)
                        updated += 1
                    else:
                        required_missing = [
                            key
                            for key, value in {
                                "nombre_completo": name,
                                "ci_ruc": ci_ruc,
                                "direccion": direccion,
                                "manzana": manzana,
                                "lote": lote,
                                "numero_medidor": meter,
                            }.items()
                            if not value
                        ]
                        if required_missing:
                            skipped += 1
                            errors.append(t("clients.import.row_missing", idx=idx, fields=", ".join(required_missing)))
                            continue
                        payload = {
                            "nombre_completo": name,
                            "ci_ruc": ci_ruc,
                            "telefono": telefono or None,
                            "celular": celular or None,
                            "direccion": direccion,
                            "manzana": manzana,
                            "lote": lote,
                            "numero_medidor": meter,
                            "categoria": categoria,
                        }
                        if is_sponsor is not None:
                            payload["is_sponsor"] = bool(is_sponsor)
                        if subsidio is not None and not payload.get("is_sponsor", False):
                            payload["subsidio_porcentagem"] = subsidio
                        created_client = client_service.create(payload)
                        created += 1
                        ci_new = normalize_identifier(created_client.get("ci_ruc", ci_ruc))
                        meter_new = normalize_identifier(created_client.get("numero_medidor", meter))
                        if ci_new:
                            by_ci[ci_new] = created_client
                        if meter_new:
                            by_meter[meter_new] = created_client
                except Exception as row_err:
                    errors.append(t("clients.import.row_error", idx=idx, error=row_err))

            summary = t(
                "clients.import.summary",
                created=created, updated=updated, skipped=skipped, errors=len(errors),
            )
            self.show_snackbar(summary, error=bool(errors))
            if errors:
                preview = "; ".join(errors[:3])
                self.show_snackbar(t("clients.import.errors_preview", preview=preview), error=True)
            self._run_load_clients()
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.import_failed"), error=True)
        finally:
            self.loading_overlay.hide()

    def _view_client(self, client: dict):
        self.selected_client = client
        self._show_detail_panel(client)

    def _edit_client(self, client: dict):
        print(f"[ClientsView] editar_click id={client.get('id')} nome={client.get('nombre_completo')}")
        self._open_form(client=client)

    def _delete_client(self, client: dict):
        print(f"[ClientsView] excluir_click id={client.get('id')} nome={client.get('nombre_completo')}")
        modal: AppModal = None  # type: ignore

        def do_delete(e):
            try:
                print(f"[ClientsView] excluir_confirmado id={client.get('id')}")
                client_service.delete(client["id"])
                modal.close()
                self.show_snackbar(t("clients.removed", name=client['nombre_completo']))
                self._run_load_clients()
            except APIError as err:
                print(f"[ClientsView] excluir_erro id={client.get('id')} erro={err.detail}")
                self.show_snackbar(str(err.detail), error=True)

        modal = AppModal(
            page=self.page,
            title=t("clients.confirm_delete_title"),
            content=ft.Text(t("clients.confirm_delete_body", name=client['nombre_completo'])),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda e: modal.close()),
                ModalAction(t("common.delete"), on_click=do_delete, danger=True),
            ],
            width_pct=0.35,
        )
        modal.open()

    def _open_form(self, e=None, client: dict | None = None):
        is_edit = client is not None
        title = t("clients.edit") if is_edit else t("clients.new")

        try:
            possible_sponsors = [c for c in self.clients if c.get("is_sponsor")]
            if not possible_sponsors:
                possible_sponsors = client_service.search(is_sponsor=True, limit=200)
        except APIError:
            possible_sponsors = []

        fields = {
            "nombre_completo": create_text_field(
                t("clients.field.full_name"),
                value=client.get("nombre_completo", "") if client else "",
                width=420,
            ),
            "ci_ruc": create_text_field(t("clients.col.ci_ruc"), value=client.get("ci_ruc", "") if client else "", width=220),
            "telefono": create_text_field(t("clients.field.phone"), value=client.get("telefono", "") if client else "", width=220),
            "celular": create_text_field(t("clients.field.cellphone"), value=client.get("celular", "") if client else "", width=220),
            "direccion": create_text_field(t("clients.field.address"), value=client.get("direccion", "") if client else "", width=660),
            "manzana": create_text_field(t("clients.field.block"), value=client.get("manzana", "") if client else "", width=160),
            "lote": create_text_field(t("clients.field.lot"), value=client.get("lote", "") if client else "", width=160),
            "numero_medidor": create_text_field(
                t("clients.field.meter_no"),
                value=client.get("numero_medidor", "") if client else "",
                width=220,
            ),
        }

        categoria_dropdown = ft.Dropdown(
            label=t("clients.col.category"),
            value=client.get("categoria", "RESIDENCIAL") if client else "RESIDENCIAL",
            options=[
                ft.dropdown.Option("RESIDENCIAL"),
                ft.dropdown.Option("COMERCIAL"),
                ft.dropdown.Option("SOCIAL"),
            ],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            width=150,
        )

        subsidio_field = create_text_field(
            t("clients.field.subsidy"),
            value=str(client.get("subsidio_porcentagem", "")) if client and client.get("subsidio_porcentagem") is not None else "",
            width=120,
        )

        sponsor_options = [ft.dropdown.Option("", t("clients.field.no_sponsor"))]
        for c in possible_sponsors:
            if is_edit and c.get("id") == client.get("id"):
                continue
            sponsor_options.append(ft.dropdown.Option(c["id"], f"{c.get('nombre_completo', '-')} ({c.get('ci_ruc', '-')})"))

        sponsor_dropdown = ft.Dropdown(
            label=t("clients.field.sponsor"),
            value=(client.get("sponsor_id") if client and client.get("sponsor_id") else ""),
            options=sponsor_options,
            width=280,
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
        )

        is_sponsor_checkbox = ft.Checkbox(
            label=t("clients.field.is_sponsor"),
            value=bool(client.get("is_sponsor", False)) if client else False,
        )

        def toggle_sponsor_mode(ev):
            sponsor_mode = bool(is_sponsor_checkbox.value)
            if sponsor_mode:
                sponsor_dropdown.value = ""
                subsidio_field.value = ""
            sponsor_dropdown.disabled = sponsor_mode
            subsidio_field.disabled = sponsor_mode
            self._safe_update(sponsor_dropdown)
            self._safe_update(subsidio_field)

        is_sponsor_checkbox.on_change = toggle_sponsor_mode
        toggle_sponsor_mode(None)

        # Estado GPS — persiste entre abertura do picker e salvamento
        _gps: dict = {
            "lat": client.get("instalacao_latitude") if client else None,
            "lon": client.get("instalacao_longitude") if client else None,
        }

        def _gps_label() -> str:
            if _gps["lat"] is not None and _gps["lon"] is not None:
                return f"{_gps['lat']:.6f}, {_gps['lon']:.6f}"
            return t("clients.gps.undefined")

        gps_display = ft.Text(
            _gps_label(),
            size=12,
            color=COLORS["text_secondary"] if _gps["lat"] is None else COLORS["accent_success"],
            font_family="monospace",
        )

        def on_gps_selected(lat: float, lon: float):
            _gps["lat"] = lat
            _gps["lon"] = lon
            gps_display.value = f"{lat:.6f}, {lon:.6f}"
            gps_display.color = COLORS["accent_success"]
            try:
                gps_display.update()
            except Exception:
                pass

        gps_row = ft.Row(
            [
                ft.Icon(ft.Icons.LOCATION_ON, size=16, color=COLORS["text_muted"]),
                ft.Text("GPS:", size=12, color=COLORS["text_secondary"]),
                gps_display,
                ft.Container(expand=True),
                create_button(
                    t("clients.gps.adjust"),
                    icon=ft.Icons.MAP,
                    primary=False,
                    on_click=lambda e: open_gps_picker_dialog(
                        self.page,
                        initial_lat=_gps["lat"],
                        initial_lon=_gps["lon"],
                        on_confirm=on_gps_selected,
                    ),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        status_dropdown = None
        if is_edit:
            status_dropdown = ft.Dropdown(
                label=t("clients.col.status"),
                value=client.get("status", "ATIVO"),
                options=[ft.dropdown.Option("ATIVO"), ft.dropdown.Option("INATIVO"), ft.dropdown.Option("CORTADO")],
                border_color=COLORS["border"],
                focused_border_color=COLORS["border_focus"],
                width=130,
            )

        error_text = ft.Text("", color=COLORS["accent_error"], size=FONTS["size_sm"], visible=False)
        _modal_ref: list[AppModal] = []

        def save(ev):
            data = {
                "nombre_completo": fields["nombre_completo"].value,
                "ci_ruc": fields["ci_ruc"].value,
                "telefono": fields["telefono"].value or None,
                "celular": fields["celular"].value or None,
                "direccion": fields["direccion"].value,
                "manzana": fields["manzana"].value,
                "lote": fields["lote"].value,
                "numero_medidor": fields["numero_medidor"].value,
                "categoria": categoria_dropdown.value,
                "is_sponsor": bool(is_sponsor_checkbox.value),
                "sponsor_id": sponsor_dropdown.value or None,
            }

            if not data["is_sponsor"] and subsidio_field.value and subsidio_field.value.strip():
                try:
                    data["subsidio_porcentagem"] = int(subsidio_field.value.strip())
                except ValueError:
                    pass
            elif data["is_sponsor"]:
                data["sponsor_id"] = None
                data["subsidio_porcentagem"] = None

            if is_edit and status_dropdown:
                data["status"] = status_dropdown.value

            if _gps["lat"] is not None and _gps["lon"] is not None:
                data["instalacao_latitude"] = _gps["lat"]
                data["instalacao_longitude"] = _gps["lon"]

            try:
                if is_edit:
                    client_service.update(client["id"], data)
                    self.show_snackbar(t("clients.updated"))
                else:
                    client_service.create(data)
                    self.show_snackbar(t("clients.created"))
                if _modal_ref:
                    _modal_ref[0].close()
                self._run_load_clients()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                self._safe_update(error_text)

        form_content = ft.Column(
            [
                ft.Row([fields["nombre_completo"]], spacing=8),
                ft.Row([fields["ci_ruc"], fields["telefono"], fields["celular"]], spacing=8, wrap=True),
                ft.Row([fields["direccion"]], spacing=8),
                ft.Row([fields["manzana"], fields["lote"], fields["numero_medidor"]], spacing=8, wrap=True),
                ft.Row(
                    [categoria_dropdown, is_sponsor_checkbox] + ([status_dropdown] if status_dropdown else []),
                    spacing=12,
                    wrap=True,
                ),
                ft.Row([subsidio_field, sponsor_dropdown], spacing=8, wrap=True),
                gps_row,
                error_text,
            ],
            spacing=SPACING["md"],
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        modal = AppModal(
            page=self.page,
            title=title,
            content=form_content,
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal.close()),
                ModalAction(t("common.save"), on_click=save, primary=True),
            ],
            width_pct=0.65,
        )
        _modal_ref.append(modal)
        modal.open()

    def _show_detail_panel(self, client: dict):
        try:
            readings = client_service.get_readings(client["id"], limit=12)
        except APIError:
            readings = []

        try:
            invoices = client_service.get_invoices(client["id"], limit=12)
        except APIError:
            invoices = []

        try:
            balance = client_service.get_pending_balance(client["id"])
        except APIError:
            balance = {"saldo_pendiente": 0, "facturas_pendientes": 0}

        status_badge = create_badge(client["status"], get_status_color(client["status"]))

        info = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(client["nombre_completo"], size=FONTS["size_lg"], weight=ft.FontWeight.BOLD, color=COLORS["text_primary"]),
                        status_badge,
                    ],
                    spacing=SPACING["sm"],
                ),
                ft.Text(t("clients.detail.ci_ruc", value=client['ci_ruc']), color=COLORS["text_secondary"]),
                ft.Text(t("clients.detail.meter", value=client['numero_medidor']), color=COLORS["text_secondary"]),
                ft.Text(t("clients.detail.mz_lt", mz=client['manzana'], lt=client['lote']), color=COLORS["text_secondary"]),
                ft.Text(t("clients.detail.category", value=client.get('categoria', '-')), color=COLORS["text_secondary"]),
                ft.Text(t("clients.detail.is_sponsor", value=t("common.yes") if client.get('is_sponsor') else t("common.no")), color=COLORS["text_secondary"]),
                ft.Text(
                    t("clients.detail.has_sponsor", value=t("common.yes") if client.get("has_sponsor") else t("common.no"))
                    + (t("clients.detail.subsidy_pct", value=client.get('subsidio_porcentagem')) if client.get("subsidio_porcentagem") is not None else ""),
                    color=COLORS["text_secondary"],
                ),
                ft.Text(
                    t(
                        "clients.detail.balance",
                        amount=format_currency(balance.get('saldo_pendiente', 0), 'Gs.'),
                        count=balance.get('facturas_pendientes', 0),
                    ),
                    color=COLORS["text_primary"],
                ),
                ft.Row(
                    [
                        create_button(
                            t("clients.detail.view_photo"),
                            icon=ft.Icons.PHOTO_CAMERA,
                            primary=False,
                            on_click=lambda e: self._show_client_photo_dialog(client),
                        ),
                    ],
                    visible=bool(client.get("foto_medidor_url") or client.get("instalacao_latitude")),
                ),
            ],
            spacing=SPACING["xs"],
        )

        tabs = CustomTabs(
            tabs=[
                TabItem(t("clients.tab.readings"), self._build_readings_tab(readings)),
                TabItem(t("clients.tab.invoices"), self._build_invoices_tab(invoices)),
            ],
            selected_index=0,
        )

        close_btn = ft.IconButton(icon=ft.Icons.CLOSE, on_click=lambda ev: self._hide_detail_panel(), icon_color=COLORS["text_secondary"])

        self.detail_panel.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row([ft.Container(expand=True), close_btn]),
                    info,
                    ft.Divider(color=COLORS["border"]),
                    tabs,
                ],
                spacing=SPACING["md"],
            ),
            width=430,
            padding=SPACING["md"],
            bgcolor=COLORS["bg_surface"],
            border=ft.Border.only(left=ft.BorderSide(1, COLORS["border"])),
        )
        self.detail_panel.visible = True
        self.detail_panel.update()

    def _hide_detail_panel(self):
        self.detail_panel.visible = False
        self.detail_panel.update()

    def _show_client_photo_dialog(self, client: dict):
        photo_url = client.get("foto_medidor_url")
        gps_lat = client.get("instalacao_latitude")
        gps_lon = client.get("instalacao_longitude")

        if not photo_url and (gps_lat is None or gps_lon is None):
            self.show_snackbar(t("clients.no_photo_gps"))
            return

        content_controls: list[ft.Control] = []
        if photo_url:
            content_controls.append(
                ImageViewer(
                    image_url=photo_url,
                    title=t("clients.photo.meter_title", name=client.get('nombre_completo', '-')),
                    gps_latitude=gps_lat,
                    gps_longitude=gps_lon,
                    width=620,
                    height=380,
                )
            )
        else:
            content_controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(t("clients.photo.no_meter_photo"), color=COLORS["text_secondary"]),
                            ft.Text(
                                f"GPS: {gps_lat:.6f}, {gps_lon:.6f}" if gps_lat is not None and gps_lon is not None else t("clients.photo.gps_unavailable"),
                                color=COLORS["text_secondary"],
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=SPACING["md"],
                )
            )

        modal = AppModal(
            page=self.page,
            title=t("clients.photo.install_title", name=client.get('nombre_completo', '-')),
            content=ft.Column(content_controls, spacing=8, tight=True),
            actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
            width_pct=0.6,
        )
        modal.open()

    def _build_readings_tab(self, readings: list) -> ft.Control:
        if not readings:
            return ft.Container(content=ft.Text(t("clients.empty_readings"), color=COLORS["text_muted"]), padding=SPACING["md"])

        items = []
        for r in readings[:12]:
            items.append(
                ft.Row(
                    [
                        ft.Text(f"{r['mes_referencia']:02d}/{r['ano_referencia']}", color=COLORS["text_secondary"], size=FONTS["size_sm"]),
                        ft.Text(f"{r['valor_leitura']} m3", color=COLORS["text_primary"]),
                        ft.Text(f"(+{r.get('consumo_calculado', 0) or 0})", color=COLORS["accent_secondary"], size=FONTS["size_sm"]),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )
            )

        return ft.Container(content=ft.Column(items, spacing=SPACING["xs"], scroll=ft.ScrollMode.AUTO), padding=SPACING["sm"])

    def _build_invoices_tab(self, invoices: list) -> ft.Control:
        if not invoices:
            return ft.Container(content=ft.Text(t("clients.empty_invoices"), color=COLORS["text_muted"]), padding=SPACING["md"])

        items = []
        for inv in invoices[:12]:
            items.append(
                ft.Row(
                    [
                        ft.Text(f"{inv['mes_referencia']:02d}/{inv['ano_referencia']}", color=COLORS["text_secondary"], size=FONTS["size_sm"]),
                        ft.Text(format_currency(inv.get("valor_total", 0), "Gs."), color=COLORS["text_primary"]),
                        create_badge(inv["status"], get_status_color(inv["status"])),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )
            )

        return ft.Container(content=ft.Column(items, spacing=SPACING["xs"], scroll=ft.ScrollMode.AUTO), padding=SPACING["sm"])
