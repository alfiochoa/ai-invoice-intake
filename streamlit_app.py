"""Streamlit Community Cloud entry point. Local: `streamlit run streamlit_app.py`.

Bridges st.secrets -> env vars (LLM_API_KEY / LLM_BASE_URL / LLM_MODEL), seeds the review queue with a few
synthetic invoices on first run (rules extractor, no LLM needed), then runs the review UI.
Without an LLM key the app uses the deterministic rule-based extractor.
"""
import os
import runpy
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)  # relative data/ paths

try:
    for _k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        if _k in st.secrets and _k not in os.environ:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # no secrets file: fine, rules-only mode
    pass

SEED = ["inv_02_clean.pdf", "inv_03_clean.pdf", "inv_04_clean.pdf", "inv_07_total_mismatch.txt",
        "inv_15_total_mismatch.pdf", "inv_17_unknown_vendor.pdf"]


@st.cache_resource
def seed_demo_data() -> int:
    from invoice_intake import db
    from invoice_intake.pipeline import process

    con = db.connect()
    if con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]:
        return 0
    for name in SEED:
        process(con, name, (ROOT / "data" / "invoices" / name).read_bytes(), "rules")
    return len(SEED)


seed_demo_data()
runpy.run_path(str(ROOT / "invoice_intake" / "ui.py"), run_name="__main__")
