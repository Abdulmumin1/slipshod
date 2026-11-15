"""The real-world risk behind a submission. Documents are rendered from this; answers are derived from it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Address:
    line1: str
    town: str
    postcode: str

    def one_line(self) -> str:
        return f"{self.line1}, {self.town} {self.postcode}"


@dataclass
class Person:
    first: str
    last: str
    email: str

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


@dataclass
class Insured:
    name: str
    address: Address
    trade: str
    annual_revenue: int
    employees: int
    prior_revenue: int
    prior_employees: int
    domain: str
    company_number: str
    vat_number: str


@dataclass
class Location:
    id: str
    address: Address
    occupancy: str
    construction: str
    year_built: int
    sprinklered: bool
    buildings: int
    contents: int
    bi: int

    @property
    def total(self) -> int:
        return self.buildings + self.contents + self.bi


@dataclass
class Claim:
    ref: str
    insurer: str
    date_of_loss: date
    cause: str
    paid: int
    reserved: int
    status: str  # "open" | "closed"
    location_id: str | None = None

    @property
    def incurred(self) -> int:
        return self.paid + self.reserved


@dataclass
class CyberRisk:
    records_held: int
    mfa_remote_access: bool
    mfa_email: bool
    offline_backups: bool
    edr: bool
    pen_test_last_12m: bool
    pci_compliant: bool
    limit_requested: int


@dataclass
class CargoRisk:
    annual_transit_value: int
    max_any_one_conveyance: int
    commodities: str
    conveyances: list[str]
    geographical_limits: str
    packaging: str


@dataclass
class InsurerPeriod:
    insurer: str
    policy_ref: str
    start: date
    end: date


@dataclass
class Risk:
    id: str
    line: str  # "property" | "cyber" | "cargo"
    as_of: date
    insured: Insured
    contact: Person
    broker: Person
    broker_firm: str
    inception: date
    expiry: date
    currency: str
    insurer_history: list[InsurerPeriod]
    claims: list[Claim]
    form_signed_date: date
    locations: list[Location] = field(default_factory=list)
    cyber: CyberRisk | None = None
    cargo: CargoRisk | None = None

    @property
    def expiring(self) -> InsurerPeriod:
        return self.insurer_history[-1]

    def location(self, loc_id: str) -> Location:
        return next(loc for loc in self.locations if loc.id == loc_id)


def _addr(a: Address) -> dict:
    return {"line1": a.line1, "town": a.town, "postcode": a.postcode}


def claim_answer(c: Claim) -> dict:
    return {
        "date_of_loss": c.date_of_loss.isoformat(),
        "cause": c.cause,
        "insurer": c.insurer,
        "paid": c.paid,
        "reserved": c.reserved,
        "status": c.status,
    }


def location_answer(loc: Location) -> dict:
    return {
        "address": _addr(loc.address),
        "occupancy": loc.occupancy,
        "construction": loc.construction,
        "year_built": loc.year_built,
        "sprinklered": loc.sprinklered,
        "buildings_sum_insured": loc.buildings,
        "contents_sum_insured": loc.contents,
        "bi_sum_insured": loc.bi,
        "total_sum_insured": loc.total,
    }


def risk_to_answer(risk: Risk) -> dict:
    """What a perfect reader would extract if every document were clean and complete."""
    ins = risk.insured
    answer: dict = {
        "submission_id": risk.id,
        "line_of_business": risk.line,
        "insured": {
            "name": ins.name,
            "address": _addr(ins.address),
            "trade": ins.trade,
            "annual_revenue": ins.annual_revenue,
            "employees": ins.employees,
        },
        "policy": {
            "inception_date": risk.inception.isoformat(),
            "expiry_date": risk.expiry.isoformat(),
            "currency": risk.currency,
        },
        "proposal_form": {
            "signed": True,
            "signed_date": risk.form_signed_date.isoformat(),
        },
        "property": None,
        "cyber": None,
        "cargo": None,
        "claims": [claim_answer(c) for c in sorted(risk.claims, key=lambda c: c.date_of_loss)],
        "flags": [],
    }
    if risk.line == "property":
        answer["property"] = {
            "total_tiv": sum(loc.total for loc in risk.locations),
            "locations": [location_answer(loc) for loc in risk.locations],
        }
    if risk.cyber:
        c = risk.cyber
        answer["cyber"] = {
            "records_held": c.records_held,
            "mfa_remote_access": c.mfa_remote_access,
            "mfa_email": c.mfa_email,
            "offline_backups": c.offline_backups,
            "edr": c.edr,
            "pen_test_last_12m": c.pen_test_last_12m,
            "pci_compliant": c.pci_compliant,
            "limit_requested": c.limit_requested,
        }
    if risk.cargo:
        g = risk.cargo
        answer["cargo"] = {
            "annual_transit_value": g.annual_transit_value,
            "max_any_one_conveyance": g.max_any_one_conveyance,
            "commodities": g.commodities,
            "conveyances": sorted(g.conveyances),
            "geographical_limits": g.geographical_limits,
            "packaging": g.packaging,
        }
    return answer
