"""Reproducible SYNTHETIC invoice generator (fictional vendors). `python -m invoice_intake.synth`"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT = Path("data/invoices")
WHITELISTED = ["Northwind Office Supply", "Brightline Cleaning Co", "Cedar & Pine Printing", "Harbor Freight Logistics",
               "Summit IT Services", "Greenleaf Catering"]
UNKNOWN = ["Quickbuck Trading LLC", "Zenith Offshore Ltd"]
ITEMS = ["Printer paper (case)", "Toner cartridge", "Monthly cleaning service", "Business cards (500)", "Courier delivery",
         "Laptop repair", "Cloud backup plan", "Catering - team lunch", "Desk lamp", "Network cable 10m", "Whiteboard markers",
         "Consulting hour"]
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def build_doc(rng: random.Random, vendor: str, k: int) -> dict:
    n = rng.randint(1, 5)
    items = []
    for d in rng.sample(ITEMS, n):
        q, u = rng.randint(1, 12), round(rng.uniform(4, 180), 2)
        items.append({"description": d, "quantity": float(q), "unit_price": u, "amount": round(q * u, 2)})
    sub = round(sum(i["amount"] for i in items), 2)
    rate = rng.choice([0.0, 0.05, 0.08, 0.1])
    tax = round(sub * rate, 2)
    idate = date(2025, 1, 1) + timedelta(days=rng.randint(0, 330))
    return {"vendor": vendor, "invoice_number": f"{''.join(w[0] for w in vendor.split()[:3]).upper()}-{rng.randint(1000, 9999)}",
            "invoice_date": idate.isoformat(), "due_date": (idate + timedelta(days=30)).isoformat(), "currency": "USD",
            "line_items": items, "subtotal": sub, "tax": tax, "total": round(sub + tax, 2), "_rate": rate}


def fmt_date(iso: str, style: int) -> str:
    d = date.fromisoformat(iso)
    return [d.isoformat(), d.strftime("%m/%d/%Y"), f"{d.day} {MONTHS[d.month - 1]} {d.year}"][style]


def render_lines(t: dict, template: str, style: int) -> list[str]:
    m = lambda x: f"{x:,.2f}"
    num = f"{t['invoice_number']}" if t["invoice_number"] else None
    idt = fmt_date(t["invoice_date"], style) if t["invoice_date"] else None
    due = fmt_date(t["due_date"], style) if t["due_date"] else None
    pct = int(round(t["_rate"] * 100))
    if template == "A":
        L = [t["vendor"], "100 Example Street, Faketown (SYNTHETIC)", "INVOICE"]
        if num: L.append(f"Invoice No: {num}")
        if idt: L.append(f"Invoice Date: {idt}")
        L += [f"Due Date: {due}", "Bill To: Sample Client LLC", "", f"{'Description':<28}{'Qty':>5}{'Unit Price':>12}{'Amount':>12}"]
        L += [f"{i['description']:<26}  {i['quantity']:g}  {m(i['unit_price']):>10}  {m(i['amount']):>10}" for i in t["line_items"]]
        L += [f"Subtotal: ${m(t['subtotal'])}", f"Tax ({pct}%): ${m(t['tax'])}", f"Total Due: ${m(t['total'])}"]
    elif template == "B":
        L = [t["vendor"], "Receipt / Tax Invoice (SYNTHETIC)"]
        if num: L.append(f"Inv # {num}")
        if idt: L.append(f"Date: {idt}")
        L += [f"{i['quantity']:g} x {i['description']} @ ${m(i['unit_price'])} = ${m(i['amount'])}" for i in t["line_items"]]
        L += [f"Sub-total ${m(t['subtotal'])}", f"VAT {pct}% ${m(t['tax'])}", f"TOTAL ${m(t['total'])}"]
    else:  # C: emailed text
        L = [f"From: {t['vendor']} <billing@example.invalid>", "To: ap@sampleclient.invalid", f"Subject: Invoice {num or ''} from {t['vendor']}",
             "", "Hello, please find our invoice below (SYNTHETIC).", ""]
        if num: L.append(f"Invoice Number: {num}")
        if idt: L.append(f"Date: {idt}")
        L += [f"Payment due: {due}", "Items:"]
        L += [f"- {i['description']} ({i['quantity']:g} x {m(i['unit_price'])}) {m(i['amount'])}" for i in t["line_items"]]
        L += [f"Subtotal {m(t['subtotal'])}", f"Sales tax {m(t['tax'])}", f"Amount due {m(t['total'])}", "", "Thanks!"]
    return L


def add_noise(lines: list[str], rng: random.Random) -> list[str]:
    """OCR-style corruption: label confusions, stray marks, misread digit in one amount."""
    out = []
    for l in lines:
        l = l.replace("Invoice", "lnvoice") if rng.random() < .5 else l
        l = l.replace("Total", "Tota1") if rng.random() < .4 else l
        out.append(l)
        if rng.random() < .25:
            out.append("~~ scan 0%d ~~" % rng.randint(10, 99))
    i = rng.randrange(len(out))
    out[i] = out[i].replace("0", "O", 1) if any(c.isdigit() for c in out[i]) else out[i]
    return out


def write_pdf(path: Path, lines: list[str], noisy: bool):
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    y = 740
    for l in lines:
        c.setFont("Courier", 10)
        c.drawString(50 + (3 if noisy else 0), y, l)
        y -= 16
    c.save()


def generate(out: Path = OUT, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    plan = ["clean"] * 18 + ["noisy"] * 4 + ["total_mismatch"] * 3 + ["missing_number"] * 2 + ["missing_date"] + ["duplicate"] * 2 + ["unknown_vendor"] * 2
    rng.shuffle(plan)
    truths, made = [], []
    for k, kind in enumerate(plan, 1):
        if kind == "duplicate" and made:
            t = json.loads(json.dumps(rng.choice(made)))
        else:
            kind = "clean" if kind == "duplicate" else kind
            t = build_doc(rng, rng.choice(UNKNOWN if kind == "unknown_vendor" else WHITELISTED), k)
            if kind == "clean":
                made.append(json.loads(json.dumps(t)))
        issues = []
        if kind == "total_mismatch":
            t["total"] = round(t["total"] + rng.choice([5.0, 12.5, -7.25, 40.0]), 2)
            issues = ["TOTAL_MISMATCH"]
        elif kind == "missing_number":
            t["invoice_number"], issues = None, ["MISSING_FIELD"]
        elif kind == "missing_date":
            t["invoice_date"], issues = None, ["MISSING_FIELD"]
        elif kind == "duplicate":
            issues = ["DUPLICATE"]
        elif kind == "unknown_vendor":
            issues = ["VENDOR_NOT_WHITELISTED"]
        template = rng.choice("ABC")
        if template == "B":
            t["due_date"] = None  # receipts print no due date
        style = rng.randrange(3)
        lines = render_lines(t, template, style)
        noisy = kind == "noisy"
        if noisy:
            lines = add_noise(lines, rng)
        name = f"inv_{k:02d}_{kind}." + ("txt" if template == "C" else "pdf")
        if template == "C":
            (out / name).write_text("\n".join(lines))
        else:
            write_pdf(out / name, lines, noisy)
        truth = {k2: v for k2, v in t.items() if not k2.startswith("_")}
        truths.append({"file": name, "kind": kind, "expected_issues": issues,
                       "expected_route": "review" if issues else "approved", "truth": truth})
    (out / "ground_truth.json").write_text(json.dumps(truths, indent=1))
    (out.parent / "whitelist.txt").write_text("\n".join(WHITELISTED) + "\n")
    return truths


if __name__ == "__main__":
    t = generate(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 42)
    print(f"generated {len(t)} synthetic invoices in {OUT}")
