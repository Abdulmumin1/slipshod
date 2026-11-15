"""The defect catalogue.

Each defect edits the document plans to reproduce one kind of real-world mess,
and records exactly what it did: which answer fields it puts at risk ("checks"),
whether the true value is still recoverable from the documents, and what a
careful broker should raise ("flag").

Invariant: after all defects run, every non-null value in the answer key can be
derived from the documents, and every null is genuinely unknowable from them.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

from .model import Claim, Risk
from .plans import (
    MONEY_KEYS, Doc, EmailPlan, FormPlan, LossRunPlan, LossRunRow, SheetRow, SOVPlan,
    long_date, lossrun_row, money,
)
from .truth import add_years, round_to

LOC_MONEY = ("buildings_sum_insured", "contents_sum_insured", "bi_sum_insured", "total_sum_insured")
SOV_TO_ANSWER = {"buildings": "buildings_sum_insured", "contents": "contents_sum_insured",
                 "bi": "bi_sum_insured", "total": "total_sum_insured"}
LOCS = "property.locations#set"
CLAIMS = "claims#set"


@dataclass
class Defect:
    code: str
    description: str
    doc: str
    checks: list[str]
    flag: dict | None = None
    resolvable: bool = True

    def to_json(self) -> dict:
        return {"code": self.code, "doc": self.doc, "description": self.description,
                "resolvable": self.resolvable, "checks": self.checks, "expected_flag": self.flag}


@dataclass
class Ctx:
    risk: Risk
    rng: random.Random
    docs: dict[str, Doc]
    emails: list[EmailPlan]
    withheld: set[str] = field(default_factory=set)
    overrides: dict[str, object] = field(default_factory=dict)
    unscored: set[str] = field(default_factory=set)
    hidden_claims: set[str] = field(default_factory=set)
    claims_unknown: bool = False
    touched: set[str] = field(default_factory=set)
    flags: list[dict] = field(default_factory=list)

    @property
    def sov(self) -> SOVPlan | None:
        d = self.docs.get("sov")
        return d.plan if d else None

    @property
    def form(self) -> FormPlan:
        return self.docs["form"].plan

    @property
    def main_email(self) -> EmailPlan:
        return self.emails[0]

    def lossrun_docs(self) -> list[Doc]:
        return [d for k, d in self.docs.items() if k.startswith("lossrun:") and k != "lossrun:sister"]

    def loc_path(self, loc_id: str, fld: str | None = None) -> str:
        pc = self.risk.location(loc_id).address.postcode
        base = f"property.locations[{pc}]"
        return f"{base}.{fld}" if fld else base

    def all_loc_paths(self, fields) -> list[str]:
        return [self.loc_path(loc.id, f) for loc in self.risk.locations for f in fields]

    def form_paths(self) -> list[str]:
        paths = [f.path for s in self.form.sections for f in s.fields if f.path and f.path != "claims_declared"]
        return paths + ["proposal_form.signed_date"]

    def visible_claims(self) -> list[Claim]:
        return [c for c in self.risk.claims if c.ref not in self.hidden_claims]

    def flag(self, type_: str, path: str, note: str) -> dict:
        f = {"type": type_, "field": path, "note": note}
        self.flags.append(f)
        return f

    def add_paragraph(self, text: str) -> None:
        paras = self.main_email.paragraphs
        paras.insert(len(paras) - 1, text)


# ======================================================================== spreadsheet: layout


def sov_title_block(ctx: Ctx) -> Defect:
    """Title rows, merged group header and blank spacer rows above/inside the table."""
    r = ctx.risk
    for sheet in ctx.sov.sheets:
        sheet.title_lines = [r.insured.name.upper(), "Schedule of Values / Statement of Fact",
                             f"Renewal date: {r.inception:%d/%m/%Y}   Prepared by: {r.contact.name}"]
        sheet.group_header = True
        sheet.blank_row_every = ctx.rng.choice([2, 3])
    return Defect("sov.title_block", "Title rows, a merged 'Sums Insured' group header, and blank spacer rows "
                  "push the real header down and break naive table parsing.", "sov", [LOCS])


def sov_single_address_column(ctx: Ctx) -> Defect:
    """Street, town and postcode crammed into one cell."""
    for sheet in ctx.sov.sheets:
        cols = [c for c in sheet.columns if c[0] not in ("town", "postcode")]
        sheet.columns = [("address", ctx.rng.choice(["Address", "Site Address", "Premises"])) if k == "line1" else (k, h)
                         for k, h in cols]
    return Defect("sov.single_address_column", "Street, town and postcode are crammed into one 'Address' cell.",
                  "sov", ctx.all_loc_paths(["address.line1", "address.town", "address.postcode"]))


def sov_units_thousands(ctx: Ctx) -> Defect:
    """Sums insured in £000s, signalled only by the header."""
    for sheet in ctx.sov.sheets:
        sheet.units = 1000
    return Defect("sov.units_thousands", "Sums insured are stated in thousands; the only hint is '(£000)' in the header.",
                  "sov", ctx.all_loc_paths(LOC_MONEY) + ["property.total_tiv"])


def sov_money_as_text(ctx: Ctx) -> Defect:
    """Money cells mix numbers and text ('£1,250,000 ')."""
    for sheet in ctx.sov.sheets:
        sheet.money_style = "mixed_text"
    return Defect("sov.money_as_text", "Money cells are a mix of numbers and text like '£1,250,000' and '1,250,000 '.",
                  "sov", ctx.all_loc_paths(LOC_MONEY))


def sov_mixed_notation(ctx: Ctx) -> Defect:
    """Sprinklers as ticks/crosses; build years like 'c. 1965'."""
    for sheet in ctx.sov.sheets:
        sheet.sprinkler_style = ctx.rng.choice(["tick", "yesno"])
        sheet.year_style = "circa"
    return Defect("sov.mixed_notation", "Sprinklers marked with ticks/crosses; some build years written 'c. 1965'.",
                  "sov", ctx.all_loc_paths(["sprinklered", "year_built"]))


# ======================================================================== spreadsheet: content


def sov_stale_tab(ctx: Ctx) -> Defect:
    """Workbook opens on last year's tab; the current schedule is the second tab."""
    sov = ctx.sov
    current = sov.sheets[0]
    stale = copy.deepcopy(current)
    prior_year = ctx.risk.inception.year - 1
    stale.name = f"{prior_year} renewal"
    stale.seed += 1
    for row in stale.rows:
        for k in ("buildings", "contents", "bi"):
            if isinstance(row.values.get(k), int) and row.values[k]:
                row.values[k] = round_to(row.values[k] * ctx.rng.uniform(0.82, 0.95), 5_000)
        if all(isinstance(row.values.get(k), int) for k in ("buildings", "contents", "bi")):
            row.values["total"] = row.values["buildings"] + row.values["contents"] + row.values["bi"]
    if len(stale.rows) > 1 and ctx.rng.random() < 0.5:
        stale.rows.pop()
    if not current.name[:4].isdigit() or current.name == stale.name:
        current.name = f"{ctx.risk.inception.year} renewal"
    sov.sheets = [stale, current]
    sov.active_index = 0
    return Defect("sov.stale_tab", f"The workbook opens on last year's tab ('{stale.name}'); the current schedule "
                  f"is on the second tab ('{current.name}').", "sov", [LOCS] + ctx.all_loc_paths(LOC_MONEY))


