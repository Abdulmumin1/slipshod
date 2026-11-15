"""Score an agent's extractions against the answer key.

Beyond accuracy, the scorer reports:
- hallucinations: a value given where the documents don't support one
- flag recall: did the agent raise what a careful broker would chase
- defect survival: for each kind of mess, did the agent get through it unscathed
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from .paths import covers, flatten, location_key, norm_key, normalize

MONEY = "money"
KINDS = {
    "insured.name": "text",
    "insured.address.line1": "text",
    "insured.address.town": "text",
    "insured.address.postcode": "postcode",
    "insured.trade": "soft",
    "insured.annual_revenue": MONEY,
    "insured.employees": "int",
    "policy.inception_date": "date",
    "policy.expiry_date": "date",
    "policy.currency": "code",
    "proposal_form.signed": "bool",
    "proposal_form.signed_date": "date",
    "property.total_tiv": MONEY,
    "property.locations.address.line1": "text",
    "property.locations.address.town": "text",
    "property.locations.address.postcode": "postcode",
    "property.locations.occupancy": "soft",
    "property.locations.construction": "soft",
    "property.locations.year_built": "int",
    "property.locations.sprinklered": "bool",
    "property.locations.buildings_sum_insured": MONEY,
    "property.locations.contents_sum_insured": MONEY,
    "property.locations.bi_sum_insured": MONEY,
    "property.locations.total_sum_insured": MONEY,
    "cyber.records_held": MONEY,
    "cyber.mfa_remote_access": "bool",
    "cyber.mfa_email": "bool",
    "cyber.offline_backups": "bool",
    "cyber.edr": "bool",
    "cyber.pen_test_last_12m": "bool",
    "cyber.pci_compliant": "bool",
    "cyber.limit_requested": MONEY,
    "cargo.annual_transit_value": MONEY,
    "cargo.max_any_one_conveyance": MONEY,
    "cargo.commodities": "soft",
    "cargo.conveyances": "set",
    "cargo.geographical_limits": "soft",
    "cargo.packaging": "soft",
}


# ----------------------------------------------------------------------------- parsing

def parse_number(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace(",", "").replace("£", "").replace("gbp", "").replace("c.", "").strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(k|m|mil|million|bn)?", s)
    if not m:
        return None
    mult = {"k": 1e3, "m": 1e6, "mil": 1e6, "million": 1e6, "bn": 1e9}.get(m.group(2) or "", 1)
    return float(m.group(1)) * mult


def parse_date(v) -> date | None:
    if isinstance(v, date):
        return v
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return parse_date(m.group(1)) if m else None


def parse_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("yes", "y", "true", "1", "✓"):
        return True
    if s in ("no", "n", "false", "0", "✗"):
        return False
    return None


_STOP = {"ltd", "limited", "plc", "the", "and", "of"}


def norm_text(v) -> str:
    s = str(v).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def _tokens(v) -> set[str]:
    return {t for t in norm_text(v).split() if t not in _STOP}


def is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "") or (isinstance(v, list) and not v)


def equal(kind: str, truth, pred) -> bool:
    if kind == MONEY:
        t, p = parse_number(truth), parse_number(pred)
        return t is not None and p is not None and abs(t - p) <= max(1.0, abs(t) * 0.001)
    if kind == "int":
        t, p = parse_number(truth), parse_number(pred)
        return t is not None and p is not None and round(t) == round(p)
    if kind == "date":
        t = parse_date(truth)
        return t is not None and t == parse_date(pred)
    if kind == "bool":
        return parse_bool(pred) is not None and parse_bool(truth) == parse_bool(pred)
    if kind == "postcode":
        return norm_key(truth) == norm_key(pred)
    if kind == "code":
        return str(truth).strip().upper() == str(pred).strip().upper()
    if kind == "set":
        if not isinstance(pred, (list, tuple, set)):
            pred = re.split(r"[,/;&]| and ", str(pred))
        return {norm_text(x) for x in truth} == {norm_text(x) for x in pred if norm_text(x)}
    a, b = norm_text(truth), norm_text(pred)
    if a == b:
        return True
    if kind == "text":
        return SequenceMatcher(None, a, b).ratio() >= 0.88
    ta, tb = _tokens(truth), _tokens(pred)
    jacc = len(ta & tb) / len(ta | tb) if ta | tb else 0
    return jacc >= 0.5 or SequenceMatcher(None, a, b).ratio() >= 0.75


def kind_of(path: str) -> str:
    generic = re.sub(r"\[[^\]]*\]", "", path)
    return KINDS.get(generic, "text")


# ----------------------------------------------------------------------------- matching

def _match_locations(truth_locs: list[dict], pred_locs: list[dict]) -> list[tuple[dict, dict]]:
    pairs, used = [], set()
    by_key = {location_key(t): t for t in truth_locs}
    rest = []
    for p in pred_locs:
        if not isinstance(p, dict):
            continue
        t = by_key.get(location_key(p))
        if t is not None and id(t) not in used:
            used.add(id(t))
            pairs.append((t, p))
        else:
            rest.append(p)
    for p in rest:
        pa = p.get("address") or {}
        best, score = None, 0.0
        for t in truth_locs:
            if id(t) in used:
                continue
            ta = t["address"]
            s = SequenceMatcher(None, norm_text(f"{ta['line1']} {ta['town']}"),
                                norm_text(f"{pa.get('line1', '')} {pa.get('town', '')}")).ratio()
            if s > score:
                best, score = t, s
        if best is not None and score >= 0.8:
            used.add(id(best))
            pairs.append((best, p))
    return pairs


def _match_claims(truth: list[dict], pred: list[dict]) -> list[tuple[dict, dict]]:
    pairs, used = [], set()
    for t in truth:
        td = parse_date(t["date_of_loss"])
        best, best_cost = None, None
        for i, p in enumerate(pred):
            if i in used or not isinstance(p, dict):
                continue
            pdt = parse_date(p.get("date_of_loss"))
            if pdt is None or abs((pdt - td).days) > 2:
                continue
            pi = (parse_number(p.get("paid")) or 0) + (parse_number(p.get("reserved")) or 0)
            cost = abs(pi - (t["paid"] + t["reserved"])) + abs((pdt - td).days) * 1e6
            if best_cost is None or cost < best_cost:
                best, best_cost = i, cost
        if best is not None:
            used.add(best)
            pairs.append((t, pred[best]))
    return pairs


def _flatten_location(key: str, loc: dict) -> dict:
    out = {}

    def walk(prefix, v):
        if isinstance(v, dict):
            for k, sub in v.items():
                walk(f"{prefix}.{k}", sub)
        else:
            out[normalize(prefix)] = v

    walk(f"property.locations[{key}]", loc)
    return out


def _prf(matched: int, n_truth: int, n_pred: int) -> dict:
    p = matched / n_pred if n_pred else (1.0 if n_truth == 0 else 0.0)
    r = matched / n_truth if n_truth else (1.0 if n_pred == 0 else 0.0)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f, "matched": matched, "truth": n_truth, "predicted": n_pred}


# ----------------------------------------------------------------------------- scoring

@dataclass
class SubmissionScore:
    id: str
    line: str
    difficulty: str
    fields: dict = field(default_factory=dict)  # path -> status
    locations: dict | None = None
    claims: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    defects: list = field(default_factory=list)
    missing_prediction: bool = False

    @property
    def field_accuracy(self) -> float:
        vals = list(self.fields.values())
        return sum(v in ("correct", "abstained") for v in vals) / len(vals) if vals else 1.0

    @property
    def score(self) -> float:
        parts = [self.field_accuracy, self.claims["f1"], self.flags["recall"]]
        if self.locations is not None:
            parts.append(self.locations["f1"])
        return sum(parts) / len(parts)

    def to_json(self) -> dict:
        unk = [v for v in self.fields.values() if v in ("abstained", "hallucinated")]
        return {
            "id": self.id, "line_of_business": self.line, "difficulty": self.difficulty,
            "score": round(self.score, 4), "field_accuracy": round(self.field_accuracy, 4),
            "hallucinations": sum(v == "hallucinated" for v in unk), "unknowable_fields": len(unk),
            "locations": self.locations, "claims": self.claims, "flags": self.flags,
            "defects": self.defects, "fields": self.fields, "missing_prediction": self.missing_prediction,
        }


def score_submission(answer: dict, manifest: dict, pred: dict | None) -> SubmissionScore:
    s = SubmissionScore(answer["submission_id"], manifest["line_of_business"], manifest["difficulty"])
    if pred is None:
        s.missing_prediction = True
        pred = {}
    unscored = {normalize(p) for p in manifest.get("unscored", [])}

    # scalar fields
    truth_flat = flatten(answer)
    pred_core = {k: v for k, v in pred.items() if k != "property"}
    pred_prop = pred.get("property") if isinstance(pred.get("property"), dict) else {}
    pred_core["property"] = {k: v for k, v in pred_prop.items() if k != "locations"} if pred_prop else None
    try:
        pred_flat = flatten(pred_core)
    except (AttributeError, TypeError):
        pred_flat = {}

    if answer.get("property"):
        tl = answer["property"]["locations"]
        pl = [p for p in (pred_prop.get("locations") or []) if isinstance(p, dict)]
        pairs = _match_locations(tl, pl)
        for t, p in pairs:
            pred_flat.update(_flatten_location(location_key(t), p))
        s.locations = _prf(len(pairs), len(tl), len(pl))

    for path, truth in truth_flat.items():
        if path in unscored:
            continue
        p = pred_flat.get(path)
        if is_empty(truth):
            s.fields[path] = "abstained" if is_empty(p) else "hallucinated"
        elif is_empty(p):
            s.fields[path] = "missed"
        else:
            s.fields[path] = "correct" if equal(kind_of(path), truth, p) else "wrong"

    # claims
    tc, pc = answer.get("claims"), pred.get("claims")
    if tc is None:
        ok = pc is None
        v = 1.0 if ok else 0.0
        s.claims = {"precision": v, "recall": v, "f1": v, "matched": 0, "truth": None,
                    "predicted": None if pc is None else len(pc), "unknown_expected": True,
                    "set_ok": ok, "fields_ok": ok, "field_accuracy": v}
    else:
        pc = [p for p in (pc or []) if isinstance(p, dict)]
        pairs = _match_claims(tc, pc)
        checks = []
        for t, p in pairs:
            checks += [equal(MONEY, t["paid"], p.get("paid", 0) or 0),
                       equal(MONEY, t["reserved"], p.get("reserved", 0) or 0),
                       norm_text(t["status"]) == norm_text(p.get("status") or ""),
                       equal("soft", t["cause"], p.get("cause") or ""),
                       equal("soft", t["insurer"], p.get("insurer") or "")]
        s.claims = {**_prf(len(pairs), len(tc), len(pc)), "unknown_expected": False,
                    "set_ok": len(pairs) == len(tc) == len(pc),
                    "field_accuracy": sum(checks) / len(checks) if checks else 1.0}
        s.claims["fields_ok"] = s.claims["set_ok"] and all(checks)
        if pred.get("claims") is None and not tc:
            s.claims.update(precision=0.0, recall=0.0, f1=0.0, set_ok=False)

    # flags
    expected = answer.get("flags") or []
    predicted = [f for f in (pred.get("flags") or []) if isinstance(f, dict)]

    def hit(e, p):
        return str(p.get("type", "")).lower() == e["type"] and covers(e["field"], str(p.get("field", "")))

    found = [e for e in expected if any(hit(e, p) for p in predicted)]
    useful = [p for p in predicted if any(hit(e, p) for e in expected)]
    s.flags = {"recall": len(found) / len(expected) if expected else 1.0,
               "precision": len(useful) / len(predicted) if predicted else 1.0,
               "expected": len(expected), "raised": len(predicted), "matched": len(found),
               "missed": [e for e in expected if e not in found]}

    # defect survival
    for d in manifest.get("defects", []):
        failed = []
        for c in d["checks"]:
            if c == "property.locations#set":
                ok = s.locations is not None and s.locations["matched"] == s.locations["truth"] == s.locations["predicted"]
            elif c == "claims#set":
                ok = s.claims["set_ok"]
            elif c == "claims.fields":
                ok = s.claims["fields_ok"]
            elif c == "claims":
                ok = (tc is None) == (pred.get("claims") is None) and s.claims["set_ok"]
            else:
                n = normalize(c)
                ok = n in unscored or s.fields.get(n) in ("correct", "abstained")
            if not ok:
                failed.append(c)
        flag_ok = d.get("expected_flag") is None or any(hit(d["expected_flag"], p) for p in predicted)
        if not flag_ok:
            failed.append("flag:" + d["expected_flag"]["field"])
        s.defects.append({"code": d["code"], "survived": not failed, "failed": failed})
    return s


def load_prediction(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def score_corpus(corpus: Path, preds: Path, only_predicted: bool = False) -> dict:
    """Score every submission; with only_predicted, skip those without a prediction file."""
    corpus, preds = Path(corpus), Path(preds)
    meta = json.loads((corpus / "corpus.json").read_text())
    subs = []
    for entry in meta["submissions"]:
        if only_predicted and not (preds / f"{entry['id']}.json").exists():
            continue
        d = corpus / "answers" / entry["id"]
        answer = json.loads((d / "answer.json").read_text())
        manifest = json.loads((d / "manifest.json").read_text())
        subs.append(score_submission(answer, manifest, load_prediction(preds / f"{entry['id']}.json")))
    return summarize(subs)


def summarize(subs: list[SubmissionScore]) -> dict:
    def mean(xs):
        xs = list(xs)
        return sum(xs) / len(xs) if xs else None

    statuses = [v for s in subs for v in s.fields.values()]
    unknowable = [v for v in statuses if v in ("abstained", "hallucinated")]
    survival = defaultdict(lambda: [0, 0])
    for s in subs:
        for d in s.defects:
            survival[d["code"]][0] += d["survived"]
            survival[d["code"]][1] += 1
    by_diff = defaultdict(list)
    for s in subs:
        by_diff[s.difficulty].append(s.score)
    locs = [s.locations for s in subs if s.locations is not None]
    return {
        "submissions": len(subs),
        "missing_predictions": sum(s.missing_prediction for s in subs),
        "score": mean(s.score for s in subs),
        "field_accuracy": sum(v in ("correct", "abstained") for v in statuses) / len(statuses) if statuses else None,
        "hallucination_rate": (sum(v == "hallucinated" for v in unknowable) / len(unknowable)) if unknowable else None,
        "unknowable_fields": len(unknowable),
        "location_f1": mean(l["f1"] for l in locs),
        "claims_f1": mean(s.claims["f1"] for s in subs),
        "flag_recall": mean(s.flags["recall"] for s in subs if s.flags["expected"]),
        "flag_precision": mean(s.flags["precision"] for s in subs if s.flags["raised"]),
        "by_difficulty": {k: mean(v) for k, v in by_diff.items()},
        "defect_survival": {k: {"survived": a, "seen": b, "rate": a / b} for k, (a, b) in sorted(survival.items())},
        "per_submission": [s.to_json() for s in subs],
    }


def format_report(r: dict) -> str:
    def pct(v):
        return "  n/a" if v is None else f"{v * 100:5.1f}%"

    lines = [
        f"slipshod score   {pct(r['score'])}   ({r['submissions']} submissions"
        + (f", {r['missing_predictions']} without predictions" if r["missing_predictions"] else "") + ")",
        "",
        f"  field accuracy       {pct(r['field_accuracy'])}",
        f"  hallucination rate   {pct(r['hallucination_rate'])}   (value given where the documents can't support one; "
        f"{r['unknowable_fields']} unknowable fields)",
        f"  location F1          {pct(r['location_f1'])}",
        f"  claims F1            {pct(r['claims_f1'])}",
        f"  flag recall          {pct(r['flag_recall'])}",
        f"  flag precision       {pct(r['flag_precision'])}   (advisory)",
        "",
        "  by difficulty: " + "   ".join(f"{k} {pct(v).strip()}" for k, v in sorted(r["by_difficulty"].items())),
        "",
        "  defect survival (worst first)",
    ]
    rows = sorted(r["defect_survival"].items(), key=lambda kv: (kv[1]["rate"], kv[0]))
    for code, v in rows:
        bar = "#" * round(v["rate"] * 20)
        lines.append(f"    {code:34s} {pct(v['rate'])}  {bar:20s} {v['survived']}/{v['seen']}")
    return "\n".join(lines)


def format_details(r: dict) -> str:
    out = []
    for s in r["per_submission"]:
        bad = {k: v for k, v in s["fields"].items() if v not in ("correct", "abstained")}
        failed = [d for d in s["defects"] if not d["survived"]]
        if not bad and not failed and not s["flags"]["missed"]:
            continue
        out.append(f"\n{s['id']} ({s['line_of_business']}, {s['difficulty']})  score {s['score'] * 100:.1f}%"
                   + ("  [no prediction]" if s["missing_prediction"] else ""))
        for k, v in bad.items():
            out.append(f"    {v:12s} {k}")
        for f in s["flags"]["missed"]:
            out.append(f"    missed flag  {f['type']} {f['field']}")
        for d in failed:
            more = f", +{len(d['failed']) - 3} more" if len(d["failed"]) > 3 else ""
            out.append(f"    tripped      {d['code']}  ({', '.join(d['failed'][:3])}{more})")
    return "\n".join(out)
