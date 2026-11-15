from __future__ import annotations

import io
import random
import re
import zipfile
from datetime import datetime

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..plans import MONEY_KEYS, SheetPlan, SheetRow, SOVPlan

HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")


def _money_cell(sheet: SheetPlan, v, rng: random.Random):
    if v is None or isinstance(v, str):
        return v, None
    shown = v / sheet.units
    shown = int(shown) if float(shown).is_integer() else round(shown, 1)
    if sheet.money_style == "number":
        return shown, "#,##0"
    style = rng.choice(["number", "commas", "symbol", "symbol"])
    if style == "number":
        return shown, "#,##0"
    if style == "commas":
        return f"{shown:,}", None
    return f"£{shown:,}" + (" " if rng.random() < 0.2 else ""), None


def _cell(sheet: SheetPlan, key: str, row: SheetRow, rng: random.Random):
    v = row.values.get(key)
    if key == "address" and v is None:
        vals = row.values
        return f"{vals['line1']}, {vals['town']} {vals['postcode']}", None
    if key in MONEY_KEYS:
        return _money_cell(sheet, v, rng)
    if key == "sprinklered" and isinstance(v, bool):
        return {"YN": ("Y", "N"), "yesno": ("Yes", "No"), "tick": ("✓", "✗")}[sheet.sprinkler_style][0 if v else 1], None
    if key == "year_built" and isinstance(v, int) and sheet.year_style == "circa" and rng.random() < 0.5:
        return f"c. {v}", None
    return v, None


def _totals(sheet: SheetPlan) -> dict:
    if isinstance(sheet.totals, dict):
        return sheet.totals
    out = {}
    for k in MONEY_KEYS:
        nums = [r.values.get(k) for r in sheet.rows if not r.hidden]
        if all(isinstance(n, int) for n in nums):
            out[k] = sum(nums)
        else:
            out[k] = sum(n for n in nums if isinstance(n, int))
    return out


def _write_sheet(ws, sheet: SheetPlan) -> None:
    rng = random.Random(sheet.seed)
    ncols = len(sheet.columns)
    r = 1
    for i, line in enumerate(sheet.title_lines):
        c = ws.cell(r, 1, line)
        c.font = Font(bold=i == 0, size=14 if i == 0 else 11)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        r += 1
    if sheet.title_lines:
        r += 1

    unit_note = " (£000)" if sheet.units == 1000 else ""
    if sheet.group_header:
        money_cols = [i for i, (k, _) in enumerate(sheet.columns, start=1) if k in MONEY_KEYS]
        if money_cols:
            ws.cell(r, money_cols[0], f"Sums Insured{unit_note or ' (£)'}").font = Font(bold=True)
            ws.cell(r, money_cols[0]).alignment = Alignment(horizontal="center")
            ws.merge_cells(start_row=r, start_column=money_cols[0], end_row=r, end_column=money_cols[-1])
            r += 1
    for ci, (key, header) in enumerate(sheet.columns, start=1):
        text = header + (unit_note if key in MONEY_KEYS and not sheet.group_header else "")
        cell = ws.cell(r, ci, text)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    r += 1

    for idx, row in enumerate(sheet.rows):
        if sheet.blank_row_every and idx and idx % sheet.blank_row_every == 0:
            r += 1
        for ci, (key, _) in enumerate(sheet.columns, start=1):
            value, fmt = _cell(sheet, key, row, rng)
            cell = ws.cell(r, ci, value)
            if fmt:
                cell.number_format = fmt
            if row.strike:
                cell.font = Font(strike=True, color="7F7F7F")
            if row.fill:
                cell.fill = PatternFill("solid", fgColor=row.fill)
        if row.note:
            ws.cell(r, 2).comment = Comment(row.note, "Finance")
        if row.hidden:
            ws.row_dimensions[r].hidden = True
        r += 1

    if sheet.totals is not None:
        totals = _totals(sheet)
        label_col = next(i for i, (k, _) in enumerate(sheet.columns, start=1) if k not in ("loc_no",))
        ws.cell(r, label_col, "TOTAL").font = Font(bold=True)
        for ci, (key, _) in enumerate(sheet.columns, start=1):
            if key in totals:
                shown = totals[key] / sheet.units
                c = ws.cell(r, ci, int(shown) if float(shown).is_integer() else round(shown, 1))
                c.number_format = "#,##0"
                c.font = Font(bold=True)

    for ci, (key, _) in enumerate(sheet.columns, start=1):
        width = {"line1": 34, "address": 52, "occupancy": 24, "construction": 28}.get(key, 14)
        ws.column_dimensions[get_column_letter(ci)].width = width


def _pin_timestamps(xlsx: bytes, when: datetime) -> bytes:
    """openpyxl stamps 'now' into the file; pin it so a seed always yields identical bytes."""
    stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>" + stamp.encode(), data)
            zi = zipfile.ZipInfo(info.filename, date_time=when.timetuple()[:6])
            zi.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(zi, data)
    return buf.getvalue()


def render_sov(plan: SOVPlan, when: datetime) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in plan.sheets:
        _write_sheet(wb.create_sheet(sheet.name), sheet)
    wb.active = plan.active_index
    for i, ws in enumerate(wb.worksheets):
        ws.sheet_view.tabSelected = i == plan.active_index
    buf = io.BytesIO()
    wb.save(buf)
    return _pin_timestamps(buf.getvalue(), when)
