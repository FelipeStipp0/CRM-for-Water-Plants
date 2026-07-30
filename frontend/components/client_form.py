"""
Formulário de cliente — o MESMO em qualquer lugar que cadastre ou edite.

Nasceu dentro da `clients_view`, e saiu de lá quando o balcão passou a cadastrar:
o cajero atende quem chega para se ligar à rede, e não existe "ficha resumida do
caixa" que a tesouraria completa depois — a junta não tem setores. Formulário
completo, uma validação, um lugar para corrigir.

Uso:

    open_client_form(page, show_snackbar,
                     prefill={"nombre_completo": "Juan"},   # o que já foi digitado
                     on_saved=lambda cliente: ...)          # cliente criado/editado

`on_saved` recebe o cliente devolvido pela API — é como a caja consegue seguir o
atendimento com ele já selecionado, sem recomeçar a busca.

Duplicata de CI/RUC e de medidor é recusada **pelo backend** (`POST /clients/`),
não só por esta tela: é o que garante que dois balcões simultâneos não criem o
mesmo cliente duas vezes.
"""

from __future__ import annotations

import flet as ft

from components.app_modal import AppModal, ModalAction
from components.gps_picker_dialog import open_gps_picker_dialog
from components.theme import (
    COLORS,
    FONTS,
    SPACING,
    create_button,
    create_percent_field,
    create_phone_field,
    create_text_field,
)
from services.api_client import APIError
from services.client_service import client_service
from i18n import t


def _safe_update(control: ft.Control | None) -> None:
    if control is None:
        return
    try:
        control.update()
    except Exception:  # noqa: BLE001 — controle ainda não montado é caso normal
        pass


