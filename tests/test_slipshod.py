import copy
import email
import io
import json
from datetime import date
from email import policy

import openpyxl
import pymupdf
import pytest

from slipshod.defects import CODES, REGISTRY
from slipshod.generate import generate_corpus, generate_submission
from slipshod.paths import covers, normalize
from slipshod.refdata import CONSTRUCTION
from slipshod.score import score_corpus, score_submission

AS_OF = date(2026, 11, 15)
CONSTRUCTIONS = {c for c, _ in CONSTRUCTION}


def sub(line="property", difficulty="medium", seed=1, only=None):
    return generate_submission("SUB-T", line, difficulty, seed, AS_OF, only)


def test_deterministic():
    a, b = sub(seed=42, difficulty="hard"), sub(seed=42, difficulty="hard")
    assert a.answer == b.answer
    assert a.manifest == b.manifest
    eml = [k for k in a.files if k.endswith(".eml")]
    assert all(a.files[k] == b.files[k] for k in eml)


@pytest.mark.parametrize("spec", REGISTRY, ids=lambda s: s.code)
def test_every_defect_can_fire(spec):
    fired = False
    for seed in range(30):
        s = sub(spec.lines[0], seed=seed, only=[spec.code])
        if any(d["code"] == spec.code for d in s.manifest["defects"]):
            fired = True
            # the oracle must still be perfect, whatever the defect did
            r = score_submission(s.answer, s.manifest, copy.deepcopy(s.answer))
            assert r.score == 1.0 and all(d["survived"] for d in r.defects)
            break
    assert fired, f"{spec.code} never applied"


def test_oracle_is_perfect_and_naive_is_not(tmp_path):
    generate_corpus(tmp_path, 12, 3, ["property", "cyber", "cargo"], "mixed", AS_OF)
    preds = tmp_path / "preds"
    preds.mkdir()
    for d in (tmp_path / "answers").iterdir():
        (preds / f"{d.name}.json").write_text((d / "answer.json").read_text())
    assert score_corpus(tmp_path, preds)["score"] == 1.0
    empty = tmp_path / "empty"
    empty.mkdir()
    r = score_corpus(tmp_path, empty)
    assert r["score"] < 0.3 and r["missing_predictions"] == 12


def _text(files, suffix):
    out = ""
    for name, data in files.items():
        if name.endswith(suffix):
            out += "\n".join(p.get_text() for p in pymupdf.open("pdf", data))
    return out


def test_clean_documents_contain_the_answers():
    for line in ("property", "cyber", "cargo"):
        for seed in range(5):
            s = sub(line, "clean", seed)
            a = s.answer
            pdf_text = _text(s.files, ".pdf")
            assert a["insured"]["name"] in pdf_text
            assert a["insured"]["address"]["postcode"] in pdf_text
            assert f"{a['insured']['annual_revenue']:,}" in pdf_text
            for c in a["claims"]:
                assert date.fromisoformat(c["date_of_loss"]).strftime("%d/%m/%Y") in pdf_text
            if line == "property":
                xlsx = next(v for k, v in s.files.items() if k.endswith(".xlsx"))
                wb = openpyxl.load_workbook(io.BytesIO(xlsx))
                cells = {c for ws in wb for row in ws.iter_rows(values_only=True) for c in row}
                for loc in a["property"]["locations"]:
                    assert loc["address"]["postcode"] in cells
                    assert loc["buildings_sum_insured"] in cells


def test_withheld_values_are_really_gone():
    for seed in range(15):
        s = sub("property", seed=seed, only=["sov.missing_construction", "sov.combined_values", "sov.duplicate_row"])
        xlsx = next(v for k, v in s.files.items() if k.endswith(".xlsx"))
        wb = openpyxl.load_workbook(io.BytesIO(xlsx))
        for loc in s.answer["property"]["locations"]:
            pc = loc["address"]["postcode"]
            rows = [r for ws in wb for r in ws.iter_rows(values_only=True) if pc in r]
            assert rows
            if loc["construction"] is None:
                assert not any(v in CONSTRUCTIONS for r in rows for v in r)
            if loc["buildings_sum_insured"] is None:
                assert all("incl." in r for r in rows)


def test_missing_loss_run_means_unknown_not_none():
    for seed in range(10):
        s = sub("cyber", seed=seed, only=["claims.loss_run_missing"])
        assert s.answer["claims"] is None
        assert not any("Loss runs" in k for k in s.files)
        main = next(v for k, v in s.files.items() if k.endswith(".eml"))
        body = email.message_from_bytes(main, policy=policy.default).get_body(("plain",)).get_content()
        assert "loss runs" in body
        pred = copy.deepcopy(s.answer)
        pred["claims"] = []
        assert score_submission(s.answer, s.manifest, pred).claims["f1"] == 0.0


def test_scorer_catches_mistakes():
    s = sub("property", "nightmare", 7)
    a, m = s.answer, s.manifest

    p = copy.deepcopy(a)
    if "insured.annual_revenue" not in m["unscored"]:
        p["insured"]["annual_revenue"] = (a["insured"]["annual_revenue"] or 0) + 100_000
        assert score_submission(a, m, p).fields["insured.annual_revenue"] == "wrong"

    p = copy.deepcopy(a)
    p["flags"] = []
    assert score_submission(a, m, p).flags["recall"] == 0.0

    p = copy.deepcopy(a)
    p["property"]["locations"].append(copy.deepcopy(p["property"]["locations"][0]))
    assert score_submission(a, m, p).locations["precision"] < 1.0

    withheld = [k for k, v in score_submission(a, m, a).fields.items() if v == "abstained"]
    assert withheld
    p = copy.deepcopy(a)
    p["proposal_form"]["signed_date"] = "2026-11-01"
    r = score_submission(a, m, p)
    if a["proposal_form"]["signed_date"] is None:
        assert r.fields["proposal_form.signed_date"] == "hallucinated"


def test_lenient_formats():
    s = sub("property", "clean", 2)
    p = copy.deepcopy(s.answer)
    p["insured"]["annual_revenue"] = f"£{s.answer['insured']['annual_revenue']:,}"
    p["policy"]["inception_date"] = date.fromisoformat(s.answer["policy"]["inception_date"]).strftime("%d/%m/%Y")
    p["insured"]["name"] = s.answer["insured"]["name"].upper()
    for loc in p["property"]["locations"]:
        loc["address"]["postcode"] = loc["address"]["postcode"].lower().replace(" ", "")
    assert score_submission(s.answer, s.manifest, p).score == 1.0


def test_paths():
    assert normalize("property.locations[ls11 5qt].Construction") == "property.locations[LS115QT].construction"
    assert covers("property.locations[LS11 5QT]", "property.locations[LS115QT].buildings_sum_insured")
    assert not covers("property.locations[LS11 5QT].construction", "property.locations")
    assert covers("claims", "claims")
    assert not covers("insured.annual_revenue", "insured")


def test_codes_unique():
    assert len(CODES) == len(set(CODES))
    json.dumps([s.code for s in REGISTRY])
