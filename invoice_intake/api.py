from __future__ import annotations

import json

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from . import db
from .pipeline import revalidate
from .schema import Invoice
from .validate import load_whitelist

app = FastAPI(title="AI Invoice Intake")
con = db.connect()


@app.post("/invoices")
async def upload(file: UploadFile = File(...), mode: str = "auto"):
    from .pipeline import process

    r = process(con, file.filename, await file.read(), mode)
    return {"id": r["id"], "status": r["status"], "extractor": r["extractor"],
            "issues": [i.model_dump() for i in r["issues"]], "invoice": json.loads(r["invoice"].model_dump_json())}


@app.get("/invoices")
def list_(status: str | None = None):
    return db.list_invoices(con, status)


@app.post("/invoices/{id_}/review")
def review(id_: int, action: str = Body(...), invoice: Invoice | None = Body(None)):
    """Human decision: action=approve (optionally with corrected invoice) | reject."""
    row = db.get(con, id_)
    if not row:
        raise HTTPException(404, "not found")
    inv = invoice or Invoice.model_validate_json(row["data"])
    if action == "reject":
        db.update(con, id_, inv, [], "rejected")
    elif action == "approve":
        # a human approval overrides review-only issues, but corrected data is still re-checked for math
        issues, _ = revalidate(con, inv, "", load_whitelist(), row["sha256"], exclude_id=id_)
        hard = [i for i in issues if i.code in {"TOTAL_MISMATCH", "MISSING_FIELD"}]
        if hard:
            raise HTTPException(422, [i.model_dump() for i in hard])
        db.update(con, id_, inv, [], "approved")
    else:
        raise HTTPException(400, "action must be approve|reject")
    return {"id": id_, "status": db.get(con, id_)["status"]}


@app.get("/export.csv", response_class=PlainTextResponse)
def export():
    return db.export_csv(con)
