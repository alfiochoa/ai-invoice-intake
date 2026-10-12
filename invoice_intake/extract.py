"""Extraction: text from file -> Invoice. LLM first, deterministic rules as fallback."""
from __future__ import annotations

import io
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .schema import Invoice, LineItem

MONEY = r"-?\$?\s?\d[\d,]*\.\d{2}"


class UnreadableDocument(Exception):
    pass


def ocr_image(data: bytes) -> str:
    """OCR backends tried in order: rapidocr (pip-only), pytesseract (needs the tesseract binary)."""
    errs = []
    try:
        from rapidocr_onnxruntime import RapidOCR

        res, _ = RapidOCR()(data)
        # regroup detected boxes into visual rows so table cells stay on one line
        boxes = sorted(((sum(pt[1] for pt in b) / 4, b[0][0], t) for b, t, _ in (res or [])))
        rows: list[list] = []
        for y, x, t in boxes:
            if rows and abs(y - rows[-1][0][0]) < 12:
                rows[-1].append((y, x, t))
            else:
                rows.append([(y, x, t)])
        return "\n".join("  ".join(t for _, _, t in sorted(r, key=lambda c: c[1])) for r in rows)
    except Exception as e:
        errs.append(type(e).__name__)
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception as e:
        errs.append(type(e).__name__)
    raise UnreadableDocument(f"image OCR unavailable ({', '.join(errs)})")


def read_text(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        pages = PdfReader(io.BytesIO(data)).pages
        text = "\n".join(p.extract_text() or "" for p in pages)
        if len(text.strip()) < 20:  # scanned PDF: OCR the embedded page images
            text = "\n".join(ocr_image(im.data) for p in pages for im in p.images)
    elif ext in {".txt", ".eml", ".md"}:
        text = data.decode("utf-8", errors="replace")
    elif ext in {".png", ".jpg", ".jpeg"}:
        text = ocr_image(data)
    else:
        raise UnreadableDocument(f"unsupported file type {ext!r}")
    if len(text.strip()) < 20:
        raise UnreadableDocument("no extractable text")
    return text


def money(s: str) -> float:
    return round(float(re.sub(r"[^\d.\-]", "", s)), 2)


def parse_date(s: str) -> Optional[date]:
    m = re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2} [A-Za-z]{3,9},? \d{4}|[A-Za-z]{3,9} \d{1,2},? \d{4}", s)
    if not m:
        return None
    tok = m.group(0).replace(",", "")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(tok, fmt).date()
        except ValueError:
            pass
    return None


def _last_money(line: str) -> Optional[float]:
    found = re.findall(MONEY, line)
    return money(found[-1]) if found else None


def extract_rules(text: str) -> Invoice:
    inv = Invoice()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for l in lines:
        if m := re.match(r"from:\s*(.+?)\s*(<.*)?$", l, re.I):
            inv.vendor = m.group(1)
            break
    if not inv.vendor and lines:
        inv.vendor = lines[0]
    if m := re.search(
        r"(?:invoice\s*(?:no\.?|number|#)|inv\s*#|inv\.?\s*no\.?)[ \t]*[:#]?[ \t]*([A-Z0-9][A-Z0-9\-/&]{2,})", text, re.I
    ):
        inv.invoice_number = m.group(1)
    for l in lines:
        if re.match(r"(invoice\s*)?date\b", l, re.I) and not inv.invoice_date:
            inv.invoice_date = parse_date(l)
        elif re.match(r"(due\s*date|payment\s*due|due)\b", l, re.I) and not inv.due_date:
            inv.due_date = parse_date(l)
        elif re.match(r"sub-?\s?total", l, re.I):
            inv.subtotal = _last_money(l)
        elif re.match(r"(sales\s+tax|vat|gst|tax)\b", l, re.I):
            inv.tax = _last_money(l)
        elif re.match(r"(grand\s+)?(total(\s*due)?|amount\s+due|balance\s+due)\b", l, re.I):
            inv.total = _last_money(l)
        elif m := re.match(rf"(.+?)\s{{2,}}(\d+(?:\.\d+)?)\s+\$?({MONEY})\s+\$?({MONEY})$", l):
            inv.line_items.append(LineItem(description=m[1], quantity=float(m[2]), unit_price=money(m[3]), amount=money(m[4])))
        elif m := re.match(rf"(\d+(?:\.\d+)?)\s*x\s+(.+?)\s*@\s*({MONEY})\s*=\s*({MONEY})$", l):
            inv.line_items.append(LineItem(description=m[2], quantity=float(m[1]), unit_price=money(m[3]), amount=money(m[4])))
        elif m := re.match(rf"[-*]\s*(.+?)\s*\((\d+(?:\.\d+)?)\s*x\s*({MONEY})\)\s*({MONEY})$", l):
            inv.line_items.append(LineItem(description=m[1], quantity=float(m[2]), unit_price=money(m[3]), amount=money(m[4])))
    return inv


PROMPT = (
    "Extract the vendor invoice below into JSON with exactly these keys: vendor, invoice_number, "
    "invoice_date (YYYY-MM-DD), due_date (YYYY-MM-DD), currency, line_items "
    "[{description, quantity, unit_price, amount}], subtotal, tax, total. "
    "Use null for anything not present in the text; never invent values. Numbers are plain numbers. "
    "Return only JSON.\n\n---\n"
)


def extract_llm(text: str) -> Invoice:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        timeout=30,
        max_retries=1,
    )
    resp = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "openai/gpt-oss-20b"),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": PROMPT + text[:6000]}],
    )
    return Invoice.model_validate(json.loads(resp.choices[0].message.content))


def extract(text: str, mode: str = "auto") -> tuple[Invoice, str]:
    """mode: auto (LLM, fall back to rules on any failure) | llm | rules."""
    if mode != "rules" and os.environ.get("LLM_API_KEY"):
        try:
            return extract_llm(text), "llm"
        except Exception:
            if mode == "llm":
                raise
    return extract_rules(text), "rules"
