"""Field-level accuracy vs ground truth.  `python -m invoice_intake.evaluate [--mode rules|llm|auto]`"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import db
from .pipeline import process
from .validate import load_whitelist, norm

FIELDS = ["vendor", "invoice_number", "invoice_date", "due_date", "subtotal", "tax", "total"]


def _eq(f, a, b):
    if f == "vendor":
        return norm(a or "") == norm(b or "")
    return (str(a) if a is not None else None) == (str(b) if b is not None else None)


def _items(lst):
    return {(norm(i["description"]), float(i["quantity"]), round(float(i["amount"]), 2)) for i in lst}


def evaluate(data_dir="data/invoices", mode="rules", sleep=0.0):
    truths = json.loads((Path(data_dir) / "ground_truth.json").read_text())
    con = db.connect(":memory:")
    wl = load_whitelist(Path(data_dir).parent / "whitelist.txt")
    stat = {f: [0, 0, 0] for f in FIELDS + ["line_items"]}  # correct, predicted, truth-present
    route_ok = false_approve = approved = missed_issue = injected = 0
    used = {}
    for t in truths:
        r = process(con, t["file"], (Path(data_dir) / t["file"]).read_bytes(), "auto" if mode == "llm" else mode, wl)
        used[r["extractor"]] = used.get(r["extractor"], 0) + 1
        pred = json.loads(r["invoice"].model_dump_json())
        for f in FIELDS:
            tv, pv = t["truth"].get(f), pred.get(f)
            stat[f][1] += pv is not None
            stat[f][2] += tv is not None
            stat[f][0] += pv is not None and _eq(f, pv, tv)
        tp, pp = _items(t["truth"]["line_items"]), _items(pred["line_items"])
        stat["line_items"][0] += len(tp & pp); stat["line_items"][1] += len(pp); stat["line_items"][2] += len(tp)
        route_ok += r["status"] == t["expected_route"]
        if r["status"] == "approved":
            approved += 1
            false_approve += t["expected_route"] == "review"
        got = {i.code for i in r["issues"]}
        for code in t["expected_issues"]:
            injected += 1
            missed_issue += code not in got
        if sleep:
            time.sleep(sleep)
    n = len(truths)
    prec = {f: (c / p if p else 0.0) for f, (c, p, _) in stat.items()}
    rec = {f: (c / tr if tr else 1.0) for f, (c, _, tr) in stat.items()}
    return {"mode": mode, "extractors_used": used, "documents": n, "precision": prec, "recall": rec,
            "routing_accuracy": route_ok / n, "approved": approved, "false_approvals": false_approve,
            "injected_errors": injected, "injected_errors_caught": injected - missed_issue}


def markdown(results: list[dict]) -> str:
    rows = ["| Field | " + " | ".join(f"{r['mode']} P / R" for r in results) + " |", "|---|" + "---|" * len(results)]
    for f in FIELDS + ["line_items"]:
        rows.append(f"| {f} | " + " | ".join(f"{r['precision'][f]:.0%} / {r['recall'][f]:.0%}" for r in results) + " |")
    rows.append("| extractor used | " + " | ".join(", ".join(f"{k}: {v}" for k, v in r["extractors_used"].items()) for r in results) + " |")
    rows.append("| **routing accuracy** | " + " | ".join(f"{r['routing_accuracy']:.0%}" for r in results) + " |")
    rows.append("| **false approvals** | " + " | ".join(f"{r['false_approvals']} of {r['approved']} approved" for r in results) + " |")
    rows.append("| **injected errors caught** | " + " | ".join(f"{r['injected_errors_caught']} / {r['injected_errors']}" for r in results) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", nargs="+", default=["rules"])
    a = ap.parse_args()
    res = [evaluate(mode=m, sleep=2.0 if m == "llm" else 0) for m in a.mode]
    Path("reports").mkdir(exist_ok=True)
    Path("reports/accuracy.json").write_text(json.dumps(res, indent=1))
    Path("reports/accuracy.md").write_text(markdown(res) + "\n")
    print(markdown(res))
