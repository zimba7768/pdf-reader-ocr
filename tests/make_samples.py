"""Create sample PDFs for manual and automated testing.

Writes into tests/samples/:
  text.pdf      - 3 pages of real text with an outline
  scan.pdf      - 2 pages that are only images (simulated scans), no text layer
  scan_rot.pdf  - 1 image page with /Rotate 90
"""
from __future__ import annotations

import os

import pymupdf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "samples")

SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "PDF Reader OCR turns scanned pages into searchable text.",
    "Tesseract recognises printed characters with high accuracy.",
    "Invoice number 48213 was issued on 3 November 2026.",
]


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_text_pdf(path: str) -> None:
    doc = pymupdf.open()
    toc = []
    for i in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 90), f"Chapter {i + 1}", fontsize=24, fontname="helv")
        y = 140
        for s in SENTENCES:
            page.insert_text((72, y), f"{s} (page {i + 1})", fontsize=12, fontname="helv")
            y += 24
        toc.append([1, f"Chapter {i + 1}", i + 1])
    doc.set_toc(toc)
    doc.save(path)
    doc.close()


def scan_image(label: str, dpi: int = 200) -> Image.Image:
    w, h = int(8.27 * dpi), int(11.69 * dpi)
    img = Image.new("RGB", (w, h), (252, 251, 247))
    d = ImageDraw.Draw(img)
    big, normal = _font(int(dpi * 0.3)), _font(int(dpi * 0.16))
    d.text((dpi, dpi), label, fill=(20, 20, 20), font=big)
    y = int(dpi * 1.8)
    for s in SENTENCES:
        d.text((dpi, y), s, fill=(30, 30, 30), font=normal)
        y += int(dpi * 0.35)
    return img


def make_scan_pdf(path: str, pages: int = 2, rotate: int = 0) -> None:
    doc = pymupdf.open()
    for i in range(pages):
        img = scan_image(f"Scanned page {i + 1}")
        tmp = os.path.join(OUT, f"_tmp_{i}.png")
        img.save(tmp)
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, filename=tmp)
        if rotate:
            page.set_rotation(rotate)
        os.remove(tmp)
    doc.save(path)
    doc.close()


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    make_text_pdf(os.path.join(OUT, "text.pdf"))
    make_scan_pdf(os.path.join(OUT, "scan.pdf"))
    make_scan_pdf(os.path.join(OUT, "scan_rot.pdf"), pages=1, rotate=90)
    print("samples written to", OUT)


if __name__ == "__main__":
    main()
