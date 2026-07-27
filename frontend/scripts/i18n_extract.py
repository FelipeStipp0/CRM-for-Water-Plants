"""
Auditoria de strings cruas (hardcoded) na UI Flet — insumo da migração i18n.

Varre frontend/views e frontend/components procurando literais de texto em
chamadas de UI que deveriam passar por t() (catálogo es/pt). NÃO altera nada:
só emite um inventário JSON (i18n_inventory.json) para as etapas seguintes
(tradução via Grok + reescrita para t()).

Uso:
    cd frontend && python scripts/i18n_extract.py
"""

import json
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
TARGET_DIRS = [FRONTEND / "views", FRONTEND / "components"]

# Chamadas cujo 1º argumento posicional é um rótulo visível ao usuário.
# Captura só quando o argumento é um literal de string ("..." ou '...'),
# ignorando quando já é t(...) ou uma variável.
CALL_PATTERNS = {
    "button": re.compile(r'create_button\(\s*(["\'])(?P<txt>(?:(?!\1).)+)\1'),
    "header": re.compile(r'create_header\(\s*(["\'])(?P<txt>(?:(?!\1).)+)\1'),
    "modal_action": re.compile(r'ModalAction\(\s*(["\'])(?P<txt>(?:(?!\1).)+)\1'),
    "checkbox": re.compile(r'ft\.Checkbox\(\s*label\s*=\s*(["\'])(?P<txt>(?:(?!\1).)+)\1'),
    "tab": re.compile(r'ft\.Tab\(\s*(?:text|label)\s*=\s*(["\'])(?P<txt>(?:(?!\1).)+)\1'),
}

# Heurística de idioma: palavras que denunciam pt-BR vazando na UI (que é es).
PT_MARKERS = re.compile(
    r'\b(ç|ã|õ|Atualizar|Transaç|Funcionário|Funcionario|Lançamento|Lancamento|'
    r'Recebimento|Despesa|Fatura|Gerar|Processar|Nova|Novo|Caixa|Informe do|'
    r'Cliente da|não|Emprestimo|Empréstimo)\b',
    re.IGNORECASE,
)


def looks_pt(text: str) -> bool:
    return bool(PT_MARKERS.search(text))


def scan() -> list[dict]:
    rows: list[dict] = []
    for d in TARGET_DIRS:
        for path in sorted(d.glob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, start=1):
                for kind, pat in CALL_PATTERNS.items():
                    for m in pat.finditer(line):
                        txt = m.group("txt")
                        if not txt.strip() or "{" in txt and "}" in txt and len(txt) < 3:
                            continue
                        rows.append({
                            "file": str(path.relative_to(FRONTEND)).replace("\\", "/"),
                            "line": i,
                            "kind": kind,
                            "text": txt,
                            "maybe_pt": looks_pt(txt),
                        })
    return rows


def main() -> None:
    rows = scan()
    out = FRONTEND / "scripts" / "i18n_inventory.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    uniq = {r["text"] for r in rows}
    pt = {r["text"] for r in rows if r["maybe_pt"]}
    print(f"Strings cruas encontradas: {len(rows)} (únicas: {len(uniq)})")
    print(f"Suspeitas de pt-BR vazando: {len(pt)}")
    for t in sorted(pt):
        print(f"  [PT?] {t}")
    print(f"\nInventário -> {out}")


if __name__ == "__main__":
    main()