def _current_sheet(ctx: Ctx):
    return ctx.sov.sheets[-1]


def _loc_rows(ctx: Ctx, loc_id: str, all_sheets: bool = False) -> list[SheetRow]:
    sheets = ctx.sov.sheets if all_sheets else [_current_sheet(ctx)]
    return [r for sh in sheets for r in sh.rows if r.location_id == loc_id]


def sov_disposed_location(ctx: Ctx) -> Defect:
    """A sold site lingers as a hidden, struck-through row."""
    from .truth import make_address
    from . import refdata as R

    sheet = _current_sheet(ctx)
    used = {loc.address.postcode for loc in ctx.risk.locations}
    addr = make_address(ctx.rng, used, True, ctx.rng.choice(R.TOWNS))
    b, c = round_to(ctx.rng.uniform(300_000, 2_000_000), 5_000), round_to(ctx.rng.uniform(50_000, 500_000), 5_000)
    row = SheetRow(values={
        "loc_no": len(sheet.rows) + 1, "line1": addr.line1, "town": addr.town, "postcode": addr.postcode,
        "occupancy": "Warehouse", "construction": "Steel frame, composite panel", "year_built": 1988,
        "sprinklered": False, "buildings": b, "contents": c, "bi": 0, "total": b + c,
    }, hidden=True, strike=True, note=f"SOLD {ctx.risk.as_of.year} - remove from cover")
    sheet.rows.insert(ctx.rng.randint(0, len(sheet.rows)), row)
    return Defect("sov.disposed_location", f"A sold site ({addr.postcode}) is still in the schedule as a hidden, "
                  "struck-through row with a 'SOLD' cell comment.", "sov", [LOCS])


