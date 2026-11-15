"""Generate submissions: truth -> plans -> defects -> files + answer key."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import __version__
from .defects import Ctx, choose
from .model import claim_answer, risk_to_answer
from .paths import set_path
from .plans import Doc, build_form, build_lossruns, build_main_email, build_sov
from .render.degrade import photo, scan
from .render.email import email_text, render_eml
from .render.form import render_form
from .render.lossrun import render_lossrun
from .render.sov import render_sov
from .truth import generate_risk

LINES = ("property", "cyber", "cargo")
MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@dataclass
class Submission:
    id: str
    files: dict[str, bytes]  # relative path -> content
    answer: dict
    manifest: dict


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-. ()&]+", "", name).strip()


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def generate_submission(sub_id: str, line: str, difficulty: str, seed: int, as_of: date,
                        only: list[str] | None = None) -> Submission:
    rng = random.Random(seed)
    risk = generate_risk(rng, sub_id, line, as_of)
    year = risk.inception.year
    short = risk.insured.name.split()[0]

    docs: dict[str, Doc] = {}
    if line == "property":
        docs["sov"] = Doc("sov", rng.choice([
            f"SOV {year} FINAL v3.xlsx", "Schedule of values (2).xlsx", "property schedule - updated.xlsx",
            f"{short} SOV {year}.xlsx",
        ]), build_sov(risk, rng), casual_name=rng.choice(["the updated schedule", "the property list", "the SOV"]))
    docs["form"] = Doc("form", rng.choice(["Proposal form - signed.pdf", "proposal.pdf", f"{short} proposal form.pdf"]),
                       build_form(risk, rng), casual_name=rng.choice(["the signed proposal form", "the form, signed"]))
    for i, lr in enumerate(build_lossruns(risk)):
        docs[f"lossrun:{i}"] = Doc(
            f"lossrun:{i}", f"Loss runs {lr.insurer.split()[0]} {lr.period_from.year}-{lr.period_to.year}.pdf", lr,
            casual_name=f"the loss runs from {lr.insurer.split()[0]}")
    email = build_main_email(risk, rng, list(docs.values()))
    ctx = Ctx(risk, rng, docs, [email])

    defects = []
    for spec in choose(line, difficulty, rng, only):
        d = spec.fn(ctx)
        if d is not None:
            defects.append(d)

    # ---- answer key
    answer = risk_to_answer(risk)
    for path in sorted(ctx.withheld):
        set_path(answer, path, None)
    for path, value in ctx.overrides.items():
        set_path(answer, path, value)
    if ctx.claims_unknown:
        answer["claims"] = None
    else:
        answer["claims"] = [claim_answer(c) for c in ctx.visible_claims()]
    answer["flags"] = ctx.flags

    # ---- render documents
    files: dict[str, bytes] = {}
    doc_files: dict[str, list[str]] = {}
    attach_payloads: dict[str, list[tuple[str, bytes, str]]] = {}
    photo_n = rng.randint(2000, 8999)
    for key, doc in docs.items():
        plan = doc.plan
        if key == "sov":
            outputs = [(doc.filename, render_sov(plan, email.sent - timedelta(hours=1)))]
        elif key == "form":
            pdf = render_form(plan, rng.randrange(1 << 30))
            if plan.degrade == "scan":
                outputs = [(f"SCAN_{risk.as_of:%Y%m%d}_{rng.randint(1000, 9999)}.pdf", scan(pdf, rng))]
            else:
                outputs = [(doc.filename, pdf)]
        else:
            pdf = render_lossrun(plan)
            if plan.degrade == "scan":
                outputs = [(doc.filename.replace(".pdf", " (scan).pdf"), scan(pdf, rng))]
            elif plan.degrade == "photo":
                outputs = []
                for shot in photo(pdf, rng):
                    outputs.append((f"IMG_{photo_n}.jpg", shot))
                    photo_n += 1
            else:
                outputs = [(doc.filename, pdf)]
        outputs = [(_safe(n), data) for n, data in outputs]
        doc_files[key] = [n for n, _ in outputs]
        if doc.attached:
            attach_payloads[key] = [(n, data, MIME[Path(n).suffix]) for n, data in outputs]
            for n, data in outputs:
                files[f"attachments/{n}"] = data

    for em in ctx.emails:
        mentioned = [docs[k].casual_name for k in em.mention_attachments if k in docs]
        sentence = ""
        if mentioned:
            sentence = rng.choice(["I've attached {x}.", "Attached are {x}.", "Please find attached {x}."]).format(x=_join(mentioned))
        payload = [p for k in em.attachments if k in attach_payloads for p in attach_payloads[k]]
        files[em.filename] = render_eml(em, email_text(em, sentence), payload)

    def doc_ref(key: str) -> list[str]:
        if key == "email":
            return [email.filename]
        if key == "lossrun":
            return [f for k, fs in doc_files.items() if k.startswith("lossrun:") and k != "lossrun:sister" for f in fs]
        return doc_files.get(key, [key])

    manifest = {
        "submission_id": sub_id,
        "line_of_business": line,
        "difficulty": difficulty,
        "seed": seed,
        "as_of": as_of.isoformat(),
        "generator": f"slipshod {__version__}",
        "inputs": sorted(files),
        "documents": {k: {"files": v, "attached": docs[k].attached} for k, v in doc_files.items()},
        "defects": [{**d.to_json(), "doc": doc_ref(d.doc)} for d in defects],
        "unscored": sorted(ctx.unscored),
    }
    return Submission(sub_id, files, answer, manifest)


DIFFICULTY_CYCLE = ("easy", "medium", "hard", "medium", "hard", "nightmare")


def generate_corpus(out: Path, n: int, seed: int, lines: list[str], difficulty: str, as_of: date,
                    only: list[str] | None = None, progress=None) -> dict:
    out = Path(out)
    index = []
    for i in range(n):
        sub_id = f"SUB-{i + 1:04d}"
        sub_seed = random.Random(f"slipshod:{seed}:{i}").randrange(1 << 31)
        line = lines[i % len(lines)]
        diff = DIFFICULTY_CYCLE[(i // len(lines)) % len(DIFFICULTY_CYCLE)] if difficulty == "mixed" else difficulty
        sub = generate_submission(sub_id, line, diff, sub_seed, as_of, only)
        in_dir = out / "inputs" / sub_id
        for rel, data in sub.files.items():
            p = in_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        ans_dir = out / "answers" / sub_id
        ans_dir.mkdir(parents=True, exist_ok=True)
        (ans_dir / "answer.json").write_text(json.dumps(sub.answer, indent=2) + "\n")
        (ans_dir / "manifest.json").write_text(json.dumps(sub.manifest, indent=2) + "\n")
        index.append({"id": sub_id, "line_of_business": line, "difficulty": diff,
                      "defects": [d["code"] for d in sub.manifest["defects"]]})
        if progress:
            progress(sub)
    meta = {"generator": f"slipshod {__version__}", "seed": seed, "as_of": as_of.isoformat(),
            "count": n, "submissions": index}
    (out / "corpus.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta
