from __future__ import annotations

import hashlib

from . import db
from .extract import UnreadableDocument, extract, read_text
from .schema import Invoice, Issue
from .validate import load_whitelist, validate


def revalidate(con, inv: Invoice, text: str, whitelist, sha, exclude_id=None) -> tuple[list[Issue], str]:
    dup = db.find_duplicate(con, sha, inv.vendor, inv.invoice_number, str(inv.invoice_date or ""), inv.total, exclude_id)
    issues = validate(inv, text, whitelist, dup)
    return issues, ("review" if any(i.severity == "error" for i in issues) else "approved")


def process(con, filename: str, data: bytes, mode: str = "auto", whitelist=None) -> dict:
    """extract -> validate -> route (approved | review). Never raises on bad input."""
    whitelist = load_whitelist() if whitelist is None else whitelist
    sha = hashlib.sha256(data).hexdigest()
    try:
        text = read_text(filename, data)
    except UnreadableDocument as e:
        issues = [Issue(code="UNREADABLE", message=str(e))]
        id_ = db.insert(con, filename, sha, Invoice(), issues, "review", "none")
        return {"id": id_, "status": "review", "extractor": "none", "issues": issues, "invoice": Invoice()}
    inv, used = extract(text, mode)
    issues, status = revalidate(con, inv, text, whitelist, sha)
    id_ = db.insert(con, filename, sha, inv, issues, status, used)
    return {"id": id_, "status": status, "extractor": used, "issues": issues, "invoice": inv}
