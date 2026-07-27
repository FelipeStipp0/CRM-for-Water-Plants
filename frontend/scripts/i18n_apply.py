"""
Aplica a migração i18n:
  1. Injeta as chaves NOVAS (scripts/i18n_translations.json) nos dicts ES e PT de i18n.py.
  2. Reescreve os literais crus das views/components para t("chave"), conforme i18n_keymap.json.
  3. Garante `from i18n import t` nos arquivos alterados.

Idempotente: não duplica chaves já presentes; não reescreve literais já convertidos.
Rode a auditoria antes/depois: python scripts/i18n_extract.py

    cd frontend && python scripts/i18n_apply.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent
I18N = FRONTEND / "i18n.py"

keymap = json.loads((HERE / "i18n_keymap.json").read_text(encoding="utf-8"))
trans = json.loads((HERE / "i18n_translations.json").read_text(encoding="utf-8"))
inventory = json.loads((HERE / "i18n_inventory.json").read_text(encoding="utf-8"))

TEXT2KEY: dict[str, str] = keymap["map"]

# Prefixos de chamada por 'kind' (o literal é o 1º arg / o label=).
KIND_PREFIX = {
    "button": "create_button(",
    "header": "create_header(",
    "modal_action": "ModalAction(",
    "checkbox": "ft.Checkbox(label=",
    "tab_text": "ft.Tab(text=",
    "tab_label": "ft.Tab(label=",
}


def esc(s: str) -> str:
    return s.replace('"', '\\"')


def inject_catalog() -> int:
    src = I18N.read_text(encoding="utf-8")
    existing_es = f'ES: dict[str, str] = {{'
    existing_pt = f'PT: dict[str, str] = {{'
    if existing_es not in src or existing_pt not in src:
        raise SystemExit("Não achei os cabeçalhos dos dicts ES/PT em i18n.py")

    added = 0
    es_lines, pt_lines = [], []
    for key in sorted(trans):
        if f'"{key}"' in src:  # já existe → não duplica
            continue
        es_lines.append(f'    "{key}": "{esc(trans[key]["es"])}",')
        pt_lines.append(f'    "{key}": "{esc(trans[key]["pt"])}",')
        added += 1

    if not added:
        return 0

    block_es = "\n    # ----- migração i18n (auto) -----\n" + "\n".join(es_lines) + "\n"
    block_pt = "\n    # ----- migração i18n (auto) -----\n" + "\n".join(pt_lines) + "\n"
    src = src.replace(existing_es, existing_es + block_es, 1)
    src = src.replace(existing_pt, existing_pt + block_pt, 1)
    I18N.write_text(src, encoding="utf-8")
    return added


def rewrite_file(path: Path, rows: list[dict]) -> int:
    src = path.read_text(encoding="utf-8")
    orig = src
    # literais mais longos primeiro (segurança extra)
    rows = sorted(rows, key=lambda r: -len(r["text"]))
    n = 0
    for r in rows:
        text = r["text"]
        key = TEXT2KEY.get(text)
        if not key:
            continue
        prefix = KIND_PREFIX[r["kind"]]
        for q in ('"', "'"):
            old = f'{prefix}{q}{text}{q}'
            new = f'{prefix}t("{key}")'
            if old in src:
                src = src.replace(old, new)
                n += 1
    if src != orig:
        if "from i18n import t" not in src:
            # insere o import após o bloco de imports do flet
            src = src.replace("import flet as ft\n", "import flet as ft\n\nfrom i18n import t\n", 1)
        path.write_text(src, encoding="utf-8")
    return n


def main() -> None:
    added = inject_catalog()
    print(f"Catálogo: +{added} chaves novas em ES e PT.")

    by_file: dict[str, list[dict]] = {}
    for row in inventory:
        by_file.setdefault(row["file"], []).append(row)

    total = 0
    for rel, rows in sorted(by_file.items()):
        n = rewrite_file(FRONTEND / rel, rows)
        if n:
            print(f"  {rel}: {n} literais -> t()")
            total += n
    print(f"Total reescrito: {total} literais.")


if __name__ == "__main__":
    main()
