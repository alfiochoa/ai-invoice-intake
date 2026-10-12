from __future__ import annotations

import os
from pathlib import Path

from .schema import Invoice, Issue

TOL = 0.02
WHITELIST_PATH = Path(os.environ.get("WHITELIST_PATH", "data/whitelist.txt"))
REQUIRED = ["vendor", "invoice_number", "invoice_date", "total"]


def load_whitelist(path: Path | None = None) -> set[str]:
    p = path or WHITELIST_PATH
    if not p.exists():
        return set()
    return {norm(l) for l in p.read_text().splitlines() if l.strip()}


def norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())  # OCR drops spaces/punctuation


def validate(inv: Invoice, text: str, whitelist: set[str], duplicate_of: int | None = None) -> list[Issue]:
    out: list[Issue] = []
    for f in REQUIRED:
        if not getattr(inv, f):
            out.append(Issue(code="MISSING_FIELD", message=f"missing {f}"))
    if not inv.line_items:
        out.append(Issue(code="NO_LINE_ITEMS", message="no line items extracted"))
    items = round(sum(i.amount for i in inv.line_items), 2)
    if inv.line_items and inv.subtotal is not None and abs(items - inv.subtotal) > TOL:
        out.append(Issue(code="TOTAL_MISMATCH", message=f"line items sum {items} != subtotal {inv.subtotal}"))
    if inv.total is not None and (inv.subtotal is not None or inv.line_items):
        base = inv.subtotal if inv.subtotal is not None else items
        expect = round(base + (inv.tax or 0), 2)
        if abs(expect - inv.total) > TOL:
            out.append(Issue(code="TOTAL_MISMATCH", message=f"subtotal+tax {expect} != total {inv.total}"))
    if inv.vendor and whitelist and norm(inv.vendor) not in whitelist:
        out.append(Issue(code="VENDOR_NOT_WHITELISTED", message=f"unknown vendor {inv.vendor!r}"))
    if inv.invoice_date and inv.due_date and inv.due_date < inv.invoice_date:
        out.append(Issue(code="DATE_ORDER", message="due date before invoice date"))
    if duplicate_of is not None:
        out.append(Issue(code="DUPLICATE", message=f"duplicate of record #{duplicate_of}"))
    # grounding guard: LLM values must literally appear in the source document
    flat = text.replace(",", "")
    if inv.invoice_number and inv.invoice_number not in text:
        out.append(Issue(code="UNGROUNDED_VALUE", message="invoice number not found in source text"))
    if inv.total is not None and f"{inv.total:.2f}" not in flat:
        out.append(Issue(code="UNGROUNDED_VALUE", message="total not found in source text"))
    return out
