"""Side panels: page thumbnails, bookmarks (outline) and the OCR panel."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_reader_ocr.document import Document
from pdf_reader_ocr.ocr import OcrPageResult

THUMB_WIDTH = 120


class ThumbnailPanel(QListWidget):
    page_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.document: Document | None = None
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.4)))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.currentRowChanged.connect(self._on_row)
        self._pending: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_next)
        self._block = False

    def set_document(self, document: Document | None) -> None:
        self._timer.stop()
        self._block = True
        self.clear()
        self._block = False
        self.document = document
        if document is None:
            return
        for pno in range(document.page_count):
            item = QListWidgetItem(f"{pno + 1}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            placeholder = QPixmap(THUMB_WIDTH, int(THUMB_WIDTH * 1.3))
            placeholder.fill(Qt.GlobalColor.white)
            item.setIcon(QIcon(placeholder))
            self.addItem(item)
        self._pending = list(range(document.page_count))
        self._timer.start()

    def refresh(self) -> None:
        self.set_document(self.document)

    def refresh_page(self, pno: int) -> None:
        if self.document and 0 <= pno < self.count():
            if pno not in self._pending:
                self._pending.insert(0, pno)
            self._timer.start()

    def _render_next(self) -> None:
        if not self._pending or self.document is None:
            self._timer.stop()
            return
        # Prioritise visible thumbnails.
        visible = [i for i in self._pending if self.visualItemRect(self.item(i)).intersects(self.viewport().rect())]
        pno = visible[0] if visible else self._pending[0]
        self._pending.remove(pno)
        try:
            w = self.document.rendered_rect(pno, 1.0, 0).width
            zoom = THUMB_WIDTH / max(1, w)
            img = self.document.render(pno, zoom, 0)
            self.item(pno).setIcon(QIcon(QPixmap.fromImage(img)))
        except Exception:
            pass

    def set_current(self, pno: int) -> None:
        if 0 <= pno < self.count() and self.currentRow() != pno:
            self._block = True
            self.setCurrentRow(pno)
            self.scrollToItem(self.item(pno))
            self._block = False

    def _on_row(self, row: int) -> None:
        if not self._block and row >= 0:
            self.page_selected.emit(row)


class OutlinePanel(QTreeWidget):
    page_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.itemClicked.connect(self._on_click)
        self.itemActivated.connect(self._on_click)

    def set_document(self, document: Document | None) -> None:
        self.clear()
        if document is None:
            return
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for entry in document.outline():
            item = QTreeWidgetItem([entry.title or "(untitled)"])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.page)
            if entry.page >= 0:
                item.setToolTip(0, f"Page {entry.page + 1}")
            while stack and stack[-1][0] >= entry.level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.addTopLevelItem(item)
            stack.append((entry.level, item))
        self.expandToDepth(0)
        if self.topLevelItemCount() == 0:
            placeholder = QTreeWidgetItem(["No bookmarks in this document"])
            placeholder.setDisabled(True)
            self.addTopLevelItem(placeholder)

    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None and page >= 0:
            self.page_selected.emit(int(page))


class OcrPanel(QWidget):
    ocr_current_requested = Signal()
    ocr_all_requested = Signal()
    cancel_requested = Signal()
    make_searchable_requested = Signal()
    export_text_requested = Signal()
    language_changed = Signal(str)
    dpi_changed = Signal(int)
    locate_tesseract_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.results: dict[int, OcrPageResult] = {}
        self._showing_page: int | None = None
        self._ok = False
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.status_label = QLabel("Tesseract: not found")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Language"))
        self.lang_combo = QComboBox()
        self.lang_combo.currentTextChanged.connect(self.language_changed)
        row.addWidget(self.lang_combo, 1)
        row.addWidget(QLabel("DPI"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(100, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        self.dpi_spin.valueChanged.connect(self.dpi_changed)
        row.addWidget(self.dpi_spin)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.btn_current = QPushButton("OCR this page")
        self.btn_current.clicked.connect(self.ocr_current_requested)
        self.btn_all = QPushButton("OCR all pages")
        self.btn_all.clicked.connect(self.ocr_all_requested)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_requested)
        self.btn_cancel.hide()
        row.addWidget(self.btn_current)
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        self.page_label = QLabel("Recognized text")
        layout.addWidget(self.page_label)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("Run OCR to see recognized text here.")
        layout.addWidget(self.text, 1)

        row = QHBoxLayout()
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy_all)
        self.btn_export = QPushButton("Export .txt")
        self.btn_export.clicked.connect(self.export_text_requested)
        self.btn_searchable = QPushButton("Save searchable PDF")
        self.btn_searchable.setToolTip("Writes an invisible text layer over the OCR'd pages and saves a copy")
        self.btn_searchable.clicked.connect(self.make_searchable_requested)
        row.addWidget(self.btn_copy)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_searchable)
        layout.addLayout(row)

        self.btn_locate = QPushButton("Locate tesseract.exe...")
        self.btn_locate.clicked.connect(self.locate_tesseract_requested)
        layout.addWidget(self.btn_locate)
        self._update_buttons()

    def _copy_all(self) -> None:
        self.text.selectAll()
        self.text.copy()

    # -- state -----------------------------------------------------------
    def set_tesseract_status(self, text: str, ok: bool) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet("" if ok else "color: #d9534f;")
        self._ok = ok
        self._update_buttons()

    def set_languages(self, langs: list[str], current: str) -> None:
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItems(langs)
        if current in langs:
            self.lang_combo.setCurrentText(current)
        self.lang_combo.blockSignals(False)

    def set_dpi(self, dpi: int) -> None:
        self.dpi_spin.setValue(dpi)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_cancel.setVisible(busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setValue(0)
        self._update_buttons()

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def clear_results(self) -> None:
        self.results.clear()
        self._showing_page = None
        self.text.clear()
        self.page_label.setText("Recognized text")
        self._update_buttons()

    def add_result(self, result: OcrPageResult) -> None:
        self.results[result.page] = result
        self.show_page(result.page)
        self._update_buttons()

    def show_page(self, pno: int) -> None:
        res = self.results.get(pno)
        if res is None:
            return
        self._showing_page = pno
        self.page_label.setText(f"Recognized text - page {pno + 1} ({len(res.words)} words)")
        self.text.setPlainText(res.text)

    def _update_buttons(self) -> None:
        has = bool(self.results)
        self.btn_current.setEnabled(self._ok and not self._busy)
        self.btn_all.setEnabled(self._ok and not self._busy)
        self.btn_export.setEnabled(has and not self._busy)
        self.btn_searchable.setEnabled(has and not self._busy)
        self.btn_copy.setEnabled(has)
