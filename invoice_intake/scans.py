"""Make scan-like inputs (PNG + image-only PDF) from synthetic invoices and measure OCR extraction.
`python -m invoice_intake.scans`"""
from __future__ import annotations

import io
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from . import db
from .pipeline import process
from .synth import render_lines
from .validate import load_whitelist

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def to_image(lines: list[str], blur: float) -> Image.Image:
    f = ImageFont.truetype(FONT, 22)
    im = Image.new("L", (1100, 40 + 34 * len(lines)), 255)
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((30, 20 + 34 * i), l, font=f, fill=20)
    return im.rotate(0.6, fillcolor=255).filter(ImageFilter.GaussianBlur(blur))


def run(n: int = 6, out: Path = Path("data/scans")) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    truths = [t for t in json.loads(Path("data/invoices/ground_truth.json").read_text())
              if t["kind"] == "clean" and t["file"].endswith(".pdf")][:n]
    con, wl = db.connect(":memory:"), load_whitelist(Path("data/whitelist.txt"))
    ok = {"invoice_number": 0, "total": 0, "approved": 0}
    for k, t in enumerate(truths):
        tr = dict(t["truth"]); tr["_rate"] = 0
        pct = round(100 * tr["tax"] / tr["subtotal"]) if tr["subtotal"] else 0
        tr["_rate"] = pct / 100
        im = to_image(render_lines(tr, "A", 0), 0.6)
        if k % 2:  # image-only PDF
            name, buf = f"scan_{k}.pdf", io.BytesIO()
            c = canvas.Canvas(buf, pagesize=letter)
            c.drawImage(ImageReader(im.convert("RGB")), 20, 792 - 20 - 560 * im.height / im.width, width=560)
            c.save(); data = buf.getvalue()
        else:
            name, buf = f"scan_{k}.png", io.BytesIO(); im.save(buf, "PNG"); data = buf.getvalue()
        (out / name).write_bytes(data)
        r = process(con, name, data, "rules", wl)
        inv = r["invoice"]
        ok["invoice_number"] += inv.invoice_number == tr["invoice_number"]
        ok["total"] += inv.total == tr["total"]
        ok["approved"] += r["status"] == "approved"
    return {"scans": len(truths), **ok}


if __name__ == "__main__":
    print(run())
