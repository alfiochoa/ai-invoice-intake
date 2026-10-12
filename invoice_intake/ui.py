"""Streamlit review UI.  `streamlit run invoice_intake/ui.py`  (talks to the SQLite DB directly)"""
import json

import streamlit as st

from invoice_intake import db
from invoice_intake.pipeline import process, revalidate
from invoice_intake.schema import Invoice
from invoice_intake.validate import load_whitelist

st.set_page_config(page_title="Invoice Intake", layout="wide")
con = db.connect()
st.title("Invoice intake - review queue")

with st.sidebar:
    up = st.file_uploader("Upload invoices (PDF/TXT/image)", accept_multiple_files=True)
    mode = st.selectbox("Extractor", ["auto", "rules"])
    if up and st.button("Process"):
        for f in up:
            r = process(con, f.name, f.read(), mode)
            st.write(f"{f.name}: **{r['status']}** ({r['extractor']})")
    st.download_button("Download approved CSV", db.export_csv(con), "approved_invoices.csv", "text/csv")

rows = db.list_invoices(con)
c = st.columns(3)
for col, s in zip(c, ["approved", "review", "rejected"]):
    col.metric(s, sum(r["status"] == s for r in rows))

st.subheader("Needs review")
for r in [r for r in rows if r["status"] == "review"]:
    issues = json.loads(r["issues"])
    with st.expander(f"#{r['id']} {r['filename']} - {', '.join(i['code'] for i in issues)}"):
        for i in issues:
            st.warning(i["message"])
        edited = st.text_area("Extracted JSON (editable)", json.dumps(json.loads(r["data"]), indent=1), key=f"j{r['id']}", height=260)
        a, b = st.columns(2)
        if a.button("Approve", key=f"a{r['id']}"):
            try:
                inv = Invoice.model_validate_json(edited)
                iss, _ = revalidate(con, inv, "", load_whitelist(), r["sha256"], exclude_id=r["id"])
                hard = [i.message for i in iss if i.code in {"TOTAL_MISMATCH", "MISSING_FIELD"}]
                if hard:
                    st.error("Fix first: " + "; ".join(hard))
                else:
                    db.update(con, r["id"], inv, [], "approved"); st.rerun()
            except Exception as e:
                st.error(str(e))
        if b.button("Reject", key=f"r{r['id']}"):
            db.update(con, r["id"], Invoice.model_validate_json(r["data"]), [], "rejected"); st.rerun()

st.subheader("All invoices")
st.dataframe([{k: r[k] for k in ["id", "filename", "vendor", "invoice_number", "total", "status", "extractor"]} for r in rows])
