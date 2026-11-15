"""Generate the underlying, true risk for one submission."""

from __future__ import annotations

import random
import re
from datetime import date, timedelta

from . import refdata as R
from .model import (
    Address, CargoRisk, Claim, CyberRisk, Insured, InsurerPeriod, Location, Person, Risk,
)


def round_to(x: float, step: int) -> int:
    return max(step, int(round(x / step)) * step)


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def postcode(rng: random.Random, area: str, districts: list[int]) -> str:
    letters = R.POSTCODE_LETTERS
    return f"{area}{rng.choice(districts)} {rng.randint(1, 9)}{rng.choice(letters)}{rng.choice(letters)}"


def street_address(rng: random.Random, industrial: bool) -> str:
    if industrial and rng.random() < 0.7:
        unit = rng.choice([f"Unit {rng.randint(1, 24)}", f"Units {(n := rng.randint(1, 18))}-{n + rng.randint(1, 3)}"])
        return f"{unit}, {rng.choice(R.ESTATE_NAMES)} {rng.choice(R.ESTATE_TYPES)}"
    return f"{rng.randint(1, 240)} {rng.choice(R.STREET_NAMES)} {rng.choice(R.STREET_TYPES)}"


def make_address(rng: random.Random, used_postcodes: set[str], industrial: bool, town=None) -> Address:
    town = town or rng.choice(R.TOWNS)
    while True:
        pc = postcode(rng, town[1], town[2])
        if pc not in used_postcodes:
            used_postcodes.add(pc)
            return Address(street_address(rng, industrial), town[0], pc)


def slug(name: str) -> str:
    base = re.sub(r"\b(ltd|limited|group|sons)\b", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "", base)


def person(rng: random.Random, domain: str) -> Person:
    first, last = rng.choice(R.FIRST_NAMES), rng.choice(R.LAST_NAMES)
    local = rng.choice([f"{first}.{last}", f"{first[0]}{last}", first]).lower()
    return Person(first, last, f"{local}@{domain}")


def _claims(rng: random.Random, risk_line: str, history: list[InsurerPeriod], as_of: date,
            locations: list[Location]) -> list[Claim]:
    n = rng.choices([0, 1, 2, 3, 4], weights=[2, 4, 3, 2, 1])[0]
    claims: list[Claim] = []
    start = history[0].start
    span = (as_of - timedelta(days=30) - start).days
    for _ in range(n):
        d = start + timedelta(days=rng.randint(0, span))
        cause, (lo, hi) = rng.choice(R.CLAIM_CAUSES[risk_line])
        period = next(p for p in history if p.start <= d <= p.end)
        incurred = round_to(rng.uniform(lo, hi), 50)
        recent = (as_of - d).days < 300
        status = "open" if recent and rng.random() < 0.7 else "closed"
        if status == "open":
            paid = round_to(incurred * rng.uniform(0, 0.6), 50) if rng.random() < 0.6 else 0
            reserved = max(50, incurred - paid)
        else:
            paid, reserved = incurred, 0
        ref = f"{''.join(w[0] for w in period.insurer.split()[:2]).upper()}/{d.year % 100:02d}/{rng.randint(100000, 999999)}"
        loc_id = rng.choice(locations).id if locations else None
        claims.append(Claim(ref, period.insurer, d, cause, paid, reserved, status, loc_id))
    claims.sort(key=lambda c: c.date_of_loss)
    return claims


