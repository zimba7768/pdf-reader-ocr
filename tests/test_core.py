"""Headless tests for the document wrapper and OCR pipeline (no GUI needed)."""
from __future__ import annotations

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pdf_reader_ocr import ocr as ocr_mod  # noqa: E402
from pdf_reader_ocr.document import Document, merge_pdfs, split_pdf  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")


@pytest.fixture(scope="session", autouse=True)
def samples():
    if not os.path.isdir(SAMPLES):
        from tests import make_samples  # type: ignore

        make_samples.main()
    return SAMPLES


@pytest.fixture
def tmp_copy(tmp_path):
    def _copy(name: str) -> str:
        dst = tmp_path / name
        shutil.copy(os.path.join(SAMPLES, name), dst)
        return str(dst)

    return _copy


def test_open_render_search_outline(tmp_copy):
    doc = Document(tmp_copy("text.pdf"))
    assert doc.page_count == 3
    img = doc.render(0, 1.0, 0)
    assert img.width() == 595 and img.height() == 842
    hits = doc.search("lazy dog")
    assert sorted(hits) == [0, 1, 2]
    assert [e.title for e in doc.outline()] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert doc.has_text(0)
    doc.close()


def test_page_ops_and_save(tmp_copy):
    path = tmp_copy("text.pdf")
    doc = Document(path)
    doc.move_page(2, 0)
    doc.rotate_page(0, 90)
    doc.delete_pages([2])
    assert doc.page_count == 2
    assert doc.modified
    doc.save()
    assert not doc.modified
    doc.close()
    again = Document(path)
    assert again.page_count == 2
    assert again.page(0).rotation == 90
    assert "Chapter 3" in again.page(0).get_text()
    again.close()


def test_merge_split(tmp_copy, tmp_path):
    a, b = tmp_copy("text.pdf"), tmp_copy("scan.pdf")
    out = str(tmp_path / "merged.pdf")
    assert merge_pdfs([a, b], out) == 5
    parts = split_pdf(out, str(tmp_path), pages_per_file=2)
    assert len(parts) == 3


def _tesseract_available() -> bool:
    exe = ocr_mod.find_tesseract()
    if exe:
        ocr_mod.configure_tesseract(exe)
    return bool(exe)


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract not installed")
def test_ocr_and_text_layer(tmp_copy, tmp_path):
    doc = Document(tmp_copy("scan.pdf"))
    assert not doc.has_text(0)
    result = ocr_mod.ocr_page(doc, 0, "eng", 200)
    assert "lazy dog" in result.text.lower()
    assert len(result.words) > 10
    written = ocr_mod.add_text_layer(doc, result)
    assert written > 10
    out = str(tmp_path / "scan_ocr.pdf")
    doc.save(out)
    doc.close()
    check = Document(out)
    assert check.has_text(0)
    hits = check.search("lazy dog")
    assert 0 in hits
    # The invisible text must sit where the printed words are (within the page's text band).
    r = hits[0][0]
    assert 50 < r.x0 < 300 and 100 < r.y0 < 500
    check.close()


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract not installed")
def test_ocr_rotated_page(tmp_copy, tmp_path):
    doc = Document(tmp_copy("scan_rot.pdf"))
    result = ocr_mod.ocr_page(doc, 0, "eng", 200)
    assert "lazy dog" in result.text.lower()
    ocr_mod.add_text_layer(doc, result)
    out = str(tmp_path / "rot_ocr.pdf")
    doc.save(out)
    doc.close()
    check = Document(out)
    hits = check.search("lazy dog")
    assert 0 in hits
    # OCR word boxes are in unrotated space; the hit from the text layer must overlap one of them.
    word = next(w for w in result.words if w.text.lower().startswith("lazy"))
    import pymupdf

    assert any(pymupdf.Rect(word.x0, word.y0, word.x1, word.y1).intersects(h) for h in hits[0])
    check.close()
