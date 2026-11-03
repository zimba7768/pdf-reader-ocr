"""Thin wrapper around a PyMuPDF document.

All coordinates handed to and from this class are in *unrotated* page space
(the space PyMuPDF uses for text extraction and annotations). Rendering takes
the page's own /Rotate plus an optional extra view rotation into account.
"""
from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass

import pymupdf
from PySide6.QtGui import QImage


@dataclass
class OutlineEntry:
    level: int
    title: str
    page: int  # 0-based; -1 when the entry has no page target


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int
    index: int

    @property
    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(self.x0, self.y0, self.x1, self.y1)


class Document:
    def __init__(self, path: str | None = None) -> None:
        self.path = os.path.abspath(path) if path else None
        self.lock = threading.RLock()
        self.doc = pymupdf.open(self.path) if self.path else pymupdf.open()
        self.modified = False
        self._words: dict[int, list[Word]] = {}

    # ---- basics --------------------------------------------------------
    @property
    def page_count(self) -> int:
        return self.doc.page_count

    @property
    def needs_password(self) -> bool:
        return bool(self.doc.needs_pass)

    @property
    def title(self) -> str:
        if self.path:
            return os.path.basename(self.path)
        return "Untitled"

    def authenticate(self, password: str) -> bool:
        return self.doc.authenticate(password) > 0

    def page(self, pno: int) -> pymupdf.Page:
        return self.doc[pno]

    def close(self) -> None:
        with self.lock:
            if not self.doc.is_closed:
                self.doc.close()

    def mark_modified(self) -> None:
        self.modified = True

    # ---- rendering -----------------------------------------------------
    @staticmethod
    def render_matrix(zoom: float, rotation: int) -> pymupdf.Matrix:
        return pymupdf.Matrix(zoom, zoom).prerotate(rotation)

    def rendered_rect(self, pno: int, zoom: float, rotation: int) -> pymupdf.IRect:
        """Pixel rectangle the page occupies after transformation (may have non-zero origin)."""
        with self.lock:
            return (self.doc[pno].rect * self.render_matrix(zoom, rotation)).irect

    def render(self, pno: int, zoom: float, rotation: int = 0) -> QImage:
        with self.lock:
            page = self.doc[pno]
            pix = page.get_pixmap(matrix=self.render_matrix(zoom, rotation), alpha=False)
            fmt = QImage.Format.Format_RGB888
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
            return img

    def render_pil(self, pno: int, dpi: int):
        """Render for OCR; returns (PIL.Image, scale)."""
        from PIL import Image

        with self.lock:
            page = self.doc[pno]
            scale = dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            return img, scale

    # ---- text ----------------------------------------------------------
    def words(self, pno: int) -> list[Word]:
        if pno not in self._words:
            with self.lock:
                raw = self.doc[pno].get_text("words")
            self._words[pno] = [Word(*w[:5], w[5], w[6], w[7]) for w in raw]
        return self._words[pno]

    def invalidate(self, pno: int | None = None) -> None:
        if pno is None:
            self._words.clear()
        else:
            self._words.pop(pno, None)

    def has_text(self, pno: int) -> bool:
        with self.lock:
            return bool(self.doc[pno].get_text("text").strip())

    def search(self, needle: str) -> dict[int, list[pymupdf.Rect]]:
        hits: dict[int, list[pymupdf.Rect]] = {}
        if not needle:
            return hits
        with self.lock:
            for pno in range(self.page_count):
                rects = self.doc[pno].search_for(needle)
                if rects:
                    hits[pno] = rects
        return hits

    def outline(self) -> list[OutlineEntry]:
        with self.lock:
            toc = self.doc.get_toc(simple=True)
        return [OutlineEntry(lvl, title, page - 1) for lvl, title, page in toc]

    # ---- page operations ----------------------------------------------
    def rotate_page(self, pno: int, degrees: int) -> None:
        with self.lock:
            page = self.doc[pno]
            page.set_rotation((page.rotation + degrees) % 360)
        self.invalidate(pno)
        self.mark_modified()

    def delete_pages(self, pages: list[int]) -> None:
        with self.lock:
            self.doc.delete_pages(sorted(set(pages)))
        self.invalidate()
        self.mark_modified()

    def move_page(self, src: int, dst: int) -> None:
        with self.lock:
            self.doc.move_page(src, dst)
        self.invalidate()
        self.mark_modified()

    def insert_pdf(self, path: str, at: int | None = None) -> int:
        """Insert all pages of *path*. Returns number of pages inserted."""
        with self.lock:
            other = pymupdf.open(path)
            try:
                n = other.page_count
                if at is None:
                    self.doc.insert_pdf(other)
                else:
                    self.doc.insert_pdf(other, start_at=at)
            finally:
                other.close()
        self.invalidate()
        self.mark_modified()
        return n

    def extract_pages(self, pages: list[int], out_path: str) -> None:
        with self.lock:
            new = pymupdf.open()
            try:
                for pno in pages:
                    new.insert_pdf(self.doc, from_page=pno, to_page=pno)
                new.save(out_path, garbage=3, deflate=True)
            finally:
                new.close()

    # ---- saving --------------------------------------------------------
    def save(self, path: str | None = None) -> None:
        target = os.path.abspath(path) if path else self.path
        if not target:
            raise ValueError("No file name given")
        with self.lock:
            fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(target))
            os.close(fd)
            try:
                self.doc.save(tmp, garbage=3, deflate=True)
                self.doc.close()
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            # Re-open from the saved file so later edits/saves apply to it.
            self.doc = pymupdf.open(target)
            self.path = target
        self.invalidate()
        self.modified = False


def merge_pdfs(paths: list[str], out_path: str) -> int:
    """Merge several PDFs into one. Returns total page count."""
    out = pymupdf.open()
    try:
        for p in paths:
            src = pymupdf.open(p)
            try:
                out.insert_pdf(src)
            finally:
                src.close()
        out.save(out_path, garbage=3, deflate=True)
        return out.page_count
    finally:
        out.close()


def split_pdf(path: str, out_dir: str, pages_per_file: int = 1) -> list[str]:
    """Split a PDF into chunks of *pages_per_file* pages. Returns written paths."""
    src = pymupdf.open(path)
    written: list[str] = []
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        n = src.page_count
        start = 0
        part = 1
        while start < n:
            end = min(start + pages_per_file, n) - 1
            out = pymupdf.open()
            try:
                out.insert_pdf(src, from_page=start, to_page=end)
                if pages_per_file > 1:
                    name = f"{stem}_part{part:03d}.pdf"
                else:
                    name = f"{stem}_page{start + 1:04d}.pdf"
                out_path = os.path.join(out_dir, name)
                out.save(out_path, garbage=3, deflate=True)
                written.append(out_path)
            finally:
                out.close()
            start = end + 1
            part += 1
    finally:
        src.close()
    return written