def sov_duplicate_row(ctx: Ctx) -> Defect:
    """One location listed twice; totals double-count it."""
    sheet = _current_sheet(ctx)
    real = [r for r in sheet.rows if r.location_id]
    src = ctx.rng.choice(real)
    dup = copy.deepcopy(src)
    if isinstance(dup.values.get("line1"), str):
        dup.values["line1"] = dup.values["line1"].upper()
    dup.fill = "FFF2CC"
    sheet.rows.append(dup)
    return Defect("sov.duplicate_row", f"Location {ctx.risk.location(src.location_id).address.postcode} is listed "
                  "twice (second copy in capitals, highlighted). The totals row double-counts it.", "sov", [LOCS])


def sov_combined_values(ctx: Ctx) -> Defect | None:
    """Buildings + contents given as one figure: split unknowable, flag it."""
    sheet = _current_sheet(ctx)
    cands = [r for r in sheet.rows if r.location_id
             and not ({ctx.loc_path(r.location_id, "buildings_sum_insured"), ctx.loc_path(r.location_id, "contents_sum_insured")} & ctx.touched)]
    if not cands:
        return None
    row = ctx.rng.choice(cands)
    loc = ctx.risk.location(row.location_id)
    combined = (loc.buildings + loc.contents) // sheet.units
    for r in _loc_rows(ctx, loc.id):
        r.values["buildings"] = f"{combined:,} (bldgs & contents)"
        r.values["contents"] = "incl."
    paths = [ctx.loc_path(loc.id, "buildings_sum_insured"), ctx.loc_path(loc.id, "contents_sum_insured")]
    ctx.withheld.update(paths)
    ctx.touched.update(paths)
    f = ctx.flag("missing", ctx.loc_path(loc.id), "Buildings and contents given as a single combined figure; need the split.")
    return Defect("sov.combined_values", f"Buildings and contents for {loc.address.postcode} are given as one combined "
                  "figure. The split is unknowable; total is still known.", "sov",
                  paths + [ctx.loc_path(loc.id, "total_sum_insured")], f)


def sov_missing_construction(ctx: Ctx) -> Defect:
    """Construction blank or 'TBC' for a site: flag it."""
    sheet = _current_sheet(ctx)
    row = ctx.rng.choice([r for r in sheet.rows if r.location_id])
    loc = ctx.risk.location(row.location_id)
    blank = ctx.rng.choice([None, "TBC", "?"])
    for r in _loc_rows(ctx, loc.id, all_sheets=True):
        r.values["construction"] = blank
    path = ctx.loc_path(loc.id, "construction")
    ctx.withheld.add(path)
    ctx.touched.add(path)
    f = ctx.flag("missing", path, "Construction not provided.")
    return Defect("sov.missing_construction", f"Construction for {loc.address.postcode} is blank/'TBC'.", "sov", [path], f)


def sov_wrong_total(ctx: Ctx) -> Defect:
    """TOTAL row is a stale hard-coded number: flag the conflict."""
    sheet = _current_sheet(ctx)
    real_total = sum(loc.total for loc in ctx.risk.locations)
    sheet.totals = {"total": real_total + ctx.rng.choice([-1, 1]) * round_to(real_total * ctx.rng.uniform(0.04, 0.15), 5_000)}
    f = ctx.flag("conflict", "property.total_tiv", "Totals row does not equal the sum of the locations.")
    return Defect("sov.wrong_total", "The TOTAL row has a stale hard-coded figure that doesn't match the rows above.",
                  "sov", ["property.total_tiv"], f)


