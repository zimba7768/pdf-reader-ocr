"""Page tools: organize (reorder / rotate / delete / extract / insert), merge, split."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdf_reader_ocr.document import Document, merge_pdfs, split_pdf

THUMB = 110


class OrganizeDialog(QDialog):
    """Lets the user reorder, rotate, delete, extract and insert pages.

    Operations are applied to the document immediately; ``changed`` tells the
    caller whether anything was modified so it can refresh the view.
    """

    def __init__(self, document: Document, parent=None) -> None:
        super().__init__(parent)
        self.document = document
        self.changed = False
        self.setWindowTitle("Organize pages")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select one or more pages, then use the buttons. Changes are saved when you save the document."))

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB, int(THUMB * 1.4)))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setSpacing(6)
        body.addWidget(self.list, 1)

        buttons = QVBoxLayout()
        for label, slot in [
            ("Move up", self.move_up),
            ("Move down", self.move_down),
            ("Rotate 90° clockwise", lambda: self.rotate(90)),
            ("Rotate 90° counter-clockwise", lambda: self.rotate(-90)),
            ("Delete", self.delete),
            ("Extract to new PDF...", self.extract),
            ("Insert PDF after selection...", self.insert_pdf),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        body.addLayout(buttons)
        layout.addLayout(body)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.accept)
        layout.addWidget(box)
        self.reload()

    # -- helpers ---------------------------------------------------------
    def reload(self) -> None:
        self.list.clear()
        for pno in range(self.document.page_count):
            item = QListWidgetItem(f"{pno + 1}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            w = self.document.rendered_rect(pno, 1.0, 0).width
            img = self.document.render(pno, THUMB / max(1, w), 0)
            item.setIcon(QIcon(QPixmap.fromImage(img)))
            self.list.addItem(item)

    def selected(self) -> list[int]:
        return sorted(self.list.row(i) for i in self.list.selectedItems())

    def _reselect(self, pages: list[int]) -> None:
        self.list.clearSelection()
        for p in pages:
            if 0 <= p < self.list.count():
                self.list.item(p).setSelected(True)

    # -- operations ------------------------------------------------------
    def move_up(self) -> None:
        sel = self.selected()
        if not sel or sel[0] == 0:
            return
        for p in sel:
            self.document.move_page(p, p - 1)
        self.changed = True
        self.reload()
        self._reselect([p - 1 for p in sel])

    def move_down(self) -> None:
        sel = self.selected()
        if not sel or sel[-1] >= self.document.page_count - 1:
            return
        for p in reversed(sel):
            # move_page(src, dst) inserts *before* dst, so dst = p + 2 shifts one down
            self.document.move_page(p, p + 2)
        self.changed = True
        self.reload()
        self._reselect([p + 1 for p in sel])

    def rotate(self, degrees: int) -> None:
        sel = self.selected()
        for p in sel:
            self.document.rotate_page(p, degrees)
        if sel:
            self.changed = True
            self.reload()
            self._reselect(sel)

    def delete(self) -> None:
        sel = self.selected()
        if not sel:
            return
        if len(sel) >= self.document.page_count:
            QMessageBox.warning(self, "Delete pages", "A document must keep at least one page.")
            return
        if QMessageBox.question(self, "Delete pages", f"Delete {len(sel)} page(s)?") != QMessageBox.StandardButton.Yes:
            return
        self.document.delete_pages(sel)
        self.changed = True
        self.reload()

    def extract(self) -> None:
        sel = self.selected()
        if not sel:
            QMessageBox.information(self, "Extract pages", "Select the pages to extract first.")
            return
        stem = os.path.splitext(self.document.path or "extracted")[0]
        path, _ = QFileDialog.getSaveFileName(self, "Extract pages to", f"{stem}_pages.pdf", "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.document.extract_pages(sel, path)
        except Exception as exc:
            QMessageBox.critical(self, "Extract pages", f"Could not write file:\n{exc}")
            return
        QMessageBox.information(self, "Extract pages", f"Wrote {len(sel)} page(s) to\n{path}")

    def insert_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Insert PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        sel = self.selected()
        at = (sel[-1] + 1) if sel else None
        try:
            n = self.document.insert_pdf(path, at)
        except Exception as exc:
            QMessageBox.critical(self, "Insert PDF", f"Could not insert file:\n{exc}")
            return
        self.changed = True
        self.reload()
        start = at if at is not None else self.document.page_count - n
        self._reselect(list(range(start, start + n)))


class MergeDialog(QDialog):
    def __init__(self, parent=None, initial: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge PDFs")
        self.resize(560, 400)
        self.output_path: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Files are merged in the order shown."))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for p in initial or []:
            self.list.addItem(p)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        for label, slot in [("Add files...", self.add), ("Remove", self.remove), ("Up", self.up), ("Down", self.down)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        layout.addLayout(row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Merge...")
        box.accepted.connect(self.run)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def paths(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF files (*.pdf)")
        for f in files:
            self.list.addItem(f)

    def remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _shift(self, delta: int) -> None:
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows:
            return
        if delta < 0 and rows[0] == 0:
            return
        if delta > 0 and rows[-1] == self.list.count() - 1:
            return
        for r in (rows if delta < 0 else reversed(rows)):
            item = self.list.takeItem(r)
            self.list.insertItem(r + delta, item)
            item.setSelected(True)

    def up(self) -> None:
        self._shift(-1)

    def down(self) -> None:
        self._shift(1)

    def run(self) -> None:
        paths = self.paths()
        if len(paths) < 2:
            QMessageBox.information(self, "Merge PDFs", "Add at least two files.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save merged PDF as", os.path.join(os.path.dirname(paths[0]), "merged.pdf"), "PDF files (*.pdf)")
        if not out:
            return
        try:
            n = merge_pdfs(paths, out)
        except Exception as exc:
            QMessageBox.critical(self, "Merge PDFs", f"Merge failed:\n{exc}")
            return
        self.output_path = out
        QMessageBox.information(self, "Merge PDFs", f"Merged {len(paths)} files ({n} pages) into\n{out}")
        self.accept()


class SplitDialog(QDialog):
    def __init__(self, source: str, parent=None) -> None:
        super().__init__(parent)
        self.source = source
        self.setWindowTitle("Split PDF")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Split\n{os.path.basename(source)}\ninto files of:"))
        row = QHBoxLayout()
        self.spin = QSpinBox()
        self.spin.setRange(1, 9999)
        self.spin.setValue(1)
        row.addWidget(self.spin)
        row.addWidget(QLabel("page(s) each"))
        layout.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Choose folder and split...")
        box.accepted.connect(self.run)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def run(self) -> None:
        out_dir = QFileDialog.getExistingDirectory(self, "Output folder", os.path.dirname(self.source))
        if not out_dir:
            return
        try:
            written = split_pdf(self.source, out_dir, self.spin.value())
        except Exception as exc:
            QMessageBox.critical(self, "Split PDF", f"Split failed:\n{exc}")
            return
        QMessageBox.information(self, "Split PDF", f"Wrote {len(written)} file(s) to\n{out_dir}")
        self.accept()
