"""Web demo: generate a submission in the browser, inspect it, reveal the traps, score an agent.

    slipshod app            (local)
    python space/app.py     (Hugging Face Spaces)
"""

from __future__ import annotations

import email
import html
import io
import json
import os
import random
import shutil
import tempfile
import threading
import zipfile
from datetime import date
from email import policy
from pathlib import Path

import gradio as gr
import openpyxl
import pymupdf
from PIL import Image

from . import __version__
from .baseline import run as run_baseline
from .defects import REGISTRY
from .generate import generate_corpus, generate_submission
from .schema import BRIEF, SCHEMA
from .score import format_details, format_report, score_corpus

AS_OF = date(2026, 11, 15)
BENCH_SEED, BENCH_N = 1, 60
WORK = Path(os.environ.get("SLIPSHOD_WORK") or Path(tempfile.gettempdir()) / f"slipshod-{__version__}")
BENCH = WORK / "benchmark"
BENCH_ZIP = WORK / f"slipshod-benchmark-seed{BENCH_SEED}-n{BENCH_N}.zip"
_bench_lock = threading.Lock()


# ----------------------------------------------------------------------------- previews

def _email_text(data: bytes) -> str:
    m = email.message_from_bytes(data, policy=policy.default)
    att = [p.get_filename() for p in m.iter_attachments()]
    head = f"From: {m['From']}\nTo: {m['To']}\nDate: {m['Date']}\nSubject: {m['Subject']}\n"
    if att:
        head += "Attachments: " + ", ".join(att) + "\n"
    return head + "\n" + m.get_body(("plain",)).get_content()


def _pdf_pages(name: str, data: bytes) -> list[tuple[Image.Image, str]]:
    doc = pymupdf.open("pdf", data)
    out = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=80)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        out.append((img, f"{name}  (page {i + 1}/{len(doc)})"))
    return out


def _fmt(cell) -> str:
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "," in (cell.number_format or ""):
        return f"{v:,.0f}"
    return html.escape(str(v))


