"""
Importação em lote de clientes para a API a partir de um CSV exportado do Zoho
(Contactos.csv). Para cada linha, autentica no backend, extrai manzana/lote do
endereço e cria o cliente via POST /clients/.

Uso:
    python scripts/import_clientes.py <usuario> <senha> [caminho_do_csv]

- <usuario> / <senha>: credenciais de um usuário da org no backend.
- [caminho_do_csv]: opcional. Se omitido, usa a variável de ambiente
  IMPORT_CSV_PATH ou, por fim, "Contactos.csv" no diretório atual.
- A URL da API pode ser sobrescrita pela variável de ambiente API_URL
  (default: http://localhost:8000).
"""
import csv
import os
import re
import sys
import time
import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")
CSV_PATH = os.getenv("IMPORT_CSV_PATH", "Contactos.csv")

# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

def get_token(username: str, password: str) -> str:
    r = httpx.post(f"{API_URL}/auth/token", data={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]

# ------------------------------------------------------------------
# Parser manzana/lote
# ------------------------------------------------------------------

def parse_mz_lote(s2: str, notes: str = "") -> tuple[str, str]:
    """Extrai manzana e lote do Street2 (e Notes como fallback)."""
    for text in [s2, notes]:
        text = text.strip()
        if not text:
            continue

        # M39L7, M39L07, M2L9, M56L16
        m = re.search(r'M0*(\d+)\s*L0*(\d+)', text, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)

        # M14-02
        m = re.match(r'^M0*(\d+)-0*(\d+)$', text, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)

        # "Mazana 56 L01" ou "Manzana 56 L01"
        m = re.search(r'[Mm]an?z?ana\s+(\d+)\s+L\s*0*(\d+)', text, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)

        # M13L13 - CASA 01 (já capturado pelo primeiro, mas garante)
        m = re.search(r'M(\d+)L(\d+)', text, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)

    return "", ""


def clean_phone(p: str) -> str:
    p = p.strip().lstrip("+").replace("'", "")
    return p if p and p != "0000000000" else ""


def clean_ci(ci: str) -> str:
    return ci.strip()


def clean_name(name: str) -> str:
    # Remove prefixos de saudação
    name = re.sub(r'^(Sr\.|Sra\.|Dr\.|Dra\.)\s+', '', name.strip())
    return name


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Uso: python import_clientes.py <usuario> <senha> [caminho_do_csv]")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    csv_path = sys.argv[3] if len(sys.argv) > 3 else CSV_PATH

    print("Autenticando...")
    token = get_token(username, password)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    client = httpx.Client(timeout=30.0)

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Total de contatos: {len(rows)}")

    ok = 0
    skipped = 0
    errors = []

    for i, row in enumerate(rows):
        nome = clean_name(row["Display Name"])
        ci = clean_ci(row["CF.CI o RUC"])
        status_zoho = row["Status"]

        # Pula sem nome ou CI
        if not nome or len(nome) < 2:
            skipped += 1
            continue
        PLACEHOLDER_CIS = {"444444017", "444444444", "0000000000"}
        if not ci or len(ci) < 3 or ci in PLACEHOLDER_CIS:
            ci = f"SIN_CI_{i:04d}"

        mz, lt = parse_mz_lote(row["Billing Street2"], row["Notes"])

        phone = clean_phone(row["MobilePhone"] or row["Phone"] or row["Billing Phone"] or "")
        endereco = (row["Billing Address"] or row["Billing Attention"] or "SIN DIRECCIÓN").strip()
        if len(endereco) < 5:
            endereco = "SIN DIRECCIÓN"

        status = "INATIVO" if status_zoho == "Inactive" else "ATIVO"

        payload = {
            "nombre_completo": nome[:200],
            "ci_ruc": ci[:20],
            "celular": phone[:20] if phone else None,
            "direccion": endereco[:300],
            "manzana": mz,
            "lote": lt,
            "status": status,
        }

        for attempt in range(3):
            try:
                r = client.post(f"{API_URL}/clients/", json=payload, headers=headers)
                break
            except Exception as ex:
                if attempt == 2:
                    errors.append({"nome": nome, "ci": ci, "status": 0, "detail": str(ex)[:100]})
                    print(f"  [{i+1:03d}] ERR {nome[:40]} | conexão: {ex}")
                    r = None
                    break
                time.sleep(1)
        if r is None:
            continue

        if r.status_code == 201:
            ok += 1
            mz_label = f"M{mz}L{lt}" if mz else "sem lote"
            print(f"  [{i+1:03d}] OK  {nome[:40]} | CI:{ci} | {mz_label}")
        elif r.status_code == 400 and "ja cadastrado" in r.text:
            skipped += 1
            print(f"  [{i+1:03d}] DUP {nome[:40]} | CI:{ci} (já existe)")
        else:
            errors.append({"nome": nome, "ci": ci, "status": r.status_code, "detail": r.text[:100]})
            print(f"  [{i+1:03d}] ERR {nome[:40]} | {r.status_code}: {r.text[:80]}")

        time.sleep(0.05)

    print()
    print("=" * 60)
    print(f"Importados:  {ok}")
    print(f"Duplicados:  {skipped}")
    print(f"Erros:       {len(errors)}")
    if errors:
        print("\nErros detalhados:")
        for e in errors:
            print(f"  {e['nome']} | {e['ci']} | {e['status']}: {e['detail']}")


if __name__ == "__main__":
    main()