def email_sov_correction(ctx: Ctx) -> Defect | None:
    """Follow-up email corrects a schedule figure; the correction wins."""
    sheet = _current_sheet(ctx)
    cands = [r for r in sheet.rows if r.location_id and isinstance(r.values.get("buildings"), int)
             and ctx.loc_path(r.location_id, "buildings_sum_insured") not in ctx.touched]
    if not cands:
        return None
    row = ctx.rng.choice(cands)
    loc = ctx.risk.location(row.location_id)
    wrong = loc.buildings
    while wrong == loc.buildings:
        wrong = round_to(loc.buildings * ctx.rng.uniform(0.75, 0.92), 5_000)
    for r in sheet.rows:
        if r.location_id == loc.id:
            r.values["buildings"] = wrong
            r.values["total"] = wrong + loc.contents + loc.bi
    main = ctx.main_email
    c, b = ctx.risk.contact, ctx.risk.broker
    where = loc.address.line1.split(",")[-1].strip() if "," in loc.address.line1 else f"{loc.address.town} site"
    body = ctx.rng.choice([
        f"Sorry {b.first}, just spotted the buildings figure for {where} ({loc.address.postcode}) on the schedule "
        f"is last year's. It should be {money(loc.buildings, 'short')} not {money(wrong, 'short')}. Everything else is right.",
        f"{b.first} - correction to the schedule I sent this morning. {loc.address.town}, {loc.address.postcode}: "
        f"buildings sum insured needs to be {money(loc.buildings, 'symbol')} (we had the revaluation done). "
        "Can you update before it goes out?",
    ])
    ctx.emails.append(EmailPlan(
        filename="02_re_" + main.filename[3:], sender=main.sender, to=main.to,
        sent=main.sent + timedelta(hours=ctx.rng.randint(1, 30), minutes=ctx.rng.randint(1, 50)),
        subject=main.subject if main.subject.upper().startswith("RE:") else f"RE: {main.subject}",
        paragraphs=[body, "Thanks"], attachments=[], quoted=[{
            "from": main.sender, "sent": main.sent, "subject": main.subject, "style": "outlook",
            "body": "(original message with attachments)",
        }], signature=[c.first],
    ))
    paths = [ctx.loc_path(loc.id, "buildings_sum_insured"), ctx.loc_path(loc.id, "total_sum_insured"), "property.total_tiv"]
    ctx.touched.update(paths[:1])
    return Defect("email.sov_correction", f"A follow-up email corrects the buildings figure for {loc.address.postcode} "
                  f"({money(wrong, 'symbol')} in the schedule -> {money(loc.buildings, 'symbol')}).",
                  ctx.emails[-1].filename, paths)


# ======================================================================== proposal form


def form_fillable(ctx: Ctx) -> Defect:
    """Answers stored in AcroForm fields, invisible to plain text extraction."""
    ctx.form.fillable = True
    return Defect("form.fillable_fields", "Answers live in PDF form fields (AcroForm widgets), not in the page text; "
                  "plain text extraction returns an empty form.", "form", ctx.form_paths())


def form_handwritten(ctx: Ctx) -> Defect:
    """Form completed by hand in blue ink."""
    ctx.form.handwritten = True
    return Defect("form.handwritten", "Form completed by hand in blue ink, partly in block capitals.", "form", ctx.form_paths())


def form_scanned(ctx: Ctx) -> Defect:
    """Form printed and scanned: skewed, noisy image, no text layer."""
    ctx.form.degrade = "scan"
    return Defect("form.scanned", "Form printed, signed and scanned: skewed, noisy, low-res image with no text layer.",
                  "form", ctx.form_paths())


def _pick_form_path(ctx: Ctx, candidates: list[str]) -> str | None:
    opts = [p for p in candidates if ctx.form.has(p) and p not in ctx.touched]
    return ctx.rng.choice(opts) if opts else None


def form_crossed_out(ctx: Ctx) -> Defect | None:
    """A value crossed out with the replacement written beside it."""
    r = ctx.risk
    cands = ["insured.employees"]
    if r.cyber:
        cands += ["cyber.limit_requested", "cyber.records_held"]
    if r.cargo:
        cands += ["cargo.annual_transit_value", "cargo.max_any_one_conveyance"]
    path = _pick_form_path(ctx, cands)
    if not path:
        return None
    f = ctx.form.field(path)
    if path == "insured.employees":
        f.correction = str(r.insured.prior_employees)
    else:
        true = int(f.value.replace(",", ""))
        old = round_to(true * ctx.rng.choice([0.5, 0.8, 1.25, 2.0]), 5_000)
        f.correction = money(old if old != true else true + 50_000, "commas")
    ctx.touched.add(path)
    return Defect("form.crossed_out_correction", f"'{f.label}' has a value crossed out ({f.correction}) with the "
                  f"replacement handwritten beside it ({f.value}).", "form", [path])


