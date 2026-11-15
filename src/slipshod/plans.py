"""Document plans: an editable description of what each document will show.

Plans start out as faithful renderings of the risk. Defects then edit the plans
(and record what they did). Renderers turn the final plans into files.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .model import Claim, Risk

UK = timezone.utc


def money(v: int, style: str = "commas", symbol: str = "£") -> str:
    if style == "plain":
        return f"{v}"
    if style == "commas":
        return f"{v:,}"
    if style == "symbol":
        return f"{symbol}{v:,}"
    if style == "short":
        if v >= 1_000_000 and v % 10_000 == 0:
            return f"{symbol}{v / 1_000_000:g}m"
        if v >= 1_000 and v % 1_000 == 0:
            return f"{symbol}{v // 1_000}k"
        return f"{symbol}{v:,}"
    raise ValueError(style)


def long_date(d: date) -> str:
    day = d.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d:%B %Y}"


# --------------------------------------------------------------------- spreadsheet

SOV_HEADERS = {
    "loc_no": ["Loc No", "Location", "#", "Site ref"],
    "address": ["Address", "Site Address", "Premises"],
    "line1": ["Address", "Address Line 1", "Street"],
    "town": ["Town", "City", "Town/City"],
    "postcode": ["Postcode", "Post Code", "PC"],
    "occupancy": ["Occupancy", "Use", "Trade at premises"],
    "construction": ["Construction", "Constr.", "Wall / Roof"],
    "year_built": ["Year Built", "Built", "Age (yr built)"],
    "sprinklered": ["Sprinklers", "Sprinklered?", "Sprinkler (Y/N)"],
    "buildings": ["Buildings", "Buildings SI", "Bldgs Sum Insured", "Building Value"],
    "contents": ["Contents", "Contents SI", "Plant & Contents", "Stock & Contents"],
    "bi": ["BI", "Business Interruption", "Gross Profit (BI)", "Loss of Revenue"],
    "total": ["Total", "TIV", "Total Sum Insured", "Total Value"],
}
MONEY_KEYS = ("buildings", "contents", "bi", "total")


@dataclass
class SheetRow:
    values: dict  # key -> int | str | bool | None. Strings are written verbatim.
    hidden: bool = False
    strike: bool = False
    fill: str | None = None
    note: str | None = None
    location_id: str | None = None  # None = not a real insured location


@dataclass
class SheetPlan:
    name: str
    columns: list[tuple[str, str]]
    rows: list[SheetRow]
    title_lines: list[str] = field(default_factory=list)
    group_header: bool = False
    blank_row_every: int = 0
    units: int = 1
    money_style: str = "number"  # number | mixed_text
    sprinkler_style: str = "YN"  # YN | yesno | tick
    year_style: str = "plain"  # plain | circa
    totals: str | dict | None = "auto"  # "auto", explicit {key: value}, or None
    seed: int = 0

    def has(self, key: str) -> bool:
        return any(k == key for k, _ in self.columns)


@dataclass
class SOVPlan:
    sheets: list[SheetPlan]
    active_index: int = 0


# --------------------------------------------------------------------- proposal form

@dataclass
class FormField:
    label: str
    value: str | None = None
    kind: str = "text"  # text | choice | multi
    options: tuple[str, ...] = ()
    ticked: set[str] = field(default_factory=set)
    correction: str | None = None  # an old value that is crossed out next to the new one
    path: str | None = None  # answer path this field evidences


@dataclass
class FormSection:
    title: str
    fields: list[FormField]


@dataclass
class FormPlan:
    issuer: str
    title: str
    sections: list[FormSection]
    signed_name: str | None
    signed_date: date | None
    handwritten: bool = False
    fillable: bool = False
    degrade: str | None = None  # None | "scan"

    def field(self, path: str) -> FormField:
        for s in self.sections:
            for f in s.fields:
                if f.path == path:
                    return f
        raise KeyError(path)

    def has(self, path: str) -> bool:
        return any(f.path == path for s in self.sections for f in s.fields)


# --------------------------------------------------------------------- loss run

@dataclass
class LossRunRow:
    ref: str
    date_of_loss: date
    cause: str
    paid: int
    reserved: int
    status: str


@dataclass
class LossRunPlan:
    insurer: str
    insured_name: str
    policy_ref: str
    period_from: date
    period_to: date
    produced: date
    rows: list[LossRunRow]
    open_summary: bool = False
    degrade: str | None = None  # None | "scan" | "photo"


def lossrun_row(c: Claim) -> LossRunRow:
    return LossRunRow(c.ref, c.date_of_loss, c.cause, c.paid, c.reserved, c.status)


# --------------------------------------------------------------------- email

@dataclass
class Doc:
    key: str  # "sov" | "form" | "lossrun:<n>" | "lossrun:sister"
    filename: str
    plan: object
    attached: bool = True
    casual_name: str = ""


@dataclass
class EmailPlan:
    filename: str
    sender: tuple[str, str]
    to: tuple[str, str]
    sent: datetime
    subject: str
    paragraphs: list[str]
    attachments: list[str]  # doc keys
    mention_attachments: list[str] = field(default_factory=list)  # doc keys the text says are attached
    quoted: list[dict] = field(default_factory=list)  # earlier messages: {from, sent, subject, body, style}
    signature: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- builders

def build_sov(risk: Risk, rng: random.Random) -> SOVPlan:
    keys = ["loc_no", "line1", "town", "postcode", "occupancy", "construction", "year_built",
            "sprinklered", "buildings", "contents", "bi", "total"]
    columns = [(k, rng.choice(SOV_HEADERS[k])) for k in keys]
    rows = []
    for i, loc in enumerate(risk.locations, start=1):
        rows.append(SheetRow(values={
            "loc_no": i, "line1": loc.address.line1, "town": loc.address.town,
            "postcode": loc.address.postcode, "occupancy": loc.occupancy,
            "construction": loc.construction, "year_built": loc.year_built,
            "sprinklered": loc.sprinklered, "buildings": loc.buildings, "contents": loc.contents,
            "bi": loc.bi, "total": loc.total,
        }, location_id=loc.id))
    name = rng.choice([f"SOV {risk.inception.year}", "Schedule", f"{risk.inception.year}-{risk.inception.year % 100 + 1:02d}", "Sheet1"])
    return SOVPlan([SheetPlan(name, columns, rows, seed=rng.randrange(1 << 30))])


def _yn(v: bool) -> set[str]:
    return {"Yes"} if v else {"No"}


def build_form(risk: Risk, rng: random.Random) -> FormPlan:
    ins = risk.insured
    title = {"property": "Commercial Property Proposal Form",
             "cyber": "Cyber & Data Proposal Form",
             "cargo": "Marine Cargo (Annual Open Cover) Proposal Form"}[risk.line]
    proposer = FormSection("1. The Proposer", [
        FormField("Name of proposer", ins.name, path="insured.name"),
        FormField("Trading address", ins.address.line1, path="insured.address.line1"),
        FormField("Town", ins.address.town, path="insured.address.town"),
        FormField("Postcode", ins.address.postcode, path="insured.address.postcode"),
        FormField("Business description", ins.trade, path="insured.trade"),
        FormField("Annual turnover (£)", money(ins.annual_revenue, "commas"), path="insured.annual_revenue"),
        FormField("Number of employees", str(ins.employees), path="insured.employees"),
    ])
    period = FormSection("2. Period of Insurance", [
        FormField("From", risk.inception.strftime("%d/%m/%Y"), path="policy.inception_date"),
        FormField("To", risk.expiry.strftime("%d/%m/%Y"), path="policy.expiry_date"),
    ])
    sections = [proposer, period]
    if risk.line == "property":
        sections.append(FormSection("3. Premises", [
            FormField("Number of premises to be insured", str(len(risk.locations))),
            FormField("Details of premises", "See attached schedule"),
        ]))
    elif risk.line == "cyber":
        c = risk.cyber
        yn = ("Yes", "No")
        sections.append(FormSection("3. Data & Security", [
            FormField("Approx. number of personal records held", f"{c.records_held:,}", path="cyber.records_held"),
            FormField("Is MFA enforced for all remote access?", kind="choice", options=yn, ticked=_yn(c.mfa_remote_access), path="cyber.mfa_remote_access"),
            FormField("Is MFA enforced for email?", kind="choice", options=yn, ticked=_yn(c.mfa_email), path="cyber.mfa_email"),
            FormField("Offline or immutable backups at least weekly?", kind="choice", options=yn, ticked=_yn(c.offline_backups), path="cyber.offline_backups"),
            FormField("EDR deployed on all endpoints?", kind="choice", options=yn, ticked=_yn(c.edr), path="cyber.edr"),
            FormField("Penetration test in the last 12 months?", kind="choice", options=yn, ticked=_yn(c.pen_test_last_12m), path="cyber.pen_test_last_12m"),
            FormField("PCI-DSS compliant?", kind="choice", options=yn, ticked=_yn(c.pci_compliant), path="cyber.pci_compliant"),
            FormField("Limit of indemnity required (£)", money(c.limit_requested, "commas"), path="cyber.limit_requested"),
        ]))
    elif risk.line == "cargo":
        g = risk.cargo
        sections.append(FormSection("3. Transit Details", [
            FormField("Estimated annual value in transit (£)", money(g.annual_transit_value, "commas"), path="cargo.annual_transit_value"),
            FormField("Maximum value any one conveyance (£)", money(g.max_any_one_conveyance, "commas"), path="cargo.max_any_one_conveyance"),
            FormField("Commodities", g.commodities, path="cargo.commodities"),
            FormField("Conveyances", kind="multi", options=("Road", "Sea", "Air", "Rail"),
                      ticked={c.capitalize() for c in g.conveyances}, path="cargo.conveyances"),
            FormField("Geographical limits", g.geographical_limits, path="cargo.geographical_limits"),
            FormField("Packaging", g.packaging, path="cargo.packaging"),
        ]))
    has_claims = bool(risk.claims)
    sections.append(FormSection("4. Claims Experience", [
        FormField("Any losses or claims in the last 5 years, whether insured or not?", kind="choice",
                  options=("Yes", "No"), ticked=_yn(has_claims), path="claims_declared"),
        FormField("If yes, please give details", "See insurer loss runs" if has_claims else ""),
    ]))
    return FormPlan(risk.broker_firm, title, sections, risk.contact.name, risk.form_signed_date)


def build_lossruns(risk: Risk) -> list[LossRunPlan]:
    plans = []
    for p in risk.insurer_history:
        rows = [lossrun_row(c) for c in risk.claims if c.insurer == p.insurer and p.start <= c.date_of_loss <= p.end]
        if p.end < risk.as_of - timedelta(days=21):
            produced, period_to = p.end + timedelta(days=14), p.end  # requested on leaving that insurer
        else:
            produced = period_to = risk.as_of - timedelta(days=21)
        plans.append(LossRunPlan(p.insurer, risk.insured.name, p.policy_ref, p.start, period_to, produced, rows))
    return plans


def build_main_email(risk: Risk, rng: random.Random, docs: list[Doc]) -> EmailPlan:
    c, b = risk.contact, risk.broker
    sent = datetime.combine(risk.as_of, datetime.min.time(), UK) + timedelta(hours=rng.randint(7, 18), minutes=rng.randint(0, 59))
    subject = rng.choice([
        "Renewal info", f"RE: {risk.insured.name} - renewal {risk.inception:%d/%m/%Y}",
        "renewal docs attached", f"Insurance renewal - {risk.insured.name}", "RE: Info needed for your renewal",
    ])
    opening = rng.choice([
        "Sorry this is a bit later than you wanted.",
        f"As requested, here's everything for the renewal on the {long_date(risk.inception)}.",
        "Finally got round to pulling this together for you.",
        "Please see attached for the renewal.",
    ])
    closing = rng.choice([
        "Let me know if you need anything else.",
        "Shout if anything's missing.",
        "Any questions give me a call.",
        "Thanks for your help as always.",
    ])
    ins = risk.insured
    signature = [
        c.name,
        rng.choice(["Finance Director", "Operations Manager", "Office Manager", "Managing Director", "Financial Controller"]),
        ins.name,
        f"T: 01{rng.randint(13, 99)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}  M: 07{rng.randint(100, 999)} {rng.randint(100000, 999999)}",
        f"{ins.name} | Registered in England & Wales No. {ins.company_number} | VAT {ins.vat_number}",
        f"Registered office: {ins.address.one_line()}",
    ]
    attach = [d.key for d in docs]
    request = {
        "from": (b.name, b.email),
        "sent": sent - timedelta(days=rng.randint(10, 30), hours=rng.randint(0, 8)),
        "subject": f"Info needed for your renewal - {ins.name}",
        "body": (
            f"Hi {c.first},\n\nYour {risk.line} policy with {risk.expiring.insurer} renews on "
            f"{long_date(risk.inception)}. To get terms in front of insurers, please could you send:\n\n"
            + ("- an updated schedule of values for all sites\n" if risk.line == "property" else "")
            + "- the attached proposal form, completed and signed\n"
            "- loss runs from your current insurer(s)\n\n"
            f"Many thanks,\n{b.name}\n{risk.broker_firm}"
        ),
        "style": rng.choice(["outlook", "gmail"]),
    }
    return EmailPlan(
        filename="01_" + re.sub(r"[^a-z0-9]+", "_", subject.lower())[:40].strip("_") + ".eml",
        sender=(c.name, c.email), to=(b.name, b.email), sent=sent, subject=subject,
        paragraphs=[f"Hi {b.first},", opening, "{attachments}", closing],
        attachments=attach, mention_attachments=list(attach), quoted=[request], signature=signature,
    )
