"""
Traduz as chaves NOVAS do i18n via xAI Grok (es + pt) e grava i18n_translations.json.

- Lê as chaves de scripts/i18n_keymap.json ("new": [{key, source, context}]).
- Manda tudo num único request ao Grok com contexto de domínio (junta de saneamiento, PY).
- Espera JSON estrito {key: {"es": ..., "pt": ...}} e valida contra as chaves pedidas.

A API key NÃO fica no código — vem de XAI_API_KEY no ambiente:
    XAI_API_KEY=... XAI_MODEL=grok-4.3 python scripts/i18n_grok_translate.py

(API xAI é compatível com o formato OpenAI chat/completions.)
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYMAP = HERE / "i18n_keymap.json"
OUT = HERE / "i18n_translations.json"

API_URL = os.environ.get("XAI_BASE", "https://api.x.ai/v1") + "/chat/completions"
MODEL = os.environ.get("XAI_MODEL", "grok-4.3")

SYSTEM = (
    "Sos un traductor especializado en software de gestión para juntas de saneamiento "
    "(agua potable) en Paraguay. La UI primaria es ESPAÑOL de Paraguay (es); también hay "
    "un catálogo en portugués de Brasil (pt) para uso interno. Traducís rótulos cortos de "
    "botones y encabezados de una app de escritorio. Reglas: mantené el registro corto y "
    "de interfaz (no frases); respetá mayúsculas de interfaz; español rioplatense/paraguayo "
    "neutro; NO inventes texto extra. Respondé EXCLUSIVAMENTE con JSON válido, sin markdown."
)


def build_user_prompt(items: list[dict]) -> str:
    lines = [
        "Traducí cada ítem a español (es) y portugués de Brasil (pt).",
        "El campo 'source' es la forma sugerida (puede estar ya en es); ajustala si hace falta.",
        "Devolvé un objeto JSON: { key: { \"es\": \"...\", \"pt\": \"...\" } } para TODAS las keys.",
        "",
        "Ítems:",
    ]
    for it in items:
        lines.append(
            f"- key={it['key']} | source={it['source']!r} | contexto={it['context']}"
        )
    return "\n".join(lines)


def call_grok(items: list[dict]) -> dict:
    key = os.environ.get("XAI_API_KEY")
    if not key:
        sys.exit("ERRO: defina XAI_API_KEY no ambiente (não hardcode a chave).")

    payload = {
        "model": MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_user_prompt(items)},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode("utf-8"))
    content = resp["choices"][0]["message"]["content"]
    return json.loads(content)


def main() -> None:
    keymap = json.loads(KEYMAP.read_text(encoding="utf-8"))
    items = keymap["new"]
    want = {it["key"] for it in items}

    trans = call_grok(items)

    missing = want - set(trans)
    if missing:
        sys.exit(f"ERRO: Grok não retornou {len(missing)} chaves: {sorted(missing)}")

    clean = {}
    for k in sorted(want):
        v = trans[k]
        clean[k] = {"es": v["es"].strip(), "pt": v["pt"].strip()}

    OUT.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK — {len(clean)} traduções -> {OUT}")
    for k, v in clean.items():
        print(f"  {k}: es={v['es']!r} pt={v['pt']!r}")


if __name__ == "__main__":
    main()