def form_blank_field(ctx: Ctx) -> Defect | None:
    """A required answer left blank and stated nowhere else: flag it."""
    r = ctx.risk
    cands = ["insured.employees"]
    if r.cyber:
        cands += ["cyber.records_held"]
    if r.cargo:
        cands += ["cargo.packaging", "cargo.max_any_one_conveyance"]
    path = _pick_form_path(ctx, cands)
    if not path:
        return None
    f = ctx.form.field(path)
    f.value = None
    ctx.withheld.add(path)
    ctx.touched.add(path)
    flag = ctx.flag("missing", path, f"'{f.label}' left blank on the proposal form.")
    return Defect("form.blank_field", f"'{f.label}' was left blank and is not stated anywhere else.", "form", [path], flag)


def form_double_ticked(ctx: Ctx) -> Defect | None:
    """Both Yes and No ticked: unresolvable, flag it."""
    cands = [f.path for s in ctx.form.sections for f in s.fields
             if f.kind == "choice" and f.path and f.path.startswith("cyber.") and f.path not in ctx.touched]
    if not cands:
        return None
    path = ctx.rng.choice(cands)
    f = ctx.form.field(path)
    f.ticked = set(f.options)
    ctx.unscored.add(path)
    ctx.touched.add(path)
    flag = ctx.flag("conflict", path, f"Both Yes and No ticked for '{f.label}'.")
    return Defect("form.double_ticked", f"Both 'Yes' and 'No' are ticked for '{f.label}'.", "form", [path], flag, resolvable=False)


def form_unsigned(ctx: Ctx) -> Defect:
    """Form unsigned and undated though the email says signed: flag it."""
    ctx.form.signed_date = None
    ctx.withheld.add("proposal_form.signed_date")
    ctx.overrides["proposal_form.signed"] = False
    ctx.touched.add("proposal_form.signed_date")
    flag = ctx.flag("missing", "proposal_form", "Proposal form is not signed or dated.")
    return Defect("form.unsigned", "The proposal form is unsigned and undated, although the email calls it signed.",
                  "form", ["proposal_form.signed", "proposal_form.signed_date"], flag)


def form_revenue_conflict(ctx: Ctx) -> Defect | None:
    """Email turnover disagrees with the form, no tie-breaker: flag it."""
    path = "insured.annual_revenue"
    if path in ctx.touched:
        return None
    true = ctx.risk.insured.annual_revenue
    other = true
    while other in (true, ctx.risk.insured.prior_revenue):
        other = round_to(true * ctx.rng.choice([0.88, 0.92, 1.07, 1.12, 1.18]), 10_000)
    ctx.add_paragraph(ctx.rng.choice([
        f"Turnover for the year came in at {money(other, 'short')}, so a bit different from what's on the form.",
        f"FYI our turnover is {money(other, 'short')} now.",
        f"Revenue's about {money(other, 'short')} for this year if they ask.",
    ]))
    ctx.unscored.add(path)
    ctx.touched.add(path)
    flag = ctx.flag("conflict", path, "Turnover on the proposal form differs from the figure in the email.")
    return Defect("form.revenue_conflict", f"The email gives turnover as {money(other, 'symbol')}; the form says "
                  f"{money(true, 'symbol')}. Nothing says which is right.", "email", [path], flag, resolvable=False)


# ======================================================================== email


