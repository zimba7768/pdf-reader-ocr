"""Generate the application icon (icon.ico + icon.png) with Pillow.

Run:  python packaging/make_icon.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "src", "pdf_reader_ocr", "resources")


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256.0

    # paper with folded corner
    x0, y0, x1, y1 = 48 * s, 20 * s, 208 * s, 236 * s
    fold = 48 * s
    paper = [(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)]
    d.polygon(paper, fill=(250, 250, 250, 255), outline=(60, 60, 70, 255))
    d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(200, 200, 205, 255), outline=(60, 60, 70, 255))

    # red "PDF" band
    d.rectangle([x0, 96 * s, x1, 140 * s], fill=(214, 48, 49, 255))
    # text lines (abstract)
    for i, yy in enumerate((56, 72, 160, 176, 192)):
        w = (x1 - x0) * (0.75 if i % 2 else 0.6)
        d.rectangle([x0 + 18 * s, yy * s, x0 + 18 * s + w, (yy + 6) * s], fill=(120, 120, 130, 255))

    # magnifier (OCR)
    cx, cy, r = 176 * s, 196 * s, 34 * s
    lw = max(1, int(8 * s))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 200), outline=(30, 90, 200, 255), width=lw)
    d.line([(cx + r * 0.7, cy + r * 0.7), (cx + r * 1.6, cy + r * 1.6)], fill=(30, 90, 200, 255), width=int(lw * 1.6))
    return img


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(sz) for sz in sizes]
    images[-1].save(os.path.join(OUT_DIR, "icon.png"))
    images[-1].save(os.path.join(OUT_DIR, "icon.ico"), sizes=[(sz, sz) for sz in sizes], append_images=images[:-1])
    print("wrote", OUT_DIR)


if __name__ == "__main__":
    main()
