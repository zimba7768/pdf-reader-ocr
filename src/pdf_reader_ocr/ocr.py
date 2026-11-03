"""OCR support built on Tesseract via pytesseract.

Pipeline:
  1. render a page to an image at *dpi*
  2. run Tesseract (TSV output) to get words with bounding boxes + confidence
  3. optionally write the words back as an *invisible* text layer so the PDF
     becomes searchable / selectable in any reader
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field

import pymupdf
from PySide6.QtCore import QThread, Signal

from pdf_reader_ocr.document import Document


@dataclass
class OcrWord:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float


@dataclass
class OcrPageResult:
    page: int
    text: str
    words: list[OcrWord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# locating Tesseract
# ---------------------------------------------------------------------------
def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def candidate_tesseract_paths() -> list[str]:
    names = ["tesseract.exe" if os.name == "nt" else "tesseract"]
    dirs = [
        os.path.join(_app_dir(), "tesseract"),
        os.path.join(getattr(sys, "_MEIPASS", _app_dir()), "tesseract"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tesseract-OCR"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Tesseract-OCR"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR"),
    ]
    return [os.path.join(d, n) for d in dirs for n in names if d]


def find_tesseract(custom: str = "") -> str | None:
    if custom and os.path.isfile(custom):
        return custom
    for p in candidate_tesseract_paths():
        if os.path.isfile(p):
            return p
    return shutil.which("tesseract")


def configure_tesseract(exe: str) -> None:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = exe
    tessdata = os.path.join(os.path.dirname(exe), "tessdata")
    if os.path.isdir(tessdata) and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = tessdata


def available_languages() -> list[str]:
    import pytesseract

    try:
        langs = pytesseract.get_languages(config="")
    except Exception:
        return ["eng"]
    return sorted(l for l in langs if l != "osd") or ["eng"]


def tesseract_version() -> str:
    import pytesseract

    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# OCR of a single page
# ---------------------------------------------------------------------------
def ocr_page(document: Document, pno: int, lang: str = "eng", dpi: int = 300) -> OcrPageResult:
    import pytesseract

    img, scale = document.render_pil(pno, dpi)
    with document.lock:
        derot = document.page(pno).derotation_matrix
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)

    words: list[OcrWord] = []
    lines: list[str] = []
    current: list[str] = []
    last_key = None
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != last_key:
            if current:
                lines.append(" ".join(current))
                current = []
            if last_key is not None and key[:2] != last_key[:2]:
                lines.append("")
            last_key = key
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        left, top = data["left"][i], data["top"][i]
        width, height = data["width"][i], data["height"][i]
        rect = pymupdf.Rect(left / scale, top / scale, (left + width) / scale, (top + height) / scale)
        rect = rect * derot  # rendered (rotated) space -> unrotated page space
        words.append(OcrWord(rect.x0, rect.y0, rect.x1, rect.y1, text, conf))
        current.append(text)
    if current:
        lines.append(" ".join(current))
    text = "\n".join(lines).strip() + "\n"
    return OcrPageResult(pno, text, words)


def add_text_layer(document: Document, result: OcrPageResult, min_conf: float = 0.0) -> int:
    """Write *result*'s words onto the page as invisible text. Returns words written."""
    written = 0
    with document.lock:
        page = document.page(result.page)
        rotate = page.rotation
        for w in result.words:
            if w.conf < min_conf or not w.text.strip():
                continue
            rect = pymupdf.Rect(w.x0, w.y0, w.x1, w.y1)
            if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                continue
            # Size the font so the word spans its box horizontally; keeps
            # selection/search highlighting aligned with the scanned glyphs.
            unit_len = pymupdf.get_text_length(w.text, fontname="helv", fontsize=1)
            if unit_len <= 0:
                continue
            # Box geometry in rotated (visible) space decides the glyph size.
            vis = rect * page.rotation_matrix
            fontsize = vis.width / unit_len
            if fontsize <= 0:
                continue
            # Baseline sits a little above the bottom of the box.
            if rotate == 0:
                origin = pymupdf.Point(rect.x0, rect.y1 - fontsize * 0.22)
            else:
                origin = pymupdf.Point(vis.x0, vis.y1 - fontsize * 0.22) * page.derotation_matrix
            try:
                page.insert_text(origin, w.text, fontsize=fontsize, fontname="helv",
                                 render_mode=3, rotate=rotate)
                written += 1
            except Exception:
                continue
    document.invalidate(result.page)
    if written:
        document.mark_modified()
    return written


def results_to_text(results: dict[int, OcrPageResult]) -> str:
    parts = []
    for pno in sorted(results):
        parts.append(f"===== Page {pno + 1} =====\n{results[pno].text}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# background worker
# ---------------------------------------------------------------------------
class OcrWorker(QThread):
    progress = Signal(int, int)          # done, total
    page_done = Signal(object)           # OcrPageResult
    failed = Signal(str)
    completed = Signal(bool)             # cancelled?

    def __init__(self, document: Document, pages: list[int], lang: str, dpi: int, parent=None) -> None:
        super().__init__(parent)
        self.document = document
        self.pages = list(pages)
        self.lang = lang
        self.dpi = dpi
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        total = len(self.pages)
        try:
            for i, pno in enumerate(self.pages):
                if self._cancel:
                    break
                result = ocr_page(self.document, pno, self.lang, self.dpi)
                self.page_done.emit(result)
                self.progress.emit(i + 1, total)
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.failed.emit(str(exc))
            self.completed.emit(True)
            return
        self.completed.emit(self._cancel)