def email_stale_forward(ctx: Ctx) -> Defect:
    """Last year's renewal summary forwarded in the thread as a decoy."""
    r = ctx.risk
    main = ctx.main_email
    last = r.inception.replace(year=r.inception.year - 1)
    lines = [
        f"Renewal summary - {r.insured.name} - {last:%d/%m/%Y}",
        "",
        f"Insurer: {r.insurer_history[-1].insurer}",
        f"Turnover: {money(r.insured.prior_revenue, 'symbol')}",
        f"Employees: {r.insured.prior_employees}",
        f"Renewal date: {long_date(last)}",
    ]
    if r.cyber:
        lines.append(f"Limit: {money(r.cyber.limit_requested, 'symbol')}")
    if r.cargo:
        lines.append(f"Annual transit value: {money(round_to(r.cargo.annual_transit_value * 0.9, 10_000), 'symbol')}")
    main.quoted.insert(0, {
        "from": (r.broker.name, r.broker.email), "sent": main.sent - timedelta(days=360 + ctx.rng.randint(0, 20)),
        "subject": f"Renewal summary {last.year}", "style": "forward", "body": "\n".join(lines),
    })
    ctx.add_paragraph("I've forwarded last year's summary underneath so you've got it to hand.")
    checks = ["insured.annual_revenue", "insured.employees", "policy.inception_date"]
    return Defect("email.stale_forwarded_figures", "Last year's renewal summary is forwarded in the thread, with "
                  "last year's turnover, headcount and dates in clean, easy-to-grab text.", "email", checks)


# ======================================================================== claims


def claims_unreported_recent(ctx: Ctx) -> Defect | None:
    """A claim newer than the loss runs, mentioned only in the email body."""
    r = ctx.risk
    produced = max(lr.plan.produced for lr in ctx.lossrun_docs())
    start, end = produced + timedelta(days=1), r.as_of - timedelta(days=3)
    if end <= start:
        return None
    from . import refdata as R

    d = start + timedelta(days=ctx.rng.randint(0, (end - start).days))
    cause, (lo, hi) = ctx.rng.choice(R.CLAIM_CAUSES[r.line])
    reserved = round_to(ctx.rng.uniform(lo, min(hi, lo * 6)), 100)
    insurer = r.expiring.insurer
    loc_id = ctx.rng.choice(r.locations).id if r.locations else None
    claim = Claim(f"TBC-{ctx.rng.randint(1000, 9999)}", insurer, d, cause, 0, reserved, "open", loc_id)
    r.claims.append(claim)
    r.claims.sort(key=lambda c: c.date_of_loss)
    where = f" at the {r.location(loc_id).address.town} site" if loc_id else ""
    ctx.add_paragraph(ctx.rng.choice([
        f"One thing that won't be on the loss runs - we had a {cause.lower()} claim{where} on {long_date(d)}. "
        f"{insurer} have put a reserve of {money(reserved, 'symbol')} on it and it's still open.",
        f"Also, there's a new claim since those loss runs were printed: {cause.lower()}{where}, {d:%d/%m/%Y}, "
        f"reserve {money(reserved, 'symbol')}, nothing paid yet.",
    ]))
    form = ctx.form
    q = form.field("claims_declared")
    q.ticked = {"Yes"}
    return Defect("claims.unreported_recent_claim", f"A claim on {d.isoformat()} happened after the loss runs were "
                  "produced; it appears only in the email body.", "email", [CLAIMS])


def claims_loss_run_missing(ctx: Ctx) -> Defect | None:
    """Loss runs 'attached' but missing: claims unknown (null, not []), flag it."""
    lrs = ctx.lossrun_docs()
    if not lrs:
        return None
    for d in lrs:
        d.attached = False
    ctx.claims_unknown = True
    flag = ctx.flag("missing", "claims", "Email says loss runs are attached but none are.")
    return Defect("claims.loss_run_missing", "The email says the loss runs are attached. They aren't, so the "
                  "claims history is unknown (not 'no claims').", "email", ["claims"], flag)


def claims_short_loss_run(ctx: Ctx) -> Defect | None:
    """Loss runs cover 3 years, not 5: flag it."""
    r = ctx.risk
    cutoff = add_years(r.inception, -3)
    lrs = ctx.lossrun_docs()
    if not lrs:
        return None
    for d in lrs:
        lr: LossRunPlan = d.plan
        if lr.period_to < cutoff:
            del ctx.docs[d.key]
            if d.key in ctx.main_email.attachments:
                ctx.main_email.attachments.remove(d.key)
            if d.key in ctx.main_email.mention_attachments:
                ctx.main_email.mention_attachments.remove(d.key)
            continue
        if lr.period_from < cutoff:
            lr.period_from = cutoff
            lr.rows = [row for row in lr.rows if row.date_of_loss >= cutoff]
    for c in r.claims:
        if c.date_of_loss < cutoff:
            ctx.hidden_claims.add(c.ref)
    flag = ctx.flag("missing", "claims", "Loss runs only cover 3 years; insurers need 5.")
    return Defect("claims.short_loss_run", f"Loss runs only go back to {cutoff:%d/%m/%Y} (3 years, not 5). Older "
                  "claims are unknowable.", "lossrun", [CLAIMS], flag)