def generate_risk(rng: random.Random, sub_id: str, line: str, as_of: date) -> Risk:
    trade = rng.choice([t for t in R.TRADES if line in t.lines])
    name = f"{rng.choice(R.COMPANY_WORDS)} {trade.noun} {rng.choice(R.COMPANY_SUFFIXES)}"
    domain = f"{slug(name)}.co.uk"
    used: set[str] = set()
    hq_town = rng.choice(R.TOWNS)
    industrial = trade.occupancies[0] not in ("Offices", "Dental surgery")
    hq = make_address(rng, used, industrial, hq_town)

    revenue = round_to(rng.uniform(*trade.revenue), 10_000)
    prior_revenue = revenue
    while prior_revenue == revenue:
        prior_revenue = round_to(revenue * rng.uniform(0.78, 1.04), 10_000)
    employees = rng.randint(*trade.employees)
    prior_employees = max(2, employees + rng.choice([-7, -5, -4, -3, -2, 2, 3]))

    insured = Insured(
        name=name, address=hq, trade=trade.description, annual_revenue=revenue,
        employees=employees, prior_revenue=prior_revenue, prior_employees=prior_employees,
        domain=domain, company_number=f"{rng.randint(1, 13):02d}{rng.randint(100000, 999999)}",
        vat_number=f"GB{rng.randint(100, 999)} {rng.randint(1000, 9999)} {rng.randint(10, 99)}",
    )

    # Renewals usually incept on the 1st, one to four months out.
    month = as_of.month + rng.randint(1, 4)
    inception = date(as_of.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)
    expiry = add_years(inception, 1) - timedelta(days=1)

    n_insurers = rng.choice([1, 1, 2])
    insurers = rng.sample(R.INSURERS, n_insurers)
    history: list[InsurerPeriod] = []
    first_start = add_years(inception, -5)
    switch_year = rng.randint(1, 4) if n_insurers == 2 else 99
    for i in range(5):
        ins = insurers[0] if i < switch_year else insurers[-1]
        start, end = add_years(first_start, i), add_years(first_start, i + 1) - timedelta(days=1)
        if history and history[-1].insurer == ins:
            history[-1].end = end
        else:
            ref = f"{ins.split()[0][:3].upper()}-{rng.randint(1000000, 9999999)}"
            history.append(InsurerPeriod(ins, ref, start, end))

    broker_firm, broker_domain = rng.choice(R.BROKER_FIRMS)
    risk = Risk(
        id=sub_id, line=line, as_of=as_of, insured=insured,
        contact=person(rng, domain), broker=person(rng, broker_domain), broker_firm=broker_firm,
        inception=inception, expiry=expiry, currency="GBP", insurer_history=history, claims=[],
        form_signed_date=as_of - timedelta(days=rng.randint(1, 15)),
    )

    if line == "property":
        n_locs = rng.choices([1, 2, 3, 4, 5, 6], weights=[2, 4, 4, 3, 2, 1])[0]
        for i in range(n_locs):
            addr = hq if i == 0 else make_address(rng, used, industrial, rng.choice([hq_town, *rng.sample(R.TOWNS, 2)]))
            occ = trade.occupancies[0] if i == 0 else rng.choice(trade.occupancies)
            big = occ not in ("Offices", "Retail shop", "Showroom", "Dental surgery")
            constr = rng.choices([c for c, _ in R.CONSTRUCTION], weights=[w for _, w in R.CONSTRUCTION])[0]
            risk.locations.append(Location(
                id=f"L{i + 1}", address=addr, occupancy=occ, construction=constr,
                year_built=rng.randint(1890, 2021),
                sprinklered=rng.random() < (0.35 if big else 0.08),
                buildings=round_to(rng.uniform(1_500_000, 7_500_000) if big else rng.uniform(250_000, 1_800_000), 5_000),
                contents=round_to(rng.uniform(150_000, 2_500_000) if big else rng.uniform(40_000, 400_000), 5_000),
                bi=0 if rng.random() < 0.25 else round_to(rng.uniform(100_000, 3_000_000), 10_000),
            ))
    elif line == "cyber":
        risk.cyber = CyberRisk(
            records_held=round_to(rng.uniform(500, 250_000), 500),
            mfa_remote_access=rng.random() < 0.8,
            mfa_email=rng.random() < 0.65,
            offline_backups=rng.random() < 0.7,
            edr=rng.random() < 0.55,
            pen_test_last_12m=rng.random() < 0.4,
            pci_compliant=rng.random() < 0.6,
            limit_requested=rng.choice([250_000, 500_000, 1_000_000, 2_000_000, 5_000_000]),
        )
    elif line == "cargo":
        atv = round_to(rng.uniform(800_000, 30_000_000), 10_000)
        conveyances = sorted(rng.sample(["road", "sea", "air", "rail"], rng.choice([1, 2, 2, 3])))
        if "road" not in conveyances and rng.random() < 0.7:
            conveyances = sorted([*conveyances, "road"])
        risk.cargo = CargoRisk(
            annual_transit_value=atv,
            max_any_one_conveyance=round_to(min(atv * rng.uniform(0.02, 0.12), 750_000), 5_000),
            commodities=trade.commodities,
            conveyances=conveyances,
            geographical_limits=rng.choice(R.GEO_LIMITS),
            packaging=rng.choice(R.PACKAGING),
        )
    else:
        raise ValueError(f"unknown line of business: {line}")

    risk.claims = _claims(rng, line, history, as_of, risk.locations)
    return risk
