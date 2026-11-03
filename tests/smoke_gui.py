"""Offscreen GUI smoke test: builds the main window, opens the samples, exercises
the main actions and writes screenshots. Run:
    python tests/smoke_gui.py [out_dir]
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pymupdf  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pdf_reader_ocr.main_window import MainWindow  # noqa: E402
from pdf_reader_ocr.page_view import Tool  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "_shots")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1280, 860)
    win.show()
    app.processEvents()
    win.grab().save(os.path.join(out, "01_welcome.png"))

    assert win.open_file(os.path.join(SAMPLES, "text.pdf"))
    app.processEvents()
    assert win.document and win.document.page_count == 3
    win.view.goto_page(1)
    app.processEvents()
    assert win.page_spin.value() == 2, win.page_spin.value()

    # search
    win.search_box.setText("lazy dog")
    app.processEvents()
    assert win.view.hit_count() == 3, win.view.hit_count()
    win.grab().save(os.path.join(out, "02_search.png"))

    # zoom + rotate view
    win.view.set_zoom(1.5)
    win.view.rotate_view(90)
    app.processEvents()
    win.view.rotate_view(-90)
    win.view.set_zoom_mode("fit-width")
    app.processEvents()

    # selection + highlight via the tool pipeline (synthesised)
    win.view.goto_page(0)
    app.processEvents()
    words = win.document.words(0)
    first = next(w for w in words if w.text == "quick")
    last = next(w for w in words if w.text == "dog.")
    win.view.set_tool(Tool.HIGHLIGHT)
    win.view.selection_page = 0
    win.view.selection_rects = [w.rect for w in words if first.y0 <= w.y0 <= last.y1 and w.line == first.line]
    win.view._add_markup(0, "highlight")
    app.processEvents()
    page0 = win.document.page(0)  # keep the page alive while inspecting its annots
    annot_types = [a.type[1] for a in page0.annots()]
    assert annot_types == ["Highlight"], annot_types

    # ink annotation
    with win.document.lock:
        a = win.document.page(0).add_ink_annot([[(100, 300), (200, 320), (300, 300)]])
        a.update()
    win.view._after_edit(0)
    app.processEvents()
    assert win.document.modified
    win.grab().save(os.path.join(out, "03_annotated.png"))

    # coordinate round trip
    pt = win.view.page_point_to_item(0, pymupdf.Point(100, 200))
    back = win.view.item_to_page_point(0, pt)
    assert abs(back.x - 100) < 0.01 and abs(back.y - 200) < 0.01, (pt, back)

    # save as, dark mode
    tmp = os.path.join(out, "text_annotated.pdf")
    assert win._do_save(tmp)
    assert not win.document.modified
    win.act_dark.setChecked(True)
    app.processEvents()
    win.grab().save(os.path.join(out, "04_dark.png"))
    win.act_dark.setChecked(False)

    # OCR flow (synchronous for the test)
    win.open_file(os.path.join(SAMPLES, "scan.pdf"))
    app.processEvents()
    if win.ocr_panel.btn_all.isEnabled():
        win.ocr_all()
        while win.worker is not None:
            app.processEvents()
            win.worker.wait(50) if win.worker else None
        assert len(win.ocr_panel.results) == 2, win.ocr_panel.results.keys()
        assert "lazy dog" in win.ocr_panel.text.toPlainText().lower()
        win.grab().save(os.path.join(out, "05_ocr.png"))
    else:
        print("WARNING: tesseract not found, OCR flow skipped")

    win.document.modified = False
    win.close()
    print("smoke OK ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
