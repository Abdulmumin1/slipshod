from __future__ import annotations

import os
import random
from pathlib import Path

import pymupdf as fitz

from ..plans import FormField, FormPlan

INK = (0.08, 0.14, 0.55)
GREY = (0.45, 0.45, 0.45)
LEFT, RIGHT, LABEL_W = 40, 555, 215
BOX_X = LEFT + LABEL_W

_HAND_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "C:/Windows/Fonts/segoepr.ttf",
]


def hand_font() -> str | None:
    for p in [os.environ.get("SLIPSHOD_HAND_FONT"), *_HAND_CANDIDATES]:
        if p and Path(p).exists():
            return p
    return None


DECLARATION = (
    "I/We declare that the statements and particulars in this proposal are true and that I/we have not "
    "misstated or suppressed any material fact. I/We agree that this proposal shall be the basis of the "
    "contract with the insurer. I/We understand that failure to make a fair presentation of the risk may "
    "result in the policy being avoided or claims reduced or not paid."
)


class _Writer:
    def __init__(self, plan: FormPlan, rng: random.Random):
        self.plan, self.rng = plan, rng
        self.doc = fitz.open()
        self.font = hand_font()
        self.page: fitz.Page | None = None
        self.y = 0.0
        self.widget_n = 0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=595, height=842)
        if self.font:
            self.page.insert_font(fontname="hand", fontfile=self.font)
        n = len(self.doc)
        self.page.insert_text((LEFT, 822), f"{self.plan.title}  |  Page {n}", fontsize=7, color=GREY)
        self.y = 50

    def ensure(self, h: float) -> None:
        if self.y + h > 790:
            self._new_page()

    # --- value writing ---------------------------------------------------------------

    def write_value(self, x: float, y: float, text: str, size: float = 11) -> float:
        if self.plan.handwritten:
            jitter = self.rng.uniform(-1.5, 1.5)
            fontname = "hand" if self.font else "tiit"
            self.page.insert_text((x, y + jitter), text, fontname=fontname, fontsize=size + 1, color=INK)
            return fitz.get_text_length(text, fontname="tiit", fontsize=size + 1) * (1.05 if self.font else 1.0)
        self.page.insert_text((x, y), text, fontname="helv", fontsize=size - 1)
        return fitz.get_text_length(text, fontname="helv", fontsize=size - 1)

    def text_widget(self, rect: fitz.Rect, value: str) -> None:
        w = fitz.Widget()
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_name = f"field_{self.widget_n}"
        w.field_value = value
        w.rect = rect
        w.text_fontsize = 9
        w.border_width = 0
        self.widget_n += 1
        self.page.add_widget(w)

    def check_widget(self, rect: fitz.Rect, on: bool) -> None:
        w = fitz.Widget()
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w.field_name = f"check_{self.widget_n}"
        w.rect = rect
        w.field_value = on
        self.widget_n += 1
        self.page.add_widget(w)

    def tick(self, box: fitz.Rect) -> None:
        if self.plan.handwritten:
            p1 = fitz.Point(box.x0 + 1, box.y0 + 5 + self.rng.uniform(-1, 1))
            p2 = fitz.Point(box.x0 + 4, box.y1 - 0.5)
            p3 = fitz.Point(box.x1 + 3 + self.rng.uniform(-1, 2), box.y0 - 3)
            self.page.draw_polyline([p1, p2, p3], color=INK, width=1.6)
        else:
            self.page.insert_text((box.x0 + 1.5, box.y1 - 1.5), "X", fontname="hebo", fontsize=9)

    # --- layout ---------------------------------------------------------------------

    def header(self) -> None:
        p = self.page
        p.insert_text((LEFT, self.y), self.plan.issuer, fontname="hebo", fontsize=15)
        self.y += 20
        p.insert_text((LEFT, self.y), self.plan.title, fontname="helv", fontsize=12)
        self.y += 8
        p.draw_line((LEFT, self.y), (RIGHT, self.y), color=GREY, width=0.8)
        self.y += 14
        p.insert_text((LEFT, self.y), "Please complete in BLOCK CAPITALS. All questions must be answered. "
                      "If a question does not apply, write N/A.", fontsize=7.5, color=GREY)
        self.y += 18

    def section(self, title: str) -> None:
        self.ensure(46)
        self.page.draw_rect(fitz.Rect(LEFT, self.y, RIGHT, self.y + 16), color=None, fill=(0.85, 0.87, 0.9))
        self.page.insert_text((LEFT + 4, self.y + 11.5), title, fontname="hebo", fontsize=10)
        self.y += 24

    def label(self, text: str, height: float) -> None:
        self.page.insert_textbox(fitz.Rect(LEFT + 4, self.y + 2, BOX_X - 6, self.y + height + 12), text, fontsize=8.5)

    @staticmethod
    def label_height(text: str) -> float:
        width = BOX_X - LEFT - 14
        lines = 1 + int(fitz.get_text_length(text, fontname="helv", fontsize=8.5) // width)
        return max(22.0, lines * 11 + 2)

    def text_field(self, f: FormField) -> None:
        h = 22
        lh = self.label_height(f.label)
        self.ensure(lh + 6)
        self.label(f.label, lh)
        box = fitz.Rect(BOX_X, self.y, RIGHT, self.y + h)
        self.page.draw_rect(box, color=GREY, width=0.6)
        value = f.value or ""
        extra = lh - h
        if self.plan.handwritten and self.rng.random() < 0.6:
            value = value.upper()
        x = BOX_X + 5
        if f.correction is not None:
            old = f.correction.upper() if self.plan.handwritten else f.correction
            width = self.write_value(x, self.y + 15, old)
            ly = self.y + 11 + self.rng.uniform(-1, 1)
            self.page.draw_line((x - 2, ly), (x + width + 2, ly + self.rng.uniform(-1.5, 1.5)), color=INK, width=1.3)
            self.page.draw_line((x - 2, ly + 2), (x + width + 2, ly + 1), color=INK, width=1.1)
            x += width + 10
            fontname = "hand" if self.font else "tiit"
            self.page.insert_text((x, self.y + 15), value or "", fontname=fontname, fontsize=12, color=INK)
            x += fitz.get_text_length(value or "", fontname="tiit", fontsize=12) + 8
            initials = "".join(part[0] for part in (self.plan.signed_name or "X X").split())
            self.page.insert_text((x, self.y + 18), initials, fontname=fontname, fontsize=7, color=INK)
        elif self.plan.fillable:
            self.text_widget(fitz.Rect(BOX_X + 2, self.y + 2, RIGHT - 2, self.y + h - 2), f.value or "")
        elif value:
            self.write_value(x, self.y + 15, value)
        self.y += h + 6 + extra

    def choice_field(self, f: FormField) -> None:
        h = self.label_height(f.label)
        self.ensure(h + 6)
        self.label(f.label, h)
        x = BOX_X + 5
        for opt in f.options:
            box = fitz.Rect(x, self.y + 6, x + 10, self.y + 16)
            self.page.draw_rect(box, color=(0, 0, 0), width=0.7)
            self.page.insert_text((x + 14, self.y + 15), opt, fontsize=9)
            if self.plan.fillable:
                self.check_widget(box, opt in f.ticked)
            elif opt in f.ticked:
                self.tick(box)
            x += 70
        self.y += h + 6

    def declaration(self) -> None:
        self.section("5. Declaration")
        self.ensure(150)
        self.page.insert_textbox(fitz.Rect(LEFT + 4, self.y, RIGHT, self.y + 60), DECLARATION, fontsize=8)
        self.y += 66
        for lab in ("Signature", "Name", "Date"):
            self.page.insert_text((LEFT + 4, self.y + 14), lab, fontsize=9)
            self.page.draw_line((BOX_X, self.y + 18), (RIGHT - 120, self.y + 18), color=GREY, width=0.6)
            if self.plan.signed_date is not None:
                fontname = "hand" if self.font else "tiit"
                if lab == "Signature":
                    self.page.insert_text((BOX_X + 8, self.y + 15), self.plan.signed_name or "", fontname=fontname,
                                          fontsize=17, color=INK)
                elif lab == "Name":
                    self.write_value(BOX_X + 5, self.y + 15, (self.plan.signed_name or "").upper())
                else:
                    self.page.insert_text((BOX_X + 5, self.y + 15), self.plan.signed_date.strftime("%d/%m/%y"),
                                          fontname=fontname, fontsize=12, color=INK)
            self.y += 26


def render_form(plan: FormPlan, seed: int) -> bytes:
    w = _Writer(plan, random.Random(seed))
    w.header()
    for s in plan.sections:
        w.section(s.title)
        for f in s.fields:
            (w.text_field if f.kind == "text" else w.choice_field)(f)
    w.declaration()
    w.doc.set_metadata({"title": plan.title, "author": plan.issuer, "creationDate": "", "modDate": ""})
    return w.doc.tobytes(garbage=3, deflate=True, no_new_id=True)