def _xlsx_html(name: str, data: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    active = wb.active.title
    parts = [f"<h4 style='margin:8px 0'>{html.escape(name)}</h4>"]
    for ws in wb.worksheets:
        tag = " &nbsp;<span style='color:#b45309'>← opens on this tab</span>" if ws.title == active else ""
        parts.append(f"<div style='margin:10px 0 4px'><b>Tab: {html.escape(ws.title)}</b>{tag}</div>")
        parts.append("<div style='overflow-x:auto'><table style='border-collapse:collapse;font-size:12px'>")
        for row in ws.iter_rows():
            if all(c.value is None for c in row):
                parts.append("<tr><td style='height:10px'></td></tr>")
                continue
            r = row[0].row
            hidden = ws.row_dimensions[r].hidden
            style = "opacity:.45;" if hidden else ""
            cells = []
            for c in row:
                st = "border:1px solid #ccc;padding:2px 6px;white-space:nowrap;"
                if c.font and c.font.b:
                    st += "font-weight:600;"
                if c.font and c.font.strike:
                    st += "text-decoration:line-through;"
                if c.fill and c.fill.fgColor and c.fill.fill_type == "solid" and c.fill.fgColor.rgb not in (None, "00000000"):
                    st += f"background:#{str(c.fill.fgColor.rgb)[-6:]};"
                note = f" title='{html.escape(c.comment.text)}'" if c.comment else ""
                mark = " 💬" if c.comment else ""
                cells.append(f"<td style='{st}'{note}>{_fmt(c)}{mark}</td>")
            label = "<td style='color:#b45309;padding-left:6px'>hidden row</td>" if hidden else ""
            parts.append(f"<tr style='{style}'>{''.join(cells)}{label}</tr>")
        parts.append("</table></div>")
    return "".join(parts)


def _zip(files: dict[str, bytes], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return str(path)


def _traps_md(manifest: dict) -> str:
    if not manifest["defects"]:
        return "_No traps: this is a clean submission._"
    lines = []
    for d in manifest["defects"]:
        flag = f"  \n  ↳ a good agent flags **{d['expected_flag']['type']}** on `{d['expected_flag']['field']}`" if d["expected_flag"] else ""
        lines.append(f"- **`{d['code']}`** in _{', '.join(d['doc'])}_  \n  {d['description']}{flag}")
    if manifest["unscored"]:
        lines.append(f"\nNot scored, because the documents genuinely contradict each other: `{'`, `'.join(manifest['unscored'])}`")
    return "\n".join(lines)


def generate_one(line: str, difficulty: str, seed):
    seed = int(seed or 0) or random.randrange(1, 10**6)
    sub = generate_submission("DEMO", line, difficulty, seed, AS_OF)
    emails, gallery, sheets = [], [], []
    for name in sorted(sub.files):
        data = sub.files[name]
        short = name.split("/")[-1]
        if name.endswith(".eml"):
            emails.append(f"===== {short} =====\n{_email_text(data)}")
        elif name.endswith(".pdf"):
            gallery += _pdf_pages(short, data)
        elif name.endswith(".jpg"):
            gallery.append((Image.open(io.BytesIO(data)).convert("RGB"), short))
        elif name.endswith(".xlsx"):
            sheets.append(_xlsx_html(short, data))
    tag = f"{line}-{difficulty}-{seed}"
    inputs_zip = _zip({f"slipshod-{tag}/{k}": v for k, v in sub.files.items()}, WORK / "demo" / f"slipshod-{tag}.zip")
    answer = json.dumps(sub.answer, indent=2)
    answers_zip = _zip({"answer.json": answer.encode(), "manifest.json": json.dumps(sub.manifest, indent=2).encode()},
                       WORK / "demo" / f"slipshod-{tag}-answer.zip")
    summary = (f"**{line.title()}** submission, **{difficulty}**, seed `{seed}`: "
               f"{len(sub.manifest['inputs'])} files, {len(sub.manifest['defects'])} traps planted.")
    return (summary, "\n\n".join(emails),
            gallery,
            "".join(sheets) or "<i>No spreadsheet in this submission (only property risks have a schedule of values).</i>",
            _traps_md(sub.manifest), answer, inputs_zip, answers_zip, seed)


# ----------------------------------------------------------------------------- benchmark

def ensure_benchmark() -> Path:
    with _bench_lock:
        if not (BENCH / "corpus.json").exists():
            if BENCH.exists():
                shutil.rmtree(BENCH)
            generate_corpus(BENCH, BENCH_N, BENCH_SEED, ["property", "cyber", "cargo"], "mixed", AS_OF)
        if not BENCH_ZIP.exists():
            files = {"README.txt": (
                f"slipshod benchmark: {BENCH_N} submissions, seed {BENCH_SEED}, as-of {AS_OF}\n\n"
                "For each folder in inputs/, have your agent write <id>.json (e.g. SUB-0001.json).\n"
                "Zip the JSON files and upload them on the 'Score your agent' tab, or run:\n"
                "  slipshod score <corpus> <predictions_dir>\n\n" + BRIEF).encode(),
                "schema.json": json.dumps(SCHEMA, indent=2).encode()}
            for p in (BENCH / "inputs").rglob("*"):
                if p.is_file():
                    files[f"inputs/{p.relative_to(BENCH / 'inputs')}"] = p.read_bytes()
            _zip(files, BENCH_ZIP)
    return BENCH


def benchmark_download():
    ensure_benchmark()
    return str(BENCH_ZIP)


BULK_MAX = 100


def generate_bulk(n, lines, difficulty, seed, only, progress=gr.Progress()):
    n = max(1, min(int(n or 1), BULK_MAX))
    lines = [x for x in ("property", "cyber", "cargo") if x in (lines or [])]
    if not lines:
        raise gr.Error("Pick at least one line of business.")
    seed = int(seed or 0) or random.randrange(1, 10**6)
    only = list(only or []) or None
    if only:
        applicable = {c for s in REGISTRY if s.code in only for c in s.lines}
        lines = [x for x in lines if x in applicable] or lines

    tag = f"slipshod-n{n}-{difficulty}-seed{seed}"
    out = WORK / "bulk" / next(tempfile._get_candidate_names()) / tag
    done = [0]

    def tick(sub):
        done[0] += 1
        progress(done[0] / n, desc=f"Generated {done[0]}/{n}")

    progress(0, desc="Starting")
    meta = generate_corpus(out, n, seed, lines, difficulty, AS_OF, only, tick)
    readme = (
        f"slipshod corpus: {n} submissions, lines={','.join(lines)}, difficulty={difficulty}, seed={seed}, as-of {AS_OF}\n"
        + (f"traps: {', '.join(only)}\n" if only else "")
        + "\ninputs/<id>/   give this to your agent\n"
        "answers/<id>/  the answer key (answer.json) and the traps planted (manifest.json)\n\n"
        "Score predictions (<id>.json per submission) with:\n"
        f"  slipshod score {tag} <predictions_dir>\n\n"
        f"Regenerate exactly with:\n  slipshod generate {tag} -n {n} --seed {seed} --lines {','.join(lines)} "
        f"--difficulty {difficulty} --as-of {AS_OF}" + (f" --only {','.join(only)}" if only else "") + "\n\n" + BRIEF)
    files = {f"{tag}/README.txt": readme.encode(), f"{tag}/schema.json": json.dumps(SCHEMA, indent=2).encode()}
    for p in out.rglob("*"):
        if p.is_file():
            files[f"{tag}/{p.relative_to(out)}"] = p.read_bytes()
    zip_path = _zip(files, out.parent / f"{tag}.zip")
    shutil.rmtree(out)

    counts: dict[str, int] = {}
    for s in meta["submissions"]:
        for code in s["defects"]:
            counts[code] = counts.get(code, 0) + 1
    by_line = {x: sum(s["line_of_business"] == x for s in meta["submissions"]) for x in lines}
    summary = (f"**{n} submissions** ({', '.join(f'{v} {k}' for k, v in by_line.items())}), seed `{seed}`, "
               f"{sum(counts.values())} traps planted in total.\n\n"
               + "\n".join(f"- `{k}` × {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    return zip_path, summary


def _collect_predictions(paths: list[str], dest: Path) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    n = 0
    for p in paths or []:
        p = Path(p)
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    name = Path(info.filename).name
                    if name.endswith(".json") and name.startswith("SUB-"):
                        (dest / name).write_bytes(z.read(info))
                        n += 1
        elif p.suffix == ".json":
            name = p.name
            if not name.startswith("SUB-"):  # gradio may rename uploads; fall back to the id inside
                try:
                    name = json.loads(p.read_text()).get("submission_id", name) + ".json"
                except (json.JSONDecodeError, AttributeError):
                    continue
            shutil.copy(p, dest / name)
            n += 1
    return n


def score_upload(files):
    bench = ensure_benchmark()
    dest = WORK / "uploads" / next(tempfile._get_candidate_names())
    n = _collect_predictions([f if isinstance(f, str) else f.name for f in (files or [])], dest)
    if n == 0:
        return "No predictions found. Upload a .zip of SUB-XXXX.json files, or the .json files themselves.", ""
    report = score_corpus(bench, dest, only_predicted=True)
    note = f"Scored the {n} submissions you uploaded (out of {BENCH_N}).\n\n" if n < BENCH_N else ""
    return note + format_report(report), format_details(report).strip()


def score_baseline():
    bench = ensure_benchmark()
    preds = WORK / "baseline-preds"
    if not preds.exists():
        run_baseline(bench / "inputs", preds)
    report = score_corpus(bench, preds)
    return ("Naive baseline: reads PDF text layers and the active spreadsheet tab, trusts everything, "
            "never flags.\n\n" + format_report(report), format_details(report).strip())


# ----------------------------------------------------------------------------- UI

INTRO = """
# slipshod
**Messy insurance broking submissions, with an answer key that knows what's unknowable.**

Each submission is a client renewal email with attachments: a schedule of values, a proposal form and loss runs.
Each one has realistic traps planted, such as last year's spreadsheet tab, a scanned hand-filled form, a sister
company's claims, or an "attached" loss run that isn't there. Every trap is recorded, together with the answer a careful broker would reach.
"""

CSS = ".gallery-item img { object-fit: contain !important; }"


def build() -> gr.Blocks:
    with gr.Blocks(title="slipshod: messy insurance submissions with ground truth") as demo:
        gr.Markdown(INTRO)
        with gr.Tab("1 · Generate a submission"):
            with gr.Row():
                line = gr.Dropdown(["property", "cyber", "cargo"], value="property", label="Line of business")
                difficulty = gr.Radio(["clean", "easy", "medium", "hard", "nightmare"], value="hard", label="Difficulty")
                seed = gr.Number(value=7, precision=0, label="Seed (0 = random)")
            go = gr.Button("Generate", variant="primary")
            summary = gr.Markdown()
            with gr.Row():
                dl_inputs = gr.File(label="Download the submission (what an agent gets)")
                dl_answer = gr.File(label="Download the answer key")
            with gr.Tab("Email thread"):
                emails = gr.Textbox(lines=28, max_lines=60, show_label=False, interactive=False)
            with gr.Tab("Documents"):
                gallery = gr.Gallery(columns=3, height=620, object_fit="contain", show_label=False)
            with gr.Tab("Spreadsheet"):
                sheet = gr.HTML()
            with gr.Accordion("Reveal the traps and the answer key", open=False):
                traps = gr.Markdown()
                answer = gr.Code(language="json", label="answer.json")
            outputs = [summary, emails, gallery, sheet, traps, answer, dl_inputs, dl_answer, seed]
            go.click(generate_one, [line, difficulty, seed], outputs)
            demo.load(generate_one, [line, difficulty, seed], outputs)

        with gr.Tab("2 · Generate in bulk"):
            gr.Markdown(
                f"Build your own corpus of up to {BULK_MAX} submissions. You get one zip with `inputs/` (for your agent), "
                "`answers/` (answer keys plus the traps planted), the schema, and the exact command to regenerate it. "
                "For bigger corpora, use the CLI: `slipshod generate corpus -n 1000`.")
            with gr.Row():
                b_n = gr.Slider(1, BULK_MAX, value=30, step=1, label="Number of submissions")
                b_seed = gr.Number(value=0, precision=0, label="Seed (0 = random)")
            with gr.Row():
                b_lines = gr.CheckboxGroup(["property", "cyber", "cargo"], value=["property", "cyber", "cargo"],
                                           label="Lines of business")
                b_diff = gr.Radio(["clean", "easy", "medium", "hard", "nightmare", "mixed"], value="mixed",
                                  label="Difficulty")
            b_only = gr.Dropdown([s.code for s in REGISTRY], multiselect=True, value=[],
                                 label="Only these traps (optional; overrides difficulty)")
            b_go = gr.Button("Generate corpus", variant="primary")
            b_file = gr.File(label="Corpus (inputs + answers)")
            b_summary = gr.Markdown()
            b_go.click(generate_bulk, [b_n, b_lines, b_diff, b_seed, b_only], [b_file, b_summary])

        with gr.Tab("3 · Score your agent"):
            gr.Markdown(
                f"**The benchmark:** {BENCH_N} submissions (seed {BENCH_SEED}) across property, cyber and cargo, at mixed difficulty.\n\n"
                "1. Download it and run your agent on every folder in `inputs/`.\n"
                "2. Write one `SUB-XXXX.json` per submission (the schema and task brief are in the zip and below).\n"
                "3. Upload a zip of the JSON files. You'll get accuracy, the hallucination rate, flag recall, and which traps caught your agent.")
            with gr.Row():
                bench_btn = gr.Button("Prepare benchmark download")
                bench_file = gr.File(label="Benchmark (inputs only)")
            bench_btn.click(benchmark_download, None, bench_file)
            uploads = gr.File(file_count="multiple", file_types=[".zip", ".json"], label="Your predictions (.zip or .json files)")
            with gr.Row():
                score_btn = gr.Button("Score my predictions", variant="primary")
                base_btn = gr.Button("Show an example: score the naive baseline")
            report = gr.Code(label="Report", language=None, lines=20, max_lines=50)
            with gr.Accordion("Every miss, per submission", open=False):
                details = gr.Code(language=None, lines=20, max_lines=30, show_label=False)
            score_btn.click(score_upload, uploads, [report, details])
            base_btn.click(score_baseline, None, [report, details])
            with gr.Accordion("Output schema and agent brief", open=False):
                gr.Code(BRIEF, language=None, label="Task brief (paste into your prompt)")
                gr.Code(json.dumps(SCHEMA, indent=2), language="json", label="JSON Schema")

        with gr.Tab("About"):
            gr.Markdown(
                "**Why:** real broking submissions are confidential, and clean synthetic ones teach you nothing. "
                "slipshod plants realistic mess and keeps an honest answer key. Every non-null answer can be derived from "
                "the documents, unknowable values are `null` and expected to be flagged, and genuine contradictions are "
                "left unscored but must be flagged.\n\n"
                "**Run it locally:** `uvx --from git+https://github.com/Abdulmumin1/slipshod slipshod generate corpus -n 30`\n\n"
                "Source, the full defect catalogue and design notes are on "
                "[GitHub](https://github.com/Abdulmumin1/slipshod). All names, companies and insurers are fictional.")
    return demo


def launch(port: int = 7860, share: bool = False, server_name: str | None = None) -> None:
    threading.Thread(target=ensure_benchmark, daemon=True).start()
    build().launch(server_port=port, share=share, server_name=server_name, css=CSS,
                   allowed_paths=[str(WORK)])
