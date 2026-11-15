"""A deliberately naive extractor: the kind of pipeline that demos well on clean documents.

It reads the text layer of PDFs, the active sheet of the workbook, and trusts
what it sees. It never raises flags. Use it as a floor, and as a template for
wiring in your own agent.

    slipshod baseline corpus/inputs preds/
    slipshod score corpus preds/
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
import pymupdf

FORM_LABELS = {
    "Name of proposer": "insured.name",
    "Trading address": "insured.address.line1",
    "Town": "insured.address.town",
    "Postcode": "insured.address.postcode",
    "Business description": "insured.trade",
    "Annual turnover (£)": "insured.annual_revenue",
    "Number of employees": "insured.employees",
    "From": "policy.inception_date",
    "To": "policy.expiry_date",
    "Approx. number of personal records held": "cyber.records_held",
    "Limit of indemnity required (£)": "cyber.limit_requested",
    "Estimated annual value in transit (£)": "cargo.annual_transit_value",
    "Maximum value any one conveyance (£)": "cargo.max_any_one_conveyance",
    "Commodities": "cargo.commodities",
    "Geographical limits": "cargo.geographical_limits",
    "Packaging": "cargo.packaging",
}
MONEY_PATHS = {"insured.annual_revenue", "insured.employees", "cyber.records_held", "cyber.limit_requested",
               "cargo.annual_transit_value", "cargo.max_any_one_conveyance"}
SOV_COLS = {
    "buildings": "buildings_sum_insured", "bldg": "buildings_sum_insured", "building": "buildings_sum_insured",
    "contents": "contents_sum_insured", "bi": "bi_sum_insured", "business interruption": "bi_sum_insured",
    "gross profit": "bi_sum_insured", "loss of revenue": "bi_sum_insured", "total": "total_sum_insured",
    "tiv": "total_sum_insured", "occupancy": "occupancy", "use": "occupancy", "trade": "occupancy",
    "construction": "construction", "constr": "construction", "wall": "construction", "year": "year_built",
    "built": "year_built", "sprinkler": "sprinklered", "postcode": "postcode", "post code": "postcode",
    "pc": "postcode", "town": "town", "city": "town", "address": "line1", "street": "line1",
}


def num(v):
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").replace("£", "").strip())
    except (TypeError, ValueError):
        return None


def iso(s: str):
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def put(obj: dict, path: str, value) -> None:
    *head, last = path.split(".")
    for k in head:
        obj = obj.setdefault(k, {})
    obj[last] = value


def read_form(doc: pymupdf.Document, out: dict) -> None:
    lines = [ln.strip() for page in doc for ln in page.get_text().splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:-1]):
        path = FORM_LABELS.get(ln)
        if not path or lines[i + 1] in FORM_LABELS:
            continue
        v = lines[i + 1]
        if path in MONEY_PATHS:
            v = num(v)
        elif path.startswith("policy."):
            v = iso(v)
        put(out, path, v)


def read_lossrun(doc: pymupdf.Document) -> list[dict]:
    text = "\n".join(page.get_text() for page in doc)
    insurer = text.strip().splitlines()[0] if text.strip() else None
    row = re.compile(r"([A-Z]{2,}/\d{2}/\d{6})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(Open|Closed)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)")
    return [{"date_of_loss": iso(m[2]), "cause": m[3], "status": m[4].lower(), "paid": num(m[5]),
             "reserved": num(m[6]), "insurer": insurer} for m in row.finditer(text)]


def read_sov(path: Path) -> list[dict]:
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    cols = {}
    for ci, h in enumerate(rows[0]):
        h = str(h or "").lower()
        for key, field in SOV_COLS.items():
            if key in h and field not in cols.values():
                cols[ci] = field
                break
    locs = []
    for r in rows[1:]:
        if not r or r[0] is None:
            continue
        loc = {"address": {}}
        for ci, field in cols.items():
            v = r[ci] if ci < len(r) else None
            if field in ("line1", "town", "postcode"):
                loc["address"][field] = v
            elif field.endswith("sum_insured"):
                loc[field] = num(v)
            elif field == "sprinklered":
                loc[field] = str(v).strip().upper().startswith("Y")
            elif field == "year_built":
                loc[field] = int(v) if isinstance(v, (int, float)) else None
            else:
                loc[field] = v
        locs.append(loc)
    return locs


def extract(sub_dir: Path) -> dict:
    out: dict = {"submission_id": sub_dir.name, "claims": [], "flags": []}
    att = sub_dir / "attachments"
    files = sorted(att.iterdir()) if att.exists() else []
    for f in files:
        if f.suffix == ".pdf":
            doc = pymupdf.open(f)
            text = doc[0].get_text()
            if "Claims Experience Report" in text:
                out["claims"] += read_lossrun(doc)
            elif "Proposal Form" in text:
                read_form(doc, out)
                out["line_of_business"] = ("cyber" if "Cyber" in text else "cargo" if "Cargo" in text else "property")
        elif f.suffix == ".xlsx":
            locs = read_sov(f)
            out["property"] = {"locations": locs, "total_tiv": sum(l.get("total_sum_insured") or 0 for l in locs)}
    out.setdefault("policy", {})["currency"] = "GBP"
    return out


def run(inputs: Path, preds: Path) -> int:
    inputs, preds = Path(inputs), Path(preds)
    preds.mkdir(parents=True, exist_ok=True)
    n = 0
    for sub in sorted(p for p in inputs.iterdir() if p.is_dir()):
        (preds / f"{sub.name}.json").write_text(json.dumps(extract(sub), indent=2, default=str))
        n += 1
    return n


if __name__ == "__main__":
    print(f"wrote {run(Path(sys.argv[1]), Path(sys.argv[2]))} predictions")
