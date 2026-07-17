"""
Importa o registro de RUC (arquivos DNIT `ruc*.txt`) para `wmapp_admin.ruc_registry`.

Formato de cada linha (pipe, UTF-8):  RUC|Nombre|DV|código|Estado|
Guardamos {ruc, nombre, dv, estado}. Store nacional (compartilhado entre orgs).

Estratégia: drop + insert_many em lotes (rápido p/ ~2M linhas) e recria o índice
único em `ruc` no final. Fase B vai versionar isso como "pacote MM/YYYY"; aqui é o
import direto dos arquivos atuais.

Uso:
    python scripts/import_ruc.py [diretorio_dos_ruc_txt]

Default do diretório: env RUC_DIR ou a pasta conhecida em Downloads.
Mongo: env MONGODB_URL ou mongodb://127.0.0.1:27017
"""
import glob
import os
import sys
import time

import pymongo

DEFAULT_DIR = r"C:/Users/stipp/Downloads/Faturamento ARQ/data/ruc"
BATCH = 50_000


def main():
    ruc_dir = sys.argv[1] if len(sys.argv) > 1 else os.getenv("RUC_DIR", DEFAULT_DIR)
    mongo_url = os.getenv("MONGODB_URL", "mongodb://127.0.0.1:27017")

    files = sorted(glob.glob(os.path.join(ruc_dir, "ruc*.txt")))
    if not files:
        print(f"Nenhum ruc*.txt em {ruc_dir}")
        sys.exit(1)
    print(f"Arquivos: {len(files)} em {ruc_dir}")

    coll = pymongo.MongoClient(mongo_url)["wmapp_admin"]["ruc_registry"]
    print("Limpando coleção anterior…")
    coll.drop()

    t0 = time.time()
    total = malformed = 0
    buf = []

    def flush():
        nonlocal buf
        if buf:
            coll.insert_many(buf, ordered=False)
            buf = []

    for path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("|")
                if len(parts) < 5 or not parts[0].strip():
                    malformed += 1
                    continue
                ruc = parts[0].strip()
                if not ruc.isdigit():
                    malformed += 1
                    continue
                buf.append({
                    "ruc": ruc,
                    "nombre": parts[1].strip(),
                    "dv": parts[2].strip(),
                    "estado": parts[4].strip().upper(),
                })
                total += 1
                if len(buf) >= BATCH:
                    flush()
        print(f"  {os.path.basename(path)} -> acumulado {total:,}")
    flush()

    print("Criando índice único em ruc…")
    coll.create_index("ruc", unique=True)

    print("=" * 50)
    print(f"Importados: {total:,} | malformados: {malformed:,} | {time.time()-t0:.1f}s")
    print("count na coleção:", coll.count_documents({}))
    # sanity: distribuição de estados (amostra)
    print("estados:", list(coll.aggregate([
        {"$group": {"_id": "$estado", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ])))


if __name__ == "__main__":
    main()
