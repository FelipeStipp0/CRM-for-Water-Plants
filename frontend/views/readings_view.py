"""
WMApp Frontend - Readings View
Tela de leituras com suporte a cadastro individual e lote por rota.
"""
from datetime import datetime

import flet as ft

from components.data_table import DataTable
from components.image_viewer import ImageViewer
from components.client_search_field import ClientSearchField
from components.pagination import Pagination
from components.search_bar import SearchBar
from components.app_modal import AppModal, ModalAction
from components.theme import (
    COLORS,
    SPACING,
    create_button,
    create_header,
    create_integer_field,
    create_text_field,
)
from i18n import t
from services.api_client import APIError
from utils.errors import friendly_error
from services.client_service import client_service
from services.reading_service import reading_service
from utils.excel_import import normalize_identifier, normalize_name, pick_first_value, read_excel_rows


class ReadingsView(ft.Container):
    """Tela de gestao de leituras."""

    def __init__(self, show_snackbar):
        super().__init__()
        self.show_snackbar = show_snackbar
        self._loaded = False
        self.mes = datetime.now().month
        self.ano = datetime.now().year
        self.current_mode = "readings"
        self._loading_readings = False
        self._page_size = 100

        self._build()
        self.on_visible = self._on_visible

    def _on_visible(self, e):
        if self.page:
            try:
                self.page.run_thread(self.trigger_initial_load)
                return
            except Exception as err:
                print(f"[ReadingsView] on_visible_run_thread_error err={err}")
        self.trigger_initial_load()

    def trigger_initial_load(self):
        self._refresh_all()

    def _safe_loading_update(self):
        try:
            self.loading.update()
        except Exception as err:
            print(f"[ReadingsView] loading_update_error err={err}")
            if self.page:
                try:
                    self.page.update()
                except Exception as page_err:
                    print(f"[ReadingsView] page_update_fallback_error err={page_err}")

    def _build(self):
        self.mes_field = create_integer_field(t("readings.field.month"), value=str(self.mes), width=80, max_length=2)
        self.ano_field = create_integer_field(t("readings.field.year"), value=str(self.ano), width=100, max_length=4)
        self.manzana_filter = create_text_field(t("clients.field.block"), width=120)

        self.mode_tabs = ft.RadioGroup(
            value="readings",
            on_change=self._change_mode,
            content=ft.Row(
                [
                    ft.Radio(value="readings", label=t("readings.tab.readings")),
                    ft.Radio(value="pending", label=t("readings.tab.pending")),
                ],
                spacing=8,
            ),
        )

        header = ft.Row(
            [
                create_header(t("readings.title")),
                ft.Container(expand=True),
                create_button(t("readings.import_excel"), icon=ft.Icons.UPLOAD_FILE, on_click=self._open_import_excel, primary=False),
                create_button(t("readings.register"), icon=ft.Icons.ADD, on_click=self._open_single_form),
                create_button(t("readings.batch"), icon=ft.Icons.LIST_ALT, on_click=self._open_batch_form, primary=False),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        filter_row = ft.Row(
            [
                self.mes_field,
                self.ano_field,
                self.manzana_filter,
                create_button(t("readings.apply"), icon=ft.Icons.FILTER_ALT, on_click=lambda e: (self.pagination.reset(), self._refresh_all(skip=0)), primary=False),
                self.mode_tabs,
            ],
            wrap=True,
            spacing=SPACING["sm"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.search_bar = SearchBar(
            placeholder=t("readings.search_placeholder"),
            on_search=self._apply_local_search,
        )

        self.table = DataTable(
            columns=[
                {"key": "cliente_nombre", "label": t("readings.col.client"), "min_width": 200, "flex": 3, "priority": 1, "hideable": False, "align": "left"},
                {"key": "cliente_medidor", "label": t("readings.col.meter"), "min_width": 100, "flex": 1, "priority": 2, "align": "center"},
                {"key": "cliente_manzana", "label": t("readings.col.mz"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "cliente_lote", "label": t("readings.col.lt"), "min_width": 48, "flex": 1, "priority": 2, "hideable": False, "align": "center"},
                {"key": "valor_leitura", "label": t("readings.col.reading"), "min_width": 90, "flex": 1, "priority": 2, "align": "right"},
                {"key": "consumo_calculado", "label": t("readings.col.consumption"), "min_width": 100, "flex": 1, "priority": 1, "align": "right"},
                {"key": "foto", "label": t("readings.col.photo"), "min_width": 60, "flex": 1, "priority": 3, "align": "center"},
                {"key": "gps", "label": t("readings.col.gps"), "min_width": 60, "flex": 1, "priority": 3, "align": "center"},
            ],
            data=[],
            on_row_click=self._open_row_media,
            show_actions=False,
        )

        self._table_data = []
        self.loading = ft.ProgressRing(width=28, height=28, visible=False)
        self.pagination = Pagination(page_size=self._page_size, on_change=self._on_page_change)

        self.content = ft.Column(
            [
                header,
                filter_row,
                self.search_bar,
                ft.Stack(
                    [
                        self.table,
                        ft.Container(content=self.loading, alignment=ft.Alignment(0, 0), expand=True),
                    ],
                    expand=True,
                ),
                self.pagination,
            ],
            spacing=SPACING["sm"],
            expand=True,
        )
        self.padding = ft.Padding.symmetric(horizontal=SPACING["lg"], vertical=SPACING["md"])
        self.expand = True

    def _on_page_change(self, skip: int):
        self._refresh_all(skip=skip)

    def _change_mode(self, e):
        self.current_mode = e.control.value or "readings"
        self.pagination.reset()
        self._refresh_all(skip=0)

    def _get_period(self) -> tuple[int, int]:
        try:
            mes = int((self.mes_field.value or "").strip())
            ano = int((self.ano_field.value or "").strip())
            if mes < 1 or mes > 12:
                raise ValueError("Mes invalido")
            if ano < 2000 or ano > 2100:
                raise ValueError("Ano invalido")
            return mes, ano
        except ValueError:
            raise APIError(400, "Periodo invalido. Use mes 1-12 e ano 2000-2100.")

    def _refresh_all(self, skip: int = 0):
        if self._loading_readings:
            return
        self._loading_readings = True
        # Skeleton substitui o spinner: vazio coberto pelo placeholder na tabela.
        if not getattr(self, "_table_data", None):
            try:
                self.table.show_skeleton(rows=10)
            except Exception as err:
                print(f"[ReadingsView] skeleton_error err={err}")
        try:
            mes, ano = self._get_period()
            manzana = (self.manzana_filter.value or "").strip() or None

            if self.current_mode == "pending":
                raw = reading_service.list_pending(mes=mes, ano=ano, manzana=manzana)
                data = [
                    {
                        "cliente_nombre": item.get("nombre", "-"),
                        "cliente_medidor": item.get("medidor", "-"),
                        "cliente_manzana": item.get("manzana", "-"),
                        "cliente_lote": item.get("lote", "-"),
                        "valor_leitura": "-",
                        "consumo_calculado": "-",
                        "foto_url": None,
                        "gps_latitude": None,
                        "gps_longitude": None,
                    }
                    for item in raw
                ]
                self._table_data = [self._decorate_reading_row(row) for row in data]
                self.table.set_data(self._table_data)
                # Pendentes: sem paginação (resultado único por período)
                self.pagination.update_state(current_page=0, total_items=len(data))
            else:
                raw, total = reading_service.list_paged(mes=mes, ano=ano, skip=skip, limit=self._page_size)
                data = [
                    {
                        "id": item.get("id"),
                        "client_id": item.get("client_id"),
                        "cliente_nombre": item.get("cliente_nombre", "-"),
                        "cliente_medidor": item.get("cliente_medidor", "-"),
                        "cliente_manzana": item.get("cliente_manzana", "-"),
                        "cliente_lote": item.get("cliente_lote", "-"),
                        "valor_leitura": item.get("valor_leitura", "-"),
                        "consumo_calculado": item.get("consumo_calculado", "-"),
                        "foto_url": item.get("foto_url"),
                        "gps_latitude": item.get("gps_latitude"),
                        "gps_longitude": item.get("gps_longitude"),
                    }
                    for item in raw
                ]
                self._table_data = [self._decorate_reading_row(row) for row in data]
                self.table.set_data(self._table_data)
                self.pagination.update_state(current_page=skip // self._page_size, total_items=total)
        except APIError as err:
            self.show_snackbar(friendly_error(err), error=True)
        finally:
            self._loading_readings = False

    def _apply_local_search(self, query: str):
        q = (query or "").strip().lower()
        if not q:
            self.table.set_data(self._table_data)
            return
        filtered = []
        for row in self._table_data:
            hay = " ".join(
                [
                    str(row.get("cliente_nombre", "")),
                    str(row.get("cliente_medidor", "")),
                    str(row.get("cliente_manzana", "")),
                    str(row.get("cliente_lote", "")),
                ]
            ).lower()
            if q in hay:
                filtered.append(row)
        self.table.set_data(filtered)

    def _decorate_reading_row(self, reading: dict) -> dict:
        row = dict(reading)
        foto_url = reading.get("foto_url")
        gps_lat = reading.get("gps_latitude")
        gps_lon = reading.get("gps_longitude")

        if foto_url:
            row["foto"] = ft.IconButton(
                icon=ft.Icons.PHOTO_CAMERA,
                icon_size=16,
                tooltip=t("readings.photo_tooltip"),
                icon_color=COLORS["accent_secondary"],
                on_click=lambda e, r=row: self._show_reading_photo_dialog(r),
            )
        else:
            row["foto"] = ft.Text("-", color=COLORS["text_muted"], size=12)

        if gps_lat is not None and gps_lon is not None:
            row["gps"] = ft.Icon(ft.Icons.LOCATION_ON, size=16, color=COLORS["accent_success"])
        else:
            row["gps"] = ft.Text("-", color=COLORS["text_muted"], size=12)

        return row

    def _open_row_media(self, row: dict):
        if row.get("foto_url") or (row.get("gps_latitude") is not None and row.get("gps_longitude") is not None):
            self._show_reading_photo_dialog(row)

    def _show_reading_photo_dialog(self, reading: dict):
        foto_url = reading.get("foto_url")
        gps_lat = reading.get("gps_latitude")
        gps_lon = reading.get("gps_longitude")

        if not foto_url and (gps_lat is None or gps_lon is None):
            self.show_snackbar(t("readings.no_photo_gps"))
            return

        content: list[ft.Control] = [
            ft.Text(f"Cliente: {reading.get('cliente_nombre', '-')}", color=COLORS["text_secondary"]),
            ft.Text(f"Leitura: {reading.get('valor_leitura', '-')}", color=COLORS["text_secondary"]),
        ]

        if foto_url:
            content.append(
                ImageViewer(
                    image_url=foto_url,
                    title=t("readings.photo_title"),
                    gps_latitude=gps_lat,
                    gps_longitude=gps_lon,
                    width=620,
                    height=380,
                )
            )
        else:
            content.append(
                ft.Text(
                    f"GPS: {gps_lat:.6f}, {gps_lon:.6f}" if gps_lat is not None and gps_lon is not None else "GPS nao disponivel",
                    color=COLORS["text_secondary"],
                )
            )

        modal = AppModal(
            page=self.page,
            title=t("readings.evidence_title"),
            content=ft.Column(content, spacing=8),
            actions=[ModalAction(t("common.close"), on_click=lambda e: modal.close())],
            width_pct=0.55,
        )
        modal.open()

    def _open_single_form(self, e):
        clients = client_service.list_by_route()
        if not clients:
            self.show_snackbar(t("readings.no_active_clients"), error=True)
            return

        mes, ano = self._get_period()
        client_search = ClientSearchField(clients=clients, width=440, label=t("readings.field.client"))
        valor_field = create_integer_field(
            t("readings.field.reading_value"),
            width=180,
            suffix="m³",
            autofocus=True,
        )
        obs_field = create_text_field(
            t("readings.field.observation"),
            width=440,
            multiline=True,
            min_lines=2,
            max_lines=3,
        )
        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)
        _modal_ref: list[AppModal] = []

        def save_reading(ev):
            try:
                if not client_search.selected_id:
                    raise APIError(400, t("readings.err.select_client"))
                valor = int((valor_field.value or "").strip())
                payload = {
                    "client_id": client_search.selected_id,
                    "valor_leitura": valor,
                    "mes_referencia": mes,
                    "ano_referencia": ano,
                    "observacion": (obs_field.value or "").strip() or None,
                }
                reading_service.create(payload)
                if _modal_ref:
                    _modal_ref[0].close()
                self.show_snackbar(t("readings.registered"))
                self._refresh_all()
            except ValueError:
                error_text.value = t("readings.err.reading_int")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        modal = AppModal(
            page=self.page,
            title=t("readings.register_title"),
            content=ft.Column([client_search, valor_field, obs_field, error_text], tight=True, spacing=12),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal.close()),
                ModalAction(t("common.save"), on_click=save_reading, primary=True),
            ],
            width_pct=0.4,
        )
        _modal_ref.append(modal)
        modal.open()

    def _fetch_all_clients(self, limit: int = 200, max_total: int = 5000) -> list[dict]:
        all_clients: list[dict] = []
        skip = 0
        while len(all_clients) < max_total:
            batch = client_service.list(skip=skip, limit=limit, status="ATIVO")
            if not batch:
                break
            all_clients.extend(batch)
            if len(batch) < limit:
                break
            skip += limit
        return all_clients

    async def _open_import_excel(self, e=None):
        if not self.page:
            self.show_snackbar("Tela ainda nao inicializada para importar arquivo.", error=True)
            return

        # Flet 0.84: FilePicker é serviço; pick_files é async e retorna os arquivos.
        picker = ft.FilePicker()
        if picker not in self.page.services:
            self.page.services.append(picker)
        files = await picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["xlsx", "xlsm", "xls"],
            dialog_title=t("readings.import.pick_title"),
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
                self.page.run_thread(lambda: self._import_readings_excel(selected.path))
                return
            except Exception:
                pass
        self._import_readings_excel(selected.path)

    def _import_readings_excel(self, file_path: str):
        if self._loading_readings:
            self.show_snackbar(t("readings.import.wait"), error=True)
            return

        self.loading.visible = True
        self._safe_loading_update()

        matched = 0
        unmatched = 0
        invalid = 0
        errors: list[str] = []

        try:
            mes, ano = self._get_period()
            rows = read_excel_rows(file_path)
            if not rows:
                self.show_snackbar(t("clients.import.empty"), error=True)
                return

            clients = self._fetch_all_clients()
            by_meter: dict[str, dict] = {}
            by_doc: dict[str, dict] = {}
            by_name: dict[str, dict] = {}
            for client in clients:
                meter_key = normalize_identifier(client.get("numero_medidor"))
                doc_key = normalize_identifier(client.get("ci_ruc"))
                name_key = normalize_name(client.get("nombre_completo"))
                if meter_key:
                    by_meter[meter_key] = client
                if doc_key:
                    by_doc[doc_key] = client
                if name_key and name_key not in by_name:
                    by_name[name_key] = client

            readings_by_client: dict[str, dict] = {}
            for idx, row in enumerate(rows, start=2):
                try:
                    meter = pick_first_value(
                        row,
                        ["numero_medidor", "medidor", "relogio", "nro_medidor"],
                        "",
                    )
                    doc = pick_first_value(
                        row,
                        ["ci_ruc", "documento", "doc", "cedula", "ruc"],
                        "",
                    )
                    name = pick_first_value(
                        row,
                        ["nombre_completo", "nome_completo", "nome", "nombre", "cliente"],
                        "",
                    )
                    reading_raw = pick_first_value(
                        row,
                        ["valor_leitura", "leitura", "reading", "valor"],
                        None,
                    )
                    obs = pick_first_value(
                        row,
                        ["observacion", "observacao", "obs"],
                        None,
                    )

                    if reading_raw in (None, ""):
                        invalid += 1
                        continue
                    reading_value = int(float(str(reading_raw).replace(",", ".")))

                    client = None
                    meter_key = normalize_identifier(meter)
                    doc_key = normalize_identifier(doc)
                    name_key = normalize_name(name)
                    if meter_key:
                        client = by_meter.get(meter_key)
                    if not client and doc_key:
                        client = by_doc.get(doc_key)
                    if not client and name_key:
                        client = by_name.get(name_key)

                    if not client:
                        unmatched += 1
                        errors.append(f"Linha {idx}: cliente nao encontrado (medidor/doc/nome).")
                        continue

                    cid = str(client.get("id"))
                    if not cid:
                        unmatched += 1
                        errors.append(f"Linha {idx}: client_id invalido.")
                        continue

                    readings_by_client[cid] = {
                        "client_id": cid,
                        "valor_leitura": reading_value,
                        "observacion": str(obs).strip() if obs not in (None, "") else None,
                    }
                    matched += 1
                except Exception as row_err:
                    invalid += 1
                    errors.append(f"Linha {idx}: {row_err}")

            payload_readings = list(readings_by_client.values())
            if not payload_readings:
                self.show_snackbar(t("readings.import.no_valid"), error=True)
                return

            result = reading_service.create_batch(
                {
                    "mes_referencia": mes,
                    "ano_referencia": ano,
                    "readings": payload_readings,
                }
            )
            created = int(result.get("created", 0) or 0)
            skipped = int(result.get("skipped", 0) or 0)
            self.show_snackbar(
                f"Importacao concluida. Planilha validada: {matched} match, {unmatched} sem match, "
                f"{invalid} invalidas. API: criadas {created}, ignoradas {skipped}.",
                error=bool(errors),
            )
            if errors:
                self.show_snackbar(t("clients.import.errors_preview", preview="; ".join(errors[:3])), error=True)
            self._refresh_all()
        except Exception as err:
            self.show_snackbar(friendly_error(err, fallback_key="error.import_failed"), error=True)
        finally:
            self.loading.visible = False
            self._safe_loading_update()

    def _open_batch_form(self, e):
        try:
            mes, ano = self._get_period()
            manzana = (self.manzana_filter.value or "").strip() or None
            pending = reading_service.list_pending(mes=mes, ano=ano, manzana=manzana)
        except APIError as err:
            self.show_snackbar(err.detail, error=True)
            return

        if not pending:
            self.show_snackbar(t("readings.batch.no_pending"))
            return

        rows = []
        for item in pending[:80]:
            value_field = create_integer_field(t("readings.field.reading"), width=120, suffix="m³")
            rows.append(
                {
                    "client_id": item["client_id"],
                    "field": value_field,
                }
            )

        list_controls = []
        for idx, item in enumerate(pending[:80]):
            list_controls.append(
                ft.Row(
                    [
                        ft.Text(f"{idx + 1:02d}.", width=30, color=COLORS["text_secondary"]),
                        ft.Text(
                            f"{item.get('nombre', '-') } | {item.get('medidor', '-') } | {item.get('manzana', '-')}/{item.get('lote', '-')}",
                            width=340,
                            color=COLORS["text_primary"],
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        rows[idx]["field"],
                    ],
                    spacing=8,
                )
            )

        error_text = ft.Text("", color=COLORS["accent_error"], visible=False)
        _modal_ref2: list[AppModal] = []

        def save_batch(ev):
            try:
                readings_payload = []
                for row in rows:
                    raw = (row["field"].value or "").strip()
                    if not raw:
                        continue
                    readings_payload.append(
                        {
                            "client_id": row["client_id"],
                            "valor_leitura": int(raw),
                        }
                    )

                if not readings_payload:
                    raise APIError(400, t("readings.err.at_least_one"))

                payload = {"mes_referencia": mes, "ano_referencia": ano, "readings": readings_payload}
                result = reading_service.create_batch(payload)
                if _modal_ref2:
                    _modal_ref2[0].close()
                self.show_snackbar(
                    t("readings.batch.processed", created=result.get("created", 0), skipped=result.get("skipped", 0))
                )
                self._refresh_all()
            except ValueError:
                error_text.value = t("readings.err.reading_invalid")
                error_text.visible = True
                error_text.update()
            except APIError as err:
                error_text.value = str(err.detail)
                error_text.visible = True
                error_text.update()

        modal = AppModal(
            page=self.page,
            title=t("readings.batch.title"),
            content=ft.Column(
                [
                    ft.Text(
                        t("readings.batch.period_hint", month=mes, year=ano),
                        color=COLORS["text_secondary"],
                        size=12,
                    ),
                    ft.Column(list_controls, spacing=6),
                    error_text,
                ],
                spacing=10,
            ),
            actions=[
                ModalAction(t("common.cancel"), on_click=lambda ev: modal.close()),
                ModalAction(t("readings.batch.send"), on_click=save_batch, primary=True),
            ],
            width_pct=0.5,
        )
        _modal_ref2.append(modal)
        modal.open()
