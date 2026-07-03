"""
Genera muestras (samples) de TODOS los documentos PDF del sistema con datos
ficticios y los abre en Chrome.

Uso:
    python frontend/scripts/generate_pdf_samples.py

Salida: frontend/scripts/_pdf_samples/*.pdf
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta

# Permite importar el paquete `services` ejecutando desde cualquier lugar.
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, FRONTEND_DIR)

from services.pdf_generation.invoices import (  # noqa: E402
    InvoiceA4Generator, InvoiceP80Generator, BulkInvoiceA4Generator,
)
from services.pdf_generation.receipts import PaymentReceiptP80Generator  # noqa: E402
from services.pdf_generation.finance import (  # noqa: E402
    FinanceReportGenerator, EmployeePaymentGenerator, ExpenseReceiptGenerator,
)
from services.pdf_generation.notifications import (  # noqa: E402
    CutNoticeGenerator, ReactivationRequestGenerator,
)

OUT_DIR = os.path.join(os.path.dirname(__file__), "_pdf_samples")

# --------------------------------------------------------------------------
# Datos ficticios compartidos
# --------------------------------------------------------------------------
COMPANY = {
    "name": "Junta de Saneamiento Santa Rosa",
    "ruc": "80012345-6",
    "address": "Avda. Mariscal López 1234, Santa Rosa",
    "phone": "(0971) 555-123",
    "activity": "Provisión de agua potable",
}

CLIENT = {
    "name": "María Fernández de González",
    "ci_ruc": "3.456.789",
    "meter": "MED-00123",
    "address": "Manzana 5, Lote 12, Barrio San José",
    "manzana": "5",
    "lote": "12",
}

ITEMS = [
    {"descripcion": "Servicio de agua - consumo mensual", "cantidad": 1,
     "precio_unitario": 80000, "subtotal": 80000},
    {"descripcion": "Cargo fijo de mantenimiento", "cantidad": 1,
     "precio_unitario": 25000, "subtotal": 25000},
    {"descripcion": "Multa por mora", "cantidad": 1,
     "precio_unitario": 15000, "subtotal": 15000},
]

now = datetime.utcnow()


def invoice_payload() -> dict:
    return {
        "company": COMPANY,
        "client": CLIENT,
        "invoice": {
            "numero_factura": "001-001-0001234",
            "mes_referencia": 6,
            "ano_referencia": 2026,
            "fecha_emision": now,
            "fecha_vencimiento": now + timedelta(days=15),
            "status": "Pendiente",
            "items": ITEMS,
            "valor_total": 120000,
            "saldo_pendiente_anterior": 60000,
            "total_a_pagar": 180000,
        },
    }


def payment_result() -> dict:
    return {
        "company": COMPANY,
        "client_name": CLIENT["name"],
        "client_ci_ruc": CLIENT["ci_ruc"],
        "subsidio_aplicado": True,
        "total_subsidio": 30000,
        "sponsor_name": "Municipalidad de Santa Rosa",
        "payment": {
            "grupo_pagamento": "PAG-2026-000045",
            "fecha_pago": now,
            "metodo": "Efectivo",
            "valor_total": 150000,
        },
        "invoices_affected": [
            {"mes_referencia": 4, "ano_referencia": 2026, "valor_aplicado": 90000},
            {"mes_referencia": 5, "ano_referencia": 2026, "valor_aplicado": 60000},
        ],
    }


def finance_report() -> dict:
    return {
        "company": COMPANY,
        "period_label": "01/06/2026 a 30/06/2026",
        "summary": {"total_entradas": 4500000, "total_saidas": 1800000, "saldo_periodo": 2700000},
        "movements": [
            {"fecha": now - timedelta(days=i), "tipo": "Entrada" if i % 2 else "Salida",
             "categoria": "pago_factura" if i % 2 else "compra_material",
             "descripcion": f"Movimiento de ejemplo {i+1}", "valor": 50000 + i * 12000}
            for i in range(12)
        ],
    }


def employee_payment() -> dict:
    return {
        "company": COMPANY,
        "employee_name": "Carlos Benítez",
        "tesoureiro_nome": "Ana Riveros",
        "presidente_nome": "Jorge Cáceres",
        "mes_referencia": 6, "ano_referencia": 2026,
        "tipo": "Salario",
        "fecha_pago": now,
        "valor_base": 2500000, "descontos": 200000, "valor_liquido": 2300000,
    }


def expense_receipt() -> dict:
    return {
        "company": COMPANY,
        "proveedor_nombre": "Ferretería El Tornillo S.A.",
        "proveedor_ruc": "80098765-4",
        "numero_factura": "002-002-0009876",
        "categoria": "Material",
        "fecha_pago": now,
        "items": [
            {"descripcion": "Caño PVC 100mm", "cantidad": 10, "precio_unitario": 45000, "subtotal": 450000},
            {"descripcion": "Codo 90°", "cantidad": 20, "precio_unitario": 8000, "subtotal": 160000},
            {"descripcion": "Pegamento PVC", "cantidad": 5, "precio_unitario": 22000, "subtotal": 110000},
        ],
        "valor_total": 720000,
    }


def cut_notice() -> dict:
    return {
        "company": COMPANY,
        "title": "NOTIFICACIÓN DE CORTE DE SERVICIO",
        "client_name": "Pablina Galeano",
        "client_ci_ruc": "2602317",
        "client_phone": "0983709238",
        "client_address": CLIENT["address"],
        "client_manzana": CLIENT["manzana"], "client_lote": CLIENT["lote"],
        "total_due": 240000,
        "issue_date": now,
        "qr_url": "https://crm.juntasantarosa.com/corte/confirmar/abc123",
    }


def reactivation_request() -> dict:
    return {
        "company": COMPANY,
        "client_name": "Pablina Galeano",
        "client_ci_ruc": "2602317",
        "client_phone": "0983709238",
        "client_address": CLIENT["address"],
        "total_due": 240000,
        "reativation_fee": 50000,
        "paid_value": 290000,
        "payment_date": now,
        "notification_date": now - timedelta(days=20),
        "comprobante": "RC-2026-000128",
        "issue_date": now,
        "qr_url": "https://crm.juntasantarosa.com/reactivacion/confirmar/xyz789",
    }


DOCS = [
    ("01_factura_A4",          InvoiceA4Generator(),        invoice_payload()),
    ("02_factura_P80_ticket",  InvoiceP80Generator(),       invoice_payload()),
    ("03_facturas_lote_A4",    BulkInvoiceA4Generator(),    [invoice_payload() for _ in range(5)]),
    ("04_recibo_pago_P80",     PaymentReceiptP80Generator(), payment_result()),
    ("05_informe_financiero",  FinanceReportGenerator(),    finance_report()),
    ("06_pago_personal_A4",    EmployeePaymentGenerator(),  employee_payment()),
    ("07_comprobante_gasto",   ExpenseReceiptGenerator(),   expense_receipt()),
    ("08_aviso_corte",         CutNoticeGenerator(),        cut_notice()),
    ("09_orden_reactivacion",  ReactivationRequestGenerator(), reactivation_request()),
]


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = []
    for name, generator, data in DOCS:
        try:
            pdf_bytes = generator.generate(data)
            path = os.path.join(OUT_DIR, f"{name}.pdf")
            with open(path, "wb") as f:
                f.write(pdf_bytes)
            paths.append(path)
            print(f"[OK]   {name}.pdf  ({len(pdf_bytes):,} bytes)")
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {name}: {e.__class__.__name__}: {e}")

    print(f"\n{len(paths)} documentos generados en:\n  {OUT_DIR}\n")

    # Filtro opcional: `python generate_pdf_samples.py 08` abre só os que casam.
    filters = [a.lower() for a in sys.argv[1:]]
    if filters:
        to_open = [p for p in paths
                   if any(f in os.path.basename(p).lower() for f in filters)]
    else:
        to_open = paths
    open_in_chrome(to_open)


def open_in_chrome(paths: list[str]) -> None:
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome = next((p for p in candidates if os.path.exists(p)), None)
    urls = [f"file:///{p.replace(os.sep, '/')}" for p in paths]
    if chrome:
        subprocess.Popen([chrome] + urls)
        print("Abriendo en Chrome...")
    else:
        # Fallback: abridor por defecto del sistema
        for p in paths:
            os.startfile(p)  # type: ignore[attr-defined]
        print("Chrome no encontrado; abriendo con el visor por defecto.")


if __name__ == "__main__":
    main()
