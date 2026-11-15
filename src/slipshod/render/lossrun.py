from __future__ import annotations

import html
import io

import pymupdf as fitz

from ..plans import LossRunPlan, LossRunRow

CSS = """
body { font-family: sans-serif; font-size: 9px; }
h1 { font-size: 15px; margin: 0; }
h2 { font-size: 11px; margin-top: 14px; }
p { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin-top: 6px; }
th { background-color: #dde3ea; text-align: left; border: 1px solid #888; padding: 3px; }
td { border: 1px solid #888; padding: 3px; }
td.n { text-align: right; }
.small { font-size: 7px; color: #666; }
"""


def _rows(rows: list[LossRunRow]) -> str:
    out = []
    for r in rows:
        out.append(
            f"<tr><td>{html.escape(r.ref)}</td><td>{r.date_of_loss:%d/%m/%Y}</td><td>{html.escape(r.cause)}</td>"
            f"<td>{r.status.capitalize()}</td><td class='n'>{r.paid:,.2f}</td><td class='n'>{r.reserved:,.2f}</td>"
            f"<td class='n'>{r.paid + r.reserved:,.2f}</td></tr>"
        )
    return "".join(out)


HEAD = ("<tr><th>Claim No.</th><th>Date of Loss</th><th>Cause</th><th>Status</th>"
        "<th>Paid (£)</th><th>Outstanding (£)</th><th>Incurred (£)</th></tr>")


def render_lossrun(plan: LossRunPlan) -> bytes:
    e = html.escape
    parts = [
        f"<h1>{e(plan.insurer)}</h1>",
        "<p><b>Claims Experience Report</b></p>",
        f"<p>Insured: {e(plan.insured_name)}</p>",
        f"<p>Policy number: {e(plan.policy_ref)}</p>",
        f"<p>Period covered: {plan.period_from:%d/%m/%Y} to {plan.period_to:%d/%m/%Y}</p>",
        f"<p>Date produced: {plan.produced:%d/%m/%Y}</p>",
    ]
    if plan.open_summary:
        open_rows = [r for r in plan.rows if r.status == "open"]
        parts.append("<h2>Summary of outstanding claims</h2>")
        parts.append(f"<table>{HEAD}{_rows(open_rows)}</table>")
        parts.append("<h2>Full claims listing</h2>")
    if plan.rows:
        paid = sum(r.paid for r in plan.rows)
        res = sum(r.reserved for r in plan.rows)
        parts.append(
            f"<table>{HEAD}{_rows(plan.rows)}"
            f"<tr><td><b>Totals</b></td><td></td><td></td><td>{len(plan.rows)} claim(s)</td>"
            f"<td class='n'><b>{paid:,.2f}</b></td><td class='n'><b>{res:,.2f}</b></td>"
            f"<td class='n'><b>{paid + res:,.2f}</b></td></tr></table>"
        )
    else:
        parts.append("<p style='margin-top:12px'><b>No claims recorded for the period shown.</b></p>")
    parts.append(
        "<p class='small' style='margin-top:18px'>This report reflects information held at the date produced and "
        "is provided for the purpose of obtaining insurance only. Figures include VAT where applicable. "
        "Outstanding amounts are reserves and may change.</p>"
    )
    story = fitz.Story(html="".join(parts), user_css=CSS)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (40, 40, -40, -40)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()
