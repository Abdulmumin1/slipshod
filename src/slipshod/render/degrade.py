"""Make clean PDFs look like they went through a tired office scanner or a phone camera."""

from __future__ import annotations

import io
import random

import pymupdf as fitz
import numpy as np
from PIL import Image, ImageFilter


def _page_image(page: fitz.Page, dpi: int, gray: bool) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY if gray else fitz.csRGB, alpha=False)
    return Image.frombytes("L" if gray else "RGB", (pix.width, pix.height), pix.samples)


def scan(pdf: bytes, rng: random.Random) -> bytes:
    """Rasterise every page: skew, uneven lighting, noise, speckle, blur, heavy JPEG."""
    np_rng = np.random.default_rng(rng.randrange(1 << 32))
    src = fitz.open("pdf", pdf)
    out = fitz.open()
    for page in src:
        img = _page_image(page, rng.choice([110, 130, 150]), gray=True)
        img = img.rotate(rng.uniform(-2.2, 2.2), resample=Image.BICUBIC, expand=True, fillcolor=250)
        a = np.asarray(img).astype(np.float32)
        h, w = a.shape
        a += np.linspace(rng.uniform(-30, 0), rng.uniform(-30, 0), w)[None, :]
        a += np.linspace(rng.uniform(-15, 0), rng.uniform(-15, 0), h)[:, None]
        a += np_rng.normal(0, rng.uniform(5, 13), a.shape)
        n = int(a.size * rng.uniform(0.0002, 0.0012))
        a[np_rng.integers(0, h, n), np_rng.integers(0, w, n)] = np_rng.uniform(0, 80, n)
        edge = rng.randint(4, 18)
        a[:, :edge] *= 0.35  # scanner lid shadow
        if rng.random() < 0.5:  # hole punches
            for cy in (0.3, 0.7):
                yy, xx = np.ogrid[:h, :w]
                mask = (xx - w * 0.04) ** 2 + (yy - h * cy) ** 2 < (w * 0.012) ** 2
                a[mask] = 30
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(28, 55))
        p = out.new_page(width=595, height=842)
        p.insert_image(p.rect, stream=buf.getvalue())
    out.set_metadata({"producer": "Canon iR-ADV C5535", "creationDate": "", "modDate": ""})
    return out.tobytes(garbage=3, deflate=True, no_new_id=True)


def _perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    m = []
    for (x, y), (u, v) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(m, dtype=np.float64)
    b = np.array([c for p in src for c in p], dtype=np.float64)
    return np.linalg.solve(a, b).tolist()


def photo(pdf: bytes, rng: random.Random) -> list[bytes]:
    """Each page as a JPEG phone photo: on a desk, at an angle, with a shadow."""
    np_rng = np.random.default_rng(rng.randrange(1 << 32))
    src = fitz.open("pdf", pdf)
    shots = []
    for page in src:
        doc_img = _page_image(page, 150, gray=False)
        pw, ph = doc_img.size
        W, H = int(pw * 1.25), int(ph * 1.2)
        desk = np.zeros((H, W, 3), dtype=np.float32)
        base = np.array(rng.choice([(120, 90, 60), (90, 90, 95), (150, 130, 105)]), dtype=np.float32)
        desk[:] = base
        desk += np_rng.normal(0, 6, desk.shape)
        background = Image.fromarray(np.clip(desk, 0, 255).astype(np.uint8))

        j = lambda s: rng.uniform(-s, s)  # noqa: E731
        ox, oy = (W - pw) / 2, (H - ph) / 2
        corners = [(ox + j(40), oy + j(30)), (ox + pw + j(40), oy + j(30)),
                   (ox + pw + j(50), oy + ph + j(30)), (ox + j(50), oy + ph + j(30))]
        coeffs = _perspective_coeffs(corners, [(0, 0), (pw, 0), (pw, ph), (0, ph)])
        warped = doc_img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(0, 0, 0))
        mask = Image.new("L", doc_img.size, 255).transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=0)
        background.paste(warped, (0, 0), mask)

        a = np.asarray(background).astype(np.float32)
        yy, xx = np.mgrid[:H, :W]
        cx, cy = rng.uniform(0.2, 0.8) * W, rng.uniform(0.2, 0.8) * H
        light = 1.0 - 0.35 * (np.hypot(xx - cx, yy - cy) / np.hypot(W, H))
        a *= light[..., None]
        if rng.random() < 0.6:  # phone/hand shadow across one corner
            sx = rng.uniform(0.5, 0.9) * W
            a[(xx + yy * 0.6) > sx + H * 0.6] *= 0.7
        a *= np.array([1.0, 0.98, 0.92])  # warm indoor light
        a += np_rng.normal(0, 4, a.shape)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.0)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(55, 75))
        shots.append(buf.getvalue())
    return shots
