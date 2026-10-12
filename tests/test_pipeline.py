import csv
import io
import os

import pytest
from fastapi.testclient import TestClient

from invoice_intake import db, synth
from invoice_intake.evaluate import evaluate
from invoice_intake.extract import extract_rules, parse_date
from invoice_intake.pipeline import process
from invoice_intake.schema import Invoice, LineItem
from invoice_intake.validate import validate


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("d") / "invoices"
    synth.generate(d, seed=7)
    return d


def test_generator_is_reproducible(tmp_path):
    a = synth.generate(tmp_path / "a" / "inv", seed=3)
    b = synth.generate(tmp_path / "b" / "inv", seed=3)
    assert a == b and len(a) >= 25


def test_parse_date_formats():
    assert str(parse_date("Date: 03/14/2025")) == "2025-03-14"
    assert str(parse_date("14 Mar 2025")) == "2025-03-14"


def test_rules_extracts_template_b():
    t = "Acme\nInv # AC-1001\nDate: 2025-01-02\n2 x Pen @ $1.50 = $3.00\nSub-total $3.00\nVAT 10% $0.30\nTOTAL $3.30"
    inv = extract_rules(t)
    assert inv.invoice_number == "AC-1001" and inv.total == 3.30 and inv.line_items[0].amount == 3.0


def test_validation_flags_math_and_vendor():
    inv = Invoice(vendor="X", invoice_number="1", invoice_date="2025-01-01", subtotal=10, tax=1, total=12,
                  line_items=[LineItem(description="a", amount=10)])
    codes = {i.code for i in validate(inv, "1 12.00", {"y"})}
    assert {"TOTAL_MISMATCH", "VENDOR_NOT_WHITELISTED"} <= codes


def test_no_false_approvals_and_all_injected_errors_caught(data):
    r = evaluate(str(data), "rules")
    assert r["false_approvals"] == 0
    assert r["injected_errors_caught"] == r["injected_errors"]
    assert r["precision"]["total"] >= 0.95


def test_duplicate_and_unreadable_routing(data):
    con = db.connect(":memory:")
    f = next(data.glob("*clean.pdf")).read_bytes()
    wl = {"x"}
    first = process(con, "a.pdf", f, "rules", wl)
    second = process(con, "b.pdf", f, "rules", wl)
    assert any(i.code == "DUPLICATE" for i in second["issues"]) and first["id"] != second["id"]
    bad = process(con, "scan.png", b"not an image", "rules", wl)
    assert bad["status"] == "review" and bad["issues"][0].code == "UNREADABLE"


def test_llm_failure_falls_back_to_rules(data, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "bad")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    con = db.connect(":memory:")
    r = process(con, "x.txt", next(data.glob("*.txt")).read_bytes(), "auto", set())
    assert r["extractor"] == "rules"


def test_api_flow_and_csv_only_contains_approved(data, monkeypatch, tmp_path):
    monkeypatch.setenv("INTAKE_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from invoice_intake import api

    api.con = db.connect(":memory:")
    c = TestClient(api.app)
    for f in sorted(data.glob("inv_*"))[:8]:
        assert c.post("/invoices?mode=rules", files={"file": (f.name, f.read_bytes())}).status_code == 200
    rows = list(csv.DictReader(io.StringIO(c.get("/export.csv").text)))
    approved = {x["invoice_number"] for x in c.get("/invoices?status=approved").json()}
    assert approved and {r["InvoiceNumber"] for r in rows} == approved


def test_ocr_scanned_inputs():
    pytest.importorskip("rapidocr_onnxruntime")
    from invoice_intake import scans

    r = scans.run(4, tmp := __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    assert r["total"] >= 3