def open_client_form(
    page: ft.Page,
    show_snackbar,
    client: dict | None = None,
    *,
    prefill: dict | None = None,
    known_clients: list[dict] | None = None,
    on_saved=None,
) -> AppModal:
    """
    Abre o formulário de cliente (novo ou edição) e devolve o modal.

    `prefill` só vale para cadastro novo: preenche os campos com o que o operador
    já digitou em outra tela (a busca do balcão, por exemplo).
    `known_clients` evita uma consulta quando quem chama já tem a lista em mão.
    """
    is_edit = client is not None
    title = t("clients.edit") if is_edit else t("clients.new")
    base = dict(client or {})
    if not is_edit and prefill:
        base.update({k: v for k, v in prefill.items() if v})

    try:
        possible_sponsors = [c for c in (known_clients or []) if c.get("is_sponsor")]
        if not possible_sponsors:
            possible_sponsors = client_service.search(is_sponsor=True, limit=200)
    except APIError:
        possible_sponsors = []

    fields = {
        "nombre_completo": create_text_field(
            t("clients.field.full_name"),
            value=base.get("nombre_completo", ""),
            max_length=200,
            keyboard_type=ft.KeyboardType.NAME,
            capitalization=ft.TextCapitalization.WORDS,
            col=12,
        ),
        "ci_ruc": create_text_field(
            t("clients.col.ci_ruc"),
            value=base.get("ci_ruc", ""),
            max_length=20,
            col={"sm": 12, "md": 4},
        ),
        "telefono": create_phone_field(
            t("clients.field.phone"),
            value=base.get("telefono", "") or "",
            max_length=30,
            col={"sm": 12, "md": 4},
        ),
        "celular": create_phone_field(
            t("clients.field.cellphone"),
            value=base.get("celular", "") or "",
            max_length=30,
            col={"sm": 12, "md": 4},
        ),
        "direccion": create_text_field(
            t("clients.field.address"),
            value=base.get("direccion", "") or "",
            max_length=300,
            keyboard_type=ft.KeyboardType.STREET_ADDRESS,
            capitalization=ft.TextCapitalization.SENTENCES,
            col=12,
        ),
        "manzana": create_text_field(
            t("clients.field.block"),
            value=base.get("manzana", "") or "",
            max_length=10,
            col={"sm": 6, "md": 3},
        ),
        "lote": create_text_field(
            t("clients.field.lot"),
            value=base.get("lote", "") or "",
            max_length=10,
            col={"sm": 6, "md": 3},
        ),
        "numero_medidor": create_text_field(
            t("clients.field.meter_no"),
            value=base.get("numero_medidor", "") or "",
            max_length=50,
            capitalization=ft.TextCapitalization.CHARACTERS,
            col={"sm": 12, "md": 6},
        ),
    }

    categoria_dropdown = ft.Dropdown(
        label=t("clients.col.category"),
        value=base.get("categoria", "RESIDENCIAL") or "RESIDENCIAL",
        options=[
            ft.dropdown.Option("RESIDENCIAL"),
            ft.dropdown.Option("COMERCIAL"),
            ft.dropdown.Option("SOCIAL"),
        ],
        border_color=COLORS["border"],
        focused_border_color=COLORS["border_focus"],
        width=180,
        filled=True,
        fill_color=COLORS["bg_input"],
        border_radius=10,
    )

    subsidio_field = create_percent_field(
        t("clients.field.subsidy"),
        value=(str(base.get("subsidio_porcentagem"))
               if base.get("subsidio_porcentagem") is not None else ""),
        width=150,
    )

    sponsor_options = [ft.dropdown.Option("", t("clients.field.no_sponsor"))]
    for c in possible_sponsors:
        if is_edit and c.get("id") == base.get("id"):
            continue
        sponsor_options.append(ft.dropdown.Option(
            c["id"], f"{c.get('nombre_completo', '-')} ({c.get('ci_ruc', '-')})"))

    sponsor_dropdown = ft.Dropdown(
        label=t("clients.field.sponsor"),
        value=base.get("sponsor_id") or "",
        options=sponsor_options,
        width=280,
        filled=True,
        fill_color=COLORS["bg_input"],
        border_radius=10,
        border_color=COLORS["border"],
        focused_border_color=COLORS["border_focus"],
    )

    is_sponsor_checkbox = ft.Checkbox(
        label=t("clients.field.is_sponsor"),
        value=bool(base.get("is_sponsor", False)),
    )

    def toggle_sponsor_mode(ev):
        sponsor_mode = bool(is_sponsor_checkbox.value)
        if sponsor_mode:
            sponsor_dropdown.value = ""
            subsidio_field.value = ""
        sponsor_dropdown.disabled = sponsor_mode
        subsidio_field.disabled = sponsor_mode
        _safe_update(sponsor_dropdown)
        _safe_update(subsidio_field)

    is_sponsor_checkbox.on_change = toggle_sponsor_mode
    toggle_sponsor_mode(None)

    # Estado GPS — persiste entre abertura do picker e salvamento
    _gps: dict = {
        "lat": base.get("instalacao_latitude"),
        "lon": base.get("instalacao_longitude"),
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
        _safe_update(gps_display)

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
                    page,
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
            value=base.get("status", "ATIVO"),
            options=[ft.dropdown.Option("ATIVO"), ft.dropdown.Option("INATIVO"),
                     ft.dropdown.Option("CORTADO")],
            border_color=COLORS["border"],
            focused_border_color=COLORS["border_focus"],
            width=130,
        )

    error_text = ft.Text("", color=COLORS["accent_error"], size=FONTS["size_sm"], visible=False)
    _modal_ref: list[AppModal] = []

    def save(ev):
        for field in list(fields.values()) + [subsidio_field]:
            field.error = None

        first_invalid: ft.TextField | None = None

        def require(field: ft.TextField, min_length: int = 1):
            nonlocal first_invalid
            value = (field.value or "").strip()
            if len(value) >= min_length:
                return
            field.error = (
                t("common.required") if min_length == 1
                else t("common.min_chars", count=min_length)
            )
            first_invalid = first_invalid or field

        require(fields["nombre_completo"], 2)
        require(fields["ci_ruc"], 3)
        require(fields["direccion"], 5)
        require(fields["numero_medidor"])

        subsidy_value: int | None = None
        if subsidio_field.value and subsidio_field.value.strip():
            try:
                subsidy_value = int(subsidio_field.value.strip())
                if not 0 <= subsidy_value <= 100:
                    raise ValueError
            except ValueError:
                subsidio_field.error = t("common.range_0_100")
                first_invalid = first_invalid or subsidio_field

        if first_invalid is not None:
            _safe_update(form_content)
            if page:
                page.run_task(first_invalid.focus)
            return

        data = {
            "nombre_completo": (fields["nombre_completo"].value or "").strip(),
            "ci_ruc": (fields["ci_ruc"].value or "").strip(),
            "telefono": (fields["telefono"].value or "").strip() or None,
            "celular": (fields["celular"].value or "").strip() or None,
            "direccion": (fields["direccion"].value or "").strip(),
            "manzana": (fields["manzana"].value or "").strip(),
            "lote": (fields["lote"].value or "").strip(),
            "numero_medidor": (fields["numero_medidor"].value or "").strip(),
            "categoria": categoria_dropdown.value,
            "is_sponsor": bool(is_sponsor_checkbox.value),
            "sponsor_id": sponsor_dropdown.value or None,
        }

        if not data["is_sponsor"] and subsidy_value is not None:
            data["subsidio_porcentagem"] = subsidy_value
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
                saved = client_service.update(base["id"], data)
                show_snackbar(t("clients.updated"))
            else:
                saved = client_service.create(data)
                show_snackbar(t("clients.created"))
            if _modal_ref:
                _modal_ref[0].close()
            if on_saved:
                on_saved(saved)
        except APIError as err:
            error_text.value = str(err.detail)
            error_text.visible = True
            _safe_update(error_text)

    form_content = ft.Column(
        [
            ft.ResponsiveRow([fields["nombre_completo"]], spacing=8, run_spacing=8),
            ft.ResponsiveRow(
                [fields["ci_ruc"], fields["telefono"], fields["celular"]],
                spacing=8, run_spacing=8,
            ),
            ft.ResponsiveRow([fields["direccion"]], spacing=8, run_spacing=8),
            ft.ResponsiveRow(
                [fields["manzana"], fields["lote"], fields["numero_medidor"]],
                spacing=8, run_spacing=8,
            ),
            ft.Row(
                [categoria_dropdown, is_sponsor_checkbox]
                + ([status_dropdown] if status_dropdown else []),
                spacing=12, wrap=True,
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
        page=page,
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
    return modal