def claims_declared_free(ctx: Ctx) -> Defect | None:
    """Form declares no claims; loss runs show claims: flag it."""
    if not ctx.visible_claims():
        return None
    q = ctx.form.field("claims_declared")
    q.ticked = {"No"}
    for s in ctx.form.sections:
        for f in s.fields:
            if f.label.startswith("If yes"):
                f.value = ""
    flag = ctx.flag("conflict", "claims", "Proposal form declares no claims in 5 years; loss runs show claims.")
    return Defect("claims.declared_claims_free", "The proposal form ticks 'No claims in 5 years' but the loss runs "
                  "show claims. A fair-presentation problem to raise.", "form", [CLAIMS], flag)


def claims_open_repeated(ctx: Ctx) -> Defect | None:
    """Open claims listed twice (summary + full listing)."""
    for d in ctx.lossrun_docs():
        if any(row.status == "open" for row in d.plan.rows):
            d.plan.open_summary = True
            return Defect("claims.open_claims_repeated", "Open claims are listed twice: in an 'outstanding claims' "
                          "summary and again in the full listing.", d.key, [CLAIMS])
    return None


def claims_sister_company(ctx: Ctx) -> Defect:
    """Loss run for a related company attached; its claims don't count."""
    from . import refdata as R

    r = ctx.risk
    base = r.insured.name.split()[0]
    sister = f"{base} {ctx.rng.choice(['Holdings', 'Property', 'Logistics', 'Trading'])} Ltd"
    p = r.expiring
    rows = []
    for _ in range(ctx.rng.randint(1, 3)):
        d = p.start + timedelta(days=ctx.rng.randint(0, max(1, (r.as_of - p.start).days - 40)))
        cause, (lo, hi) = ctx.rng.choice(R.CLAIM_CAUSES[r.line])
        amt = round_to(ctx.rng.uniform(lo, hi), 50)
        rows.append(LossRunRow(f"{''.join(w[0] for w in p.insurer.split()[:2]).upper()}/{d.year % 100:02d}/{ctx.rng.randint(100000, 999999)}", d, cause, amt, 0, "closed"))
    rows.sort(key=lambda x: x.date_of_loss)
    produced = r.as_of - timedelta(days=ctx.rng.randint(15, 40))
    plan = LossRunPlan(p.insurer, sister, f"{p.policy_ref[:3]}-{ctx.rng.randint(1000000, 9999999)}",
                       p.start, produced, produced, rows)
    fname = f"Loss runs - {sister}.pdf"
    ctx.docs["lossrun:sister"] = Doc("lossrun:sister", fname, plan, casual_name=f"the loss runs for {sister}")
    ctx.main_email.attachments.append("lossrun:sister")
    ctx.main_email.mention_attachments.append("lossrun:sister")
    return Defect("claims.sister_company_loss_run", f"An extra loss run for a related company ({sister}) is "
                  "attached. Its claims are not this insured's.", "lossrun:sister", [CLAIMS])


def lossrun_scanned(ctx: Ctx) -> Defect | None:
    """A loss run as a skewed, noisy scan."""
    docs = [d for d in ctx.lossrun_docs() if d.attached]
    if not docs:
        return None
    d = ctx.rng.choice(docs)
    d.plan.degrade = "scan"
    return Defect("lossrun.scanned", "A loss run was faxed/scanned: image only, skewed and noisy.", d.key,
                  [CLAIMS, "claims.fields"])


def lossrun_photo(ctx: Ctx) -> Defect | None:
    """A loss run as phone photos (JPEG per page)."""
    docs = [d for d in ctx.lossrun_docs() if d.attached and d.plan.degrade is None]
    if not docs:
        return None
    d = ctx.rng.choice(docs)
    d.plan.degrade = "photo"
    return Defect("lossrun.phone_photo", "A loss run arrives as phone photos (JPEG per page): perspective, "
                  "shadows, desk in frame.", d.key, [CLAIMS, "claims.fields"])


