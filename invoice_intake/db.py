from __future__ import annotations

import csv
import io
import json
import os
import sqlite3

from .validate import norm

DB_PATH = os.environ.get("INTAKE_DB", "data/intake.db")
SCHEMA = """CREATE TABLE IF NOT EXISTS invoices(
 id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, sha256 TEXT, vendor TEXT, invoice_number TEXT,
 invoice_date TEXT, total REAL, data TEXT, issues TEXT, status TEXT, extractor TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    if p != ":memory:":
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    con = sqlite3.connect(p, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def find_duplicate(con, sha, vendor, number, invoice_date, total, exclude_id=None) -> int | None:
    for r in con.execute("SELECT * FROM invoices WHERE status!='rejected' AND id IS NOT ?", (exclude_id,)):
        if r["sha256"] == sha:
            return r["id"]
        if vendor and norm(r["vendor"] or "") == norm(vendor):
            if number and r["invoice_number"] == number:
                return r["id"]
            if not number and total is not None and r["total"] == total and r["invoice_date"] == invoice_date:
                return r["id"]
    return None


def insert(con, filename, sha, inv, issues, status, extractor) -> int:
    cur = con.execute(
        "INSERT INTO invoices(filename,sha256,vendor,invoice_number,invoice_date,total,data,issues,status,extractor)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (filename, sha, inv.vendor, inv.invoice_number, str(inv.invoice_date or ""), inv.total,
         inv.model_dump_json(), json.dumps([i.model_dump() for i in issues]), status, extractor),
    )
    con.commit()
    return cur.lastrowid


def update(con, id_, inv, issues, status):
    con.execute(
        "UPDATE invoices SET vendor=?,invoice_number=?,invoice_date=?,total=?,data=?,issues=?,status=? WHERE id=?",
        (inv.vendor, inv.invoice_number, str(inv.invoice_date or ""), inv.total, inv.model_dump_json(),
         json.dumps([i.model_dump() for i in issues]), status, id_),
    )
    con.commit()


def get(con, id_):
    return con.execute("SELECT * FROM invoices WHERE id=?", (id_,)).fetchone()


def list_invoices(con, status=None):
    q, a = "SELECT * FROM invoices", ()
    if status:
        q, a = q + " WHERE status=?", (status,)
    return [dict(r) for r in con.execute(q + " ORDER BY id", a)]


COLS = ["ContactName", "InvoiceNumber", "InvoiceDate", "DueDate", "Description", "Quantity",
        "UnitAmount", "LineAmount", "TaxTotal", "InvoiceTotal", "Currency"]


def export_csv(con) -> str:
    """Accounting-import style CSV (one row per line item) of approved invoices only."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLS)
    for r in list_invoices(con, "approved"):
        d = json.loads(r["data"])
        for it in d["line_items"] or [{"description": "", "quantity": 1, "unit_price": d["total"], "amount": d["total"]}]:
            w.writerow([d["vendor"], d["invoice_number"], d["invoice_date"], d["due_date"] or "", it["description"],
                        it["quantity"], it["unit_price"] if it["unit_price"] is not None else it["amount"],
                        it["amount"], d["tax"] or 0, d["total"], d["currency"]])
    return buf.getvalue()
