from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

from . import __version__


def _generate(a) -> int:
    from .defects import CODES
    from .generate import LINES, generate_corpus

    lines = [x.strip() for x in a.lines.split(",") if x.strip()]
    bad = [x for x in lines if x not in LINES]
    if bad:
        sys.exit(f"unknown line(s): {', '.join(bad)}. Choose from {', '.join(LINES)}")
    only = [x.strip() for x in a.only.split(",")] if a.only else None
    if only:
        unknown = [c for c in only if c not in CODES]
        if unknown:
            sys.exit(f"unknown defect code(s): {', '.join(unknown)}. See `slipshod defects`.")
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        if not a.force:
            sys.exit(f"{out} is not empty (use --force to overwrite)")
        shutil.rmtree(out)

    def progress(sub):
        codes = ", ".join(d["code"] for d in sub.manifest["defects"]) or "no defects"
        print(f"  {sub.id}  {sub.manifest['line_of_business']:8s} {sub.manifest['difficulty']:9s} {codes}")

    as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()
    meta = generate_corpus(out, a.n, a.seed, lines, a.difficulty, as_of, only, progress)
    print(f"\nWrote {meta['count']} submissions to {out}/")
    print(f"  give your agent:  {out}/inputs/<id>/")
    print(f"  keep hidden:      {out}/answers/<id>/")
    return 0


def _score(a) -> int:
    from .score import format_details, format_report, score_corpus

    report = score_corpus(Path(a.corpus), Path(a.predictions))
    print(format_report(report))
    if a.verbose:
        print(format_details(report))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(f"\nfull report: {a.json}")
    return 0


def _oracle(a) -> int:
    corpus, out = Path(a.corpus), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in sorted((corpus / "answers").iterdir()):
        if (d / "answer.json").exists():
            shutil.copy(d / "answer.json", out / f"{d.name}.json")
            n += 1
    print(f"Copied {n} answer keys to {out}/ (a perfect agent; useful to check your harness)")
    return 0


def _defects(a) -> int:
    from .defects import REGISTRY

    for s in REGISTRY:
        doc = (s.fn.__doc__ or "").strip()
        lines = ",".join(s.lines) if len(s.lines) < 3 else "all"
        print(f"{s.code:34s} [{lines}]")
        if doc:
            print(f"    {doc}")
    return 0


def _explain(a) -> int:
    d = Path(a.corpus) / "answers" / a.id
    m = json.loads((d / "manifest.json").read_text())
    print(f"{a.id}: {m['line_of_business']}, {m['difficulty']}, seed {m['seed']}")
    print("\nInputs:")
    for f in m["inputs"]:
        print(f"  {f}")
    print("\nTraps:")
    for x in m["defects"]:
        flag = f"\n      expect flag: {x['expected_flag']['type']} {x['expected_flag']['field']}" if x["expected_flag"] else ""
        print(f"  - {x['code']}  ({', '.join(x['doc'])})\n      {x['description']}{flag}")
    if m["unscored"]:
        print(f"\nNot scored (genuinely ambiguous): {', '.join(m['unscored'])}")
    return 0


def _baseline(a) -> int:
    from .baseline import run

    print(f"Wrote {run(Path(a.inputs), Path(a.out))} naive-baseline predictions to {a.out}/")
    return 0


def _app(a) -> int:
    try:
        from .app import launch
    except ImportError:
        sys.exit('The web app needs the "app" extra:  pip install "slipshod[app]"')
    launch(port=a.port, share=a.share)
    return 0


def _schema(a) -> int:
    from .schema import BRIEF, SCHEMA

    print(BRIEF if a.brief else json.dumps(SCHEMA, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="slipshod", description="Messy insurance submissions with ground truth.")
    p.add_argument("--version", action="version", version=f"slipshod {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate a corpus")
    g.add_argument("out")
    g.add_argument("-n", type=int, default=30)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--lines", default="property,cyber,cargo")
    g.add_argument("--difficulty", default="mixed", choices=["clean", "easy", "medium", "hard", "nightmare", "mixed"])
    g.add_argument("--only", help="comma-separated defect codes: apply exactly these (where applicable)")
    g.add_argument("--as-of", help="the 'today' of the corpus, YYYY-MM-DD (default: today). Fix it for reproducibility.")
    g.add_argument("--force", action="store_true")
    g.set_defaults(fn=_generate)

    s = sub.add_parser("score", help="score predictions (<predictions>/<id>.json) against a corpus")
    s.add_argument("corpus")
    s.add_argument("predictions")
    s.add_argument("--json", help="write the full report here")
    s.add_argument("-v", "--verbose", action="store_true", help="list every miss per submission")
    s.set_defaults(fn=_score)

    o = sub.add_parser("oracle", help="write the answer keys as predictions (should score 100%%)")
    o.add_argument("corpus")
    o.add_argument("out")
    o.set_defaults(fn=_oracle)

    e = sub.add_parser("explain", help="show the traps planted in one submission")
    e.add_argument("corpus")
    e.add_argument("id")
    e.set_defaults(fn=_explain)

    d = sub.add_parser("defects", help="list the defect catalogue")
    d.set_defaults(fn=_defects)

    sc = sub.add_parser("schema", help="print the output JSON Schema (or --brief for the agent task brief)")
    sc.add_argument("--brief", action="store_true")
    sc.set_defaults(fn=_schema)

    b = sub.add_parser("baseline", help="run the naive baseline agent over <corpus>/inputs")
    b.add_argument("inputs")
    b.add_argument("out")
    b.set_defaults(fn=_baseline)

    w = sub.add_parser("app", help="open the web demo (needs the 'app' extra)")
    w.add_argument("--port", type=int, default=7860)
    w.add_argument("--share", action="store_true", help="create a temporary public gradio.live link")
    w.set_defaults(fn=_app)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