# ======================================================================== registry


@dataclass
class Spec:
    code: str
    fn: Callable[[Ctx], Defect | None]
    lines: tuple[str, ...] = ("property", "cyber", "cargo")
    excludes: tuple[str, ...] = ()
    weight: float = 1.0


REGISTRY: list[Spec] = [
    # claims: run first, they can change the truth (unreported claim) and which docs exist
    Spec("claims.unreported_recent_claim", claims_unreported_recent, excludes=("claims.loss_run_missing",), weight=0.6),
    Spec("claims.short_loss_run", claims_short_loss_run, excludes=("claims.loss_run_missing",), weight=0.6),
    Spec("claims.loss_run_missing", claims_loss_run_missing,
         excludes=("claims.unreported_recent_claim", "claims.short_loss_run", "claims.declared_claims_free",
                   "claims.open_claims_repeated", "lossrun.scanned", "lossrun.phone_photo"), weight=0.6),
    Spec("claims.declared_claims_free", claims_declared_free, excludes=("claims.loss_run_missing",), weight=0.6),
    Spec("claims.open_claims_repeated", claims_open_repeated, excludes=("claims.loss_run_missing",), weight=0.6),
    Spec("claims.sister_company_loss_run", claims_sister_company, weight=0.6),
    Spec("lossrun.scanned", lossrun_scanned, excludes=("claims.loss_run_missing",), weight=0.6),
    Spec("lossrun.phone_photo", lossrun_photo, excludes=("claims.loss_run_missing",), weight=0.6),
    # spreadsheet
    Spec("sov.stale_tab", sov_stale_tab, lines=("property",)),
    Spec("sov.title_block", sov_title_block, lines=("property",)),
    Spec("sov.single_address_column", sov_single_address_column, lines=("property",)),
    Spec("sov.units_thousands", sov_units_thousands, lines=("property",)),
    Spec("sov.money_as_text", sov_money_as_text, lines=("property",)),
    Spec("sov.mixed_notation", sov_mixed_notation, lines=("property",)),
    Spec("sov.disposed_location", sov_disposed_location, lines=("property",)),
    Spec("sov.duplicate_row", sov_duplicate_row, lines=("property",)),
    Spec("sov.combined_values", sov_combined_values, lines=("property",)),
    Spec("sov.missing_construction", sov_missing_construction, lines=("property",)),
    Spec("email.sov_correction", email_sov_correction, lines=("property",)),
    Spec("sov.wrong_total", sov_wrong_total, lines=("property",)),
    # proposal form
    Spec("form.revenue_conflict", form_revenue_conflict),
    Spec("form.crossed_out_correction", form_crossed_out, excludes=("form.fillable_fields",)),
    Spec("form.blank_field", form_blank_field),
    Spec("form.double_ticked", form_double_ticked, lines=("cyber",), excludes=("form.fillable_fields",)),
    Spec("form.unsigned", form_unsigned, weight=0.7),
    Spec("form.fillable_fields", form_fillable,
         excludes=("form.handwritten", "form.scanned", "form.crossed_out_correction", "form.double_ticked")),
    Spec("form.handwritten", form_handwritten, excludes=("form.fillable_fields",)),
    Spec("form.scanned", form_scanned, excludes=("form.fillable_fields",)),
    # email
    Spec("email.stale_forwarded_figures", email_stale_forward),
]

CODES = [s.code for s in REGISTRY]

DIFFICULTY = {"clean": (0, 0), "easy": (1, 2), "medium": (3, 5), "hard": (6, 9), "nightmare": (99, 99)}


def choose(line: str, difficulty: str, rng: random.Random, only: list[str] | None = None) -> list[Spec]:
    pool = [s for s in REGISTRY if line in s.lines and (only is None or s.code in only)]
    if only is not None:
        return pool
    lo, hi = DIFFICULTY[difficulty]
    k = rng.randint(lo, hi)
    chosen: list[Spec] = []
    candidates = pool[:]
    while candidates and len(chosen) < k:
        pick = rng.choices(candidates, weights=[s.weight for s in candidates])[0]
        chosen.append(pick)
        candidates = [s for s in candidates if s is not pick and s.code not in pick.excludes
                      and pick.code not in s.excludes]
    return [s for s in REGISTRY if s in chosen]
