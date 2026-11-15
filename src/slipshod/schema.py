"""The output an agent should produce for each submission, as JSON Schema plus a task brief."""

from __future__ import annotations

_money = {"type": ["number", "null"], "description": "GBP, full units (not thousands)."}
_bool = {"type": ["boolean", "null"]}
_text = {"type": ["string", "null"]}
_date = {"type": ["string", "null"], "description": "ISO date, YYYY-MM-DD."}
_address = {
    "type": ["object", "null"],
    "properties": {"line1": _text, "town": _text, "postcode": _text},
}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "slipshod extraction",
    "type": "object",
    "required": ["submission_id", "insured", "policy", "claims", "flags"],
    "properties": {
        "submission_id": {"type": "string"},
        "line_of_business": {"enum": ["property", "cyber", "cargo"]},
        "insured": {
            "type": "object",
            "properties": {
                "name": _text, "address": _address, "trade": _text,
                "annual_revenue": _money, "employees": {"type": ["integer", "null"]},
            },
        },
        "policy": {
            "type": "object",
            "properties": {"inception_date": _date, "expiry_date": _date, "currency": _text},
        },
        "proposal_form": {
            "type": ["object", "null"],
            "properties": {"signed": _bool, "signed_date": _date},
        },
        "property": {
            "type": ["object", "null"],
            "properties": {
                "total_tiv": _money,
                "locations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "address": _address, "occupancy": _text, "construction": _text,
                            "year_built": {"type": ["integer", "null"]}, "sprinklered": _bool,
                            "buildings_sum_insured": _money, "contents_sum_insured": _money,
                            "bi_sum_insured": _money, "total_sum_insured": _money,
                        },
                    },
                },
            },
        },
        "cyber": {
            "type": ["object", "null"],
            "properties": {
                "records_held": {"type": ["integer", "null"]}, "mfa_remote_access": _bool, "mfa_email": _bool,
                "offline_backups": _bool, "edr": _bool, "pen_test_last_12m": _bool, "pci_compliant": _bool,
                "limit_requested": _money,
            },
        },
        "cargo": {
            "type": ["object", "null"],
            "properties": {
                "annual_transit_value": _money, "max_any_one_conveyance": _money, "commodities": _text,
                "conveyances": {"type": ["array", "null"], "items": {"enum": ["road", "sea", "air", "rail"]}},
                "geographical_limits": _text, "packaging": _text,
            },
        },
        "claims": {
            "type": ["array", "null"],
            "description": "Claims of THIS insured in the last 5 years. null = claims history unknown; [] = known to be claim-free.",
            "items": {
                "type": "object",
                "properties": {
                    "date_of_loss": _date, "cause": _text, "insurer": _text,
                    "paid": _money, "reserved": _money, "status": {"enum": ["open", "closed"]},
                },
            },
        },
        "flags": {
            "type": "array",
            "description": "Things a broker must chase before this can go to market.",
            "items": {
                "type": "object",
                "required": ["type", "field"],
                "properties": {
                    "type": {"enum": ["missing", "conflict"]},
                    "field": {"type": "string", "description": "Path, e.g. insured.annual_revenue, "
                              "property.locations[LS11 5QT].construction, claims, proposal_form"},
                    "note": {"type": "string"},
                },
            },
        },
    },
}

BRIEF = """\
You are a commercial insurance broker's assistant. A client has emailed renewal
information. Read every .eml file and every attachment for this submission and
produce one JSON object matching the slipshod schema.

Rules
- Extract the CURRENT position for the coming policy period. Ignore last year's
  figures, superseded values and documents that belong to other companies.
- Later corrections override earlier documents.
- Money in full GBP (2.1m -> 2100000; a column headed (£000) means thousands).
- Locations: one entry per insured site currently to be covered. No totals rows,
  duplicates or disposed sites.
- Claims: only this insured's claims. Count each claim once. Use null for
  "claims" if the history is not provided; use [] only if it is shown to be nil.
- If a value is not stated anywhere, use null. Do not guess.
- If sources disagree and nothing says which is right, give your best value
  and add a flag {"type": "conflict", "field": <path>}. If something needed is
  missing (blank, unsigned, incomplete history), add {"type": "missing", ...}.
- Field paths for flags use dots, with locations keyed by postcode:
  property.locations[LS11 5QT].construction
"""
