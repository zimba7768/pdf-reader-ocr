"""Main application window."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QKeySequence, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdf_reader_ocr import APP_NAME, __version__
from pdf_reader_ocr import ocr as ocr_mod
from pdf_reader_ocr.document import Document
from pdf_reader_ocr.page_tools import MergeDialog, OrganizeDialog, SplitDialog
from pdf_reader_ocr.page_view import PageView, Tool
from pdf_reader_ocr.panels import OcrPanel, OutlinePanel, ThumbnailPanel
from pdf_reader_ocr.settings import Settings
from pdf_reader_ocr.theme import apply_theme

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
ZOOM_PRESETS = ["Fit width", "Fit page", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"]


def app_icon() -> QIcon:
    ico = os.path.join(RESOURCES, "icon.ico")
    return QIcon(ico) if os.path.exists(ico) else QIcon()


class WelcomePage(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        title = QLabel(f"<h1>{APP_NAME}</h1><p>Free, open-source PDF reader with OCR.</p>")
        layout.addWidget(title)
        row = QHBoxLayout()
        open_btn = QPushButton("Open PDF...")
        open_btn.clicked.connect(window.open_file_dialog)
        merge_btn = QPushButton("Merge PDFs...")
        merge_btn.clicked.connect(window.merge_pdfs)
        row.addWidget(open_btn)
        row.addWidget(merge_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel("<b>Recent files</b>"))
        self.recent = QListWidget()
        self.recent.itemActivated.connect(lambda item: window.open_file(item.text()))
        layout.addWidget(self.recent, 1)
        hint = QLabel("Tip: drag a PDF onto this window to open it.")
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

    def refresh(self) -> None:
        self.recent.clear()
        for p in self.window.settings.recent_files():
            self.recent.addItem(p)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings()
        self.document: Document | None = None
        self.worker: ocr_mod.OcrWorker | None = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1200, 820)
        self.setAcceptDrops(True)

        self.view = PageView(self)
        self.welcome = WelcomePage(self)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.view)
        self.setCentralWidget(self.stack)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._wire_signals()

        self.statusBar().showMessage("Ready")
        apply_theme(QApplication.instance(), self.settings.dark_mode)
        self.act_dark.setChecked(self.settings.dark_mode)
        self._init_ocr()
        self._restore_window()
        self._update_ui()
        self.welcome.refresh()

    # ------------------------------------------------------------------ build
    def _build_docks(self) -> None:
        self.thumbs = ThumbnailPanel()
        self.dock_thumbs = QDockWidget("Pages", self)
        self.dock_thumbs.setObjectName("dock_pages")
        self.dock_thumbs.setWidget(self.thumbs)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_thumbs)

        self.outline = OutlinePanel()
        self.dock_outline = QDockWidget("Bookmarks", self)
        self.dock_outline.setObjectName("dock_bookmarks")
        self.dock_outline.setWidget(self.outline)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_outline)
        self.tabifyDockWidget(self.dock_thumbs, self.dock_outline)
        self.dock_thumbs.raise_()

        self.ocr_panel = OcrPanel()
        self.dock_ocr = QDockWidget("OCR", self)
        self.dock_ocr.setObjectName("dock_ocr")
        self.dock_ocr.setWidget(self.ocr_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_ocr)
        self.resizeDocks([self.dock_thumbs, self.dock_ocr], [190, 340], Qt.Orientation.Horizontal)

    def _icon(self, name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        icon = QIcon.fromTheme(name)
        return icon if not icon.isNull() else self.style().standardIcon(fallback)

    def _build_actions(self) -> None:
        sp = QStyle.StandardPixmap
        A = QAction

        self.act_open = A(self._icon("document-open", sp.SP_DialogOpenButton), "&Open...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.open_file_dialog)

        self.act_save = A(self._icon("document-save", sp.SP_DialogSaveButton), "&Save", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self.save)

        self.act_save_as = A("Save &As...", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self.save_as)

        self.act_close = A("&Close", self)
        self.act_close.setShortcut(QKeySequence.StandardKey.Close)
        self.act_close.triggered.connect(self.close_document)

        self.act_print = A(self._icon("document-print", sp.SP_FileDialogDetailedView), "&Print...", self)
        self.act_print.setShortcut(QKeySequence.StandardKey.Print)
        self.act_print.triggered.connect(self.print_document)

        self.act_quit = A("E&xit", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_prev = A(self._icon("go-up", sp.SP_ArrowUp), "Previous page", self)
        self.act_prev.setShortcut(QKeySequence("Alt+Left"))
        self.act_prev.triggered.connect(self.view.prev_page)
        self.act_next = A(self._icon("go-down", sp.SP_ArrowDown), "Next page", self)
        self.act_next.setShortcut(QKeySequence("Alt+Right"))
        self.act_next.triggered.connect(self.view.next_page)
        self.act_first = A("First page", self)
        self.act_first.setShortcut(QKeySequence("Ctrl+Home"))
        self.act_first.triggered.connect(lambda: self.view.goto_page(0))
        self.act_last = A("Last page", self)
        self.act_last.setShortcut(QKeySequence("Ctrl+End"))
        self.act_last.triggered.connect(lambda: self.view.goto_page(self.view.page_count() - 1))
        self.act_goto = A("Go to page...", self)
        self.act_goto.setShortcut(QKeySequence("Ctrl+G"))
        self.act_goto.triggered.connect(self.goto_page_dialog)

        self.act_zoom_in = A(self._icon("zoom-in", sp.SP_ArrowUp), "Zoom in", self)
        self.act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_in.triggered.connect(self.view.zoom_in)
        self.act_zoom_out = A(self._icon("zoom-out", sp.SP_ArrowDown), "Zoom out", self)
        self.act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.act_zoom_out.triggered.connect(self.view.zoom_out)
        self.act_fit_width = A("Fit width", self)
        self.act_fit_width.setShortcut(QKeySequence("Ctrl+1"))
        self.act_fit_width.triggered.connect(lambda: self.view.set_zoom_mode("fit-width"))
        self.act_fit_page = A("Fit page", self)
        self.act_fit_page.setShortcut(QKeySequence("Ctrl+2"))
        self.act_fit_page.triggered.connect(lambda: self.view.set_zoom_mode("fit-page"))
        self.act_zoom_100 = A("Actual size", self)
        self.act_zoom_100.setShortcut(QKeySequence("Ctrl+0"))
        self.act_zoom_100.triggered.connect(lambda: self.view.set_zoom(1.0))
        self.act_rotate_view_cw = A(self._icon("object-rotate-right", sp.SP_BrowserReload), "Rotate view clockwise", self)
        self.act_rotate_view_cw.setShortcut(QKeySequence("Ctrl+R"))
        self.act_rotate_view_cw.triggered.connect(lambda: self.view.rotate_view(90))
        self.act_rotate_view_ccw = A("Rotate view counter-clockwise", self)
        self.act_rotate_view_ccw.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.act_rotate_view_ccw.triggered.connect(lambda: self.view.rotate_view(-90))

        self.act_dark = A("Dark mode", self)
        self.act_dark.setCheckable(True)
        self.act_dark.toggled.connect(self.toggle_dark)
        self.act_fullscreen = A("Full screen", self)
        self.act_fullscreen.setShortcut(QKeySequence("F11"))
        self.act_fullscreen.setCheckable(True)
        self.act_fullscreen.toggled.connect(lambda on: self.showFullScreen() if on else self.showNormal())

        # tools
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, label, key in [
            (Tool.SELECT, "Select text", "V"),
            (Tool.HAND, "Hand (pan)", "H"),
            (Tool.HIGHLIGHT, "Highlight", "1"),
            (Tool.UNDERLINE, "Underline", "2"),
            (Tool.NOTE, "Sticky note", "3"),
            (Tool.INK, "Draw (ink)", "4"),
        ]:
            act = A(label, self)
            act.setCheckable(True)
            act.setShortcut(QKeySequence(key))
            act.setData(tool)
            act.triggered.connect(lambda _c=False, t=tool: self.view.set_tool(t))
            self.tool_group.addAction(act)
            self.tool_actions[tool] = act
        self.tool_actions[Tool.SELECT].setChecked(True)

        self.act_copy = A("&Copy", self)
        self.act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self.act_copy.triggered.connect(self.view.copy_selection)
        self.act_select_all = A("Select all on page", self)
        self.act_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.act_select_all.triggered.connect(lambda: self.view.select_all_on_page())
        self.act_find = A(self._icon("edit-find", sp.SP_FileDialogContentsView), "&Find", self)
        self.act_find.setShortcut(QKeySequence.StandardKey.Find)
        self.act_find.triggered.connect(lambda: (self.search_box.setFocus(), self.search_box.selectAll()))

        # page tools
        self.act_organize = A("Organize pages...", self)
        self.act_organize.triggered.connect(self.organize_pages)
        self.act_rotate_page_cw = A("Rotate current page clockwise", self)
        self.act_rotate_page_cw.triggered.connect(lambda: self.rotate_current_page(90))
        self.act_rotate_page_ccw = A("Rotate current page counter-clockwise", self)
        self.act_rotate_page_ccw.triggered.connect(lambda: self.rotate_current_page(-90))
        self.act_delete_page = A("Delete current page", self)
        self.act_delete_page.triggered.connect(self.delete_current_page)
        self.act_merge = A("Merge PDFs...", self)
        self.act_merge.triggered.connect(self.merge_pdfs)
        self.act_split = A("Split this PDF...", self)
        self.act_split.triggered.connect(self.split_pdf)

        # OCR
        self.act_ocr_page = A("OCR current page", self)
        self.act_ocr_page.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_ocr_page.triggered.connect(self.ocr_current)
        self.act_ocr_all = A("OCR all pages", self)
        self.act_ocr_all.triggered.connect(self.ocr_all)
        self.act_ocr_searchable = A("Save searchable PDF...", self)
        self.act_ocr_searchable.triggered.connect(self.make_searchable)
        self.act_ocr_export = A("Export OCR text...", self)
        self.act_ocr_export.triggered.connect(self.export_text)

        self.act_default = A("Set as default PDF viewer...", self)
        self.act_default.triggered.connect(self.set_default_viewer)
        self.act_about = A("&About", self)
        self.act_about.triggered.connect(self.about)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(self.act_open)
        self.recent_menu = m.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addSeparator()
        m.addAction(self.act_save)
        m.addAction(self.act_save_as)
        m.addAction(self.act_close)
        m.addSeparator()
        m.addAction(self.act_print)
        m.addSeparator()
        m.addAction(self.act_quit)

        m = mb.addMenu("&Edit")
        m.addAction(self.act_copy)
        m.addAction(self.act_select_all)
        m.addAction(self.act_find)
        m.addSeparator()
        for act in self.tool_actions.values():
            m.addAction(act)

        m = mb.addMenu("&View")
        for act in (self.act_zoom_in, self.act_zoom_out, self.act_fit_width, self.act_fit_page, self.act_zoom_100):
            m.addAction(act)
        m.addSeparator()
        m.addAction(self.act_rotate_view_cw)
        m.addAction(self.act_rotate_view_ccw)
        m.addSeparator()
        m.addAction(self.dock_thumbs.toggleViewAction())
        m.addAction(self.dock_outline.toggleViewAction())
        m.addAction(self.dock_ocr.toggleViewAction())
        m.addSeparator()
        m.addAction(self.act_dark)
        m.addAction(self.act_fullscreen)

        m = mb.addMenu("&Go")
        for act in (self.act_first, self.act_prev, self.act_next, self.act_last, self.act_goto):
            m.addAction(act)

        m = mb.addMenu("&Pages")
        m.addAction(self.act_organize)
        m.addSeparator()
        m.addAction(self.act_rotate_page_cw)
        m.addAction(self.act_rotate_page_ccw)
        m.addAction(self.act_delete_page)
        m.addSeparator()
        m.addAction(self.act_merge)
        m.addAction(self.act_split)

        m = mb.addMenu("&OCR")
        m.addAction(self.act_ocr_page)
        m.addAction(self.act_ocr_all)
        m.addSeparator()
        m.addAction(self.act_ocr_searchable)
        m.addAction(self.act_ocr_export)

        m = mb.addMenu("&Help")
        m.addAction(self.act_default)
        m.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("toolbar_main")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addAction(self.act_print)
        tb.addSeparator()
        tb.addAction(self.act_prev)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.valueChanged.connect(lambda v: self.view.goto_page(v - 1))
        tb.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0 ")
        tb.addWidget(self.page_total)
        tb.addAction(self.act_next)
        tb.addSeparator()
        tb.addAction(self.act_zoom_out)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems(ZOOM_PRESETS)
        self.zoom_combo.setMinimumWidth(100)
        self.zoom_combo.activated.connect(self._zoom_combo_changed)
        self.zoom_combo.lineEdit().returnPressed.connect(lambda: self._zoom_combo_changed(-1))
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_rotate_view_cw)
        tb.addSeparator()
        for tool, act in self.tool_actions.items():
            act.setIcon(self._tool_icon(tool))
            tb.addAction(act)
        tb.addSeparator()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Find in document (Enter = next, Shift+Enter = previous)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumWidth(220)
        self.search_box.returnPressed.connect(self._search_enter)
        self.search_box.textChanged.connect(self._search_changed)
        tb.addWidget(self.search_box)
        self.search_label = QLabel("")
        tb.addWidget(self.search_label)
        tb.addSeparator()
        ocr_btn = QAction("OCR", self)
        ocr_btn.setToolTip("Show the OCR panel")
        ocr_btn.triggered.connect(lambda: (self.dock_ocr.show(), self.dock_ocr.raise_()))
        tb.addAction(ocr_btn)

    def _tool_icon(self, tool: Tool) -> QIcon:
        names = {
            Tool.SELECT: "edit-select-text",
            Tool.HAND: "transform-move",
            Tool.HIGHLIGHT: "format-text-highlight",
            Tool.UNDERLINE: "format-text-underline",
            Tool.NOTE: "note",
            Tool.INK: "draw-freehand",
        }
        return QIcon.fromTheme(names[tool])

    def _wire_signals(self) -> None:
        self.view.current_page_changed.connect(self._page_changed)
        self.view.zoom_changed.connect(self._zoom_changed)
        self.view.document_modified.connect(self._modified)
        self.view.status.connect(lambda s: self.statusBar().showMessage(s, 3000))
        self.thumbs.page_selected.connect(self.view.goto_page)
        self.outline.page_selected.connect(self.view.goto_page)

        p = self.ocr_panel
        p.ocr_current_requested.connect(self.ocr_current)
        p.ocr_all_requested.connect(self.ocr_all)
        p.cancel_requested.connect(self.cancel_ocr)
        p.make_searchable_requested.connect(self.make_searchable)
        p.export_text_requested.connect(self.export_text)
        p.locate_tesseract_requested.connect(self.locate_tesseract)
        p.language_changed.connect(lambda l: setattr(self.settings, "ocr_language", l))
        p.dpi_changed.connect(lambda d: setattr(self.settings, "ocr_dpi", d))

    # --------------------------------------------------------------- window
    def _restore_window(self) -> None:
        geo = self.settings.geometry()
        if geo:
            self.restoreGeometry(geo)
        state = self.settings.window_state()
        if state:
            self.restoreState(state)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._maybe_save():
            event.ignore()
            return
        self.cancel_ocr(wait=True)
        self.settings.set_geometry(self.saveGeometry())
        self.settings.set_window_state(self.saveState())
        if self.document:
            self.document.close()
        event.accept()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for u in event.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.open_file(path)
                break

    def _update_ui(self) -> None:
        has = self.document is not None
        self.stack.setCurrentWidget(self.view if has else self.welcome)
        for act in (
            self.act_save, self.act_save_as, self.act_close, self.act_print, self.act_prev, self.act_next,
            self.act_first, self.act_last, self.act_goto, self.act_zoom_in, self.act_zoom_out,
            self.act_fit_width, self.act_fit_page, self.act_zoom_100, self.act_rotate_view_cw,
            self.act_rotate_view_ccw, self.act_copy, self.act_select_all, self.act_find, self.act_organize,
            self.act_rotate_page_cw, self.act_rotate_page_ccw, self.act_delete_page, self.act_split,
            self.act_ocr_page, self.act_ocr_all, self.act_ocr_searchable, self.act_ocr_export,
        ):
            act.setEnabled(has)
        for act in self.tool_actions.values():
            act.setEnabled(has)
        self.page_spin.setEnabled(has)
        self.zoom_combo.setEnabled(has)
        self.search_box.setEnabled(has)
        title = APP_NAME
        if self.document:
            title = f"{'*' if self.document.modified else ''}{self.document.title} - {APP_NAME}"
            self.page_total.setText(f" / {self.document.page_count} ")
            self.page_spin.setRange(1, max(1, self.document.page_count))
        else:
            self.page_total.setText(" / 0 ")
        self.setWindowTitle(title)

    # ---------------------------------------------------------------- files
    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", self.settings.last_dir, "PDF files (*.pdf);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> bool:
        if not self._maybe_save():
            return False
        try:
            doc = Document(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open PDF", f"Could not open\n{path}\n\n{exc}")
            return False
        while doc.needs_password:
            pw, ok = QInputDialog.getText(self, "Password required", "This PDF is encrypted. Password:", QLineEdit.EchoMode.Password)
            if not ok:
                doc.close()
                return False
            if doc.authenticate(pw):
                break
            QMessageBox.warning(self, "Password", "Wrong password, try again.")
        self._set_document(doc)
        self.settings.add_recent(path)
        self.settings.last_dir = os.path.dirname(path)
        self.welcome.refresh()
        self.statusBar().showMessage(f"Opened {path}", 4000)
        return True

    def _set_document(self, doc: Document | None) -> None:
        self.cancel_ocr(wait=True)
        if self.document is not None:
            self.document.close()
        self.document = doc
        self.view.set_document(doc)
        self.thumbs.set_document(doc)
        self.outline.set_document(doc)
        self.ocr_panel.clear_results()
        self.search_box.clear()
        self.view.set_tool(Tool.SELECT)
        self.tool_actions[Tool.SELECT].setChecked(True)
        self._update_ui()
        if doc:
            self._page_changed(0)

    def close_document(self) -> None:
        if self._maybe_save():
            self._set_document(None)

    def _maybe_save(self) -> bool:
        if not self.document or not self.document.modified:
            return True
        ret = QMessageBox.question(
            self, "Unsaved changes", f"Save changes to {self.document.title}?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if ret == QMessageBox.StandardButton.Save:
            return self.save()
        return ret == QMessageBox.StandardButton.Discard

    def save(self) -> bool:
        if not self.document:
            return False
        if not self.document.path:
            return self.save_as()
        return self._do_save(self.document.path)

    def save_as(self) -> bool:
        if not self.document:
            return False
        start = self.document.path or os.path.join(self.settings.last_dir, "document.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF as", start, "PDF files (*.pdf)")
        if not path:
            return False
        return self._do_save(path)

    def _do_save(self, path: str) -> bool:
        try:
            self.document.save(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save PDF", f"Could not save:\n{exc}")
            return False
        self.settings.add_recent(path)
        self.view.invalidate_all()
        self._update_ui()
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = self.settings.recent_files()
        for p in files:
            self.recent_menu.addAction(p, lambda _c=False, p=p: self.open_file(p))
        if files:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear list", lambda: (self.settings.clear_recent(), self.welcome.refresh()))
        else:
            self.recent_menu.addAction("(empty)").setEnabled(False)

    def print_document(self) -> None:
        if not self.document:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.document.title)
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, self.document.page_count)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        first, last = printer.fromPage(), printer.toPage()
        if first == 0 and last == 0:
            first, last = 1, self.document.page_count
        painter = QPainter(printer)
        try:
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            for pno in range(first - 1, last):
                if pno != first - 1:
                    printer.newPage()
                w, h = self.document.page(pno).rect.width, self.document.page(pno).rect.height
                scale = min(page_rect.width() / w, page_rect.height() / h)
                img = self.document.render(pno, scale, 0)
                x = (page_rect.width() - img.width()) / 2
                y = (page_rect.height() - img.height()) / 2
                painter.drawImage(int(x), int(y), img)
        finally:
            painter.end()
        self.statusBar().showMessage("Sent to printer", 4000)

    # ----------------------------------------------------------- navigation
    def _page_changed(self, pno: int) -> None:
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(pno + 1)
        self.page_spin.blockSignals(False)
        self.thumbs.set_current(pno)
        self.ocr_panel.show_page(pno)

    def goto_page_dialog(self) -> None:
        if not self.document:
            return
        n, ok = QInputDialog.getInt(self, "Go to page", "Page:", self.view.current_page() + 1, 1, self.document.page_count)
        if ok:
            self.view.goto_page(n - 1)

    def _zoom_changed(self, zoom: float) -> None:
        mode = self.view.zoom_mode
        text = "Fit width" if mode == "fit-width" else "Fit page" if mode == "fit-page" else f"{int(round(zoom * 100))}%"
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setEditText(text)
        self.zoom_combo.blockSignals(False)

    def _zoom_combo_changed(self, _index: int) -> None:
        text = self.zoom_combo.currentText().strip()
        if text == "Fit width":
            self.view.set_zoom_mode("fit-width")
        elif text == "Fit page":
            self.view.set_zoom_mode("fit-page")
        else:
            try:
                self.view.set_zoom(float(text.rstrip("%")) / 100)
            except ValueError:
                self._zoom_changed(self.view.zoom)

    def toggle_dark(self, on: bool) -> None:
        self.settings.dark_mode = on
        apply_theme(QApplication.instance(), on)

    def _modified(self) -> None:
        self._update_ui()
        self.thumbs.refresh_page(self.view.current_page())

    # --------------------------------------------------------------- search
    def _search_changed(self, text: str) -> None:
        if not self.document:
            return
        hits = self.document.search(text) if len(text) >= 1 else {}
        self.view.set_search_hits(hits)
        n = self.view.hit_count()
        if text and n:
            idx = self.view.step_hit(True)
            self.search_label.setText(f" {idx} / {n} ")
        else:
            self.search_label.setText(" no matches " if text else "")

    def _search_enter(self) -> None:
        forward = not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        idx = self.view.step_hit(forward)
        n = self.view.hit_count()
        if n:
            self.search_label.setText(f" {idx} / {n} ")

    # ----------------------------------------------------------- page tools
    def organize_pages(self) -> None:
        if not self.document:
            return
        dlg = OrganizeDialog(self.document, self)
        dlg.exec()
        if dlg.changed:
            self._after_structure_change()

    def _after_structure_change(self) -> None:
        self.view.rebuild_items()
        self.thumbs.set_document(self.document)
        self.outline.set_document(self.document)
        self.ocr_panel.clear_results()
        self._update_ui()

    def rotate_current_page(self, degrees: int) -> None:
        if not self.document:
            return
        pno = self.view.current_page()
        self.document.rotate_page(pno, degrees)
        self.view.rebuild_items()
        self.view.goto_page(pno)
        self.thumbs.refresh_page(pno)
        self._update_ui()

    def delete_current_page(self) -> None:
        if not self.document:
            return
        if self.document.page_count <= 1:
            QMessageBox.warning(self, "Delete page", "A document must keep at least one page.")
            return
        pno = self.view.current_page()
        if QMessageBox.question(self, "Delete page", f"Delete page {pno + 1}?") != QMessageBox.StandardButton.Yes:
            return
        self.document.delete_pages([pno])
        self._after_structure_change()

    def merge_pdfs(self) -> None:
        initial = [self.document.path] if self.document and self.document.path else []
        dlg = MergeDialog(self, initial)
        if dlg.exec() == MergeDialog.DialogCode.Accepted and dlg.output_path:
            if QMessageBox.question(self, "Merge PDFs", "Open the merged file now?") == QMessageBox.StandardButton.Yes:
                self.open_file(dlg.output_path)

    def split_pdf(self) -> None:
        if not self.document or not self.document.path:
            QMessageBox.information(self, "Split PDF", "Save the document first.")
            return
        if self.document.modified and not self._maybe_save():
            return
        SplitDialog(self.document.path, self).exec()

    # ------------------------------------------------------------------ OCR
    def _init_ocr(self) -> None:
        exe = ocr_mod.find_tesseract(self.settings.tesseract_path)
        if exe:
            ocr_mod.configure_tesseract(exe)
            langs = ocr_mod.available_languages()
            self.ocr_panel.set_tesseract_status(f"Tesseract {ocr_mod.tesseract_version()} found at\n{exe}", True)
            self.ocr_panel.set_languages(langs, self.settings.ocr_language)
        else:
            self.ocr_panel.set_tesseract_status(
                "Tesseract not found. Install it (e.g. from the UB Mannheim builds) or click 'Locate tesseract.exe...'.", False)
            self.ocr_panel.set_languages(["eng"], "eng")
        self.ocr_panel.set_dpi(self.settings.ocr_dpi)

    def locate_tesseract(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate tesseract.exe", "", "tesseract.exe (tesseract.exe);;All files (*)")
        if path:
            self.settings.tesseract_path = path
            self._init_ocr()

    def _start_ocr(self, pages: list[int]) -> None:
        if not self.document or self.worker is not None or not pages:
            return
        self.worker = ocr_mod.OcrWorker(self.document, pages, self.ocr_panel.lang_combo.currentText() or "eng", self.ocr_panel.dpi_spin.value())
        self.worker.progress.connect(self.ocr_panel.set_progress)
        self.worker.page_done.connect(self.ocr_panel.add_result)
        self.worker.failed.connect(lambda msg: QMessageBox.critical(self, "OCR failed", msg))
        self.worker.completed.connect(self._ocr_done)
        self.ocr_panel.set_busy(True)
        self.ocr_panel.set_progress(0, len(pages))
        self.dock_ocr.show()
        self.dock_ocr.raise_()
        self.statusBar().showMessage(f"Running OCR on {len(pages)} page(s)...")
        self.worker.start()

    def _ocr_done(self, cancelled: bool) -> None:
        self.ocr_panel.set_busy(False)
        if self.worker:
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None
        n = len(self.ocr_panel.results)
        self.statusBar().showMessage("OCR cancelled" if cancelled else f"OCR finished - {n} page(s) recognized", 5000)

    def ocr_current(self) -> None:
        if self.document:
            self._start_ocr([self.view.current_page()])

    def ocr_all(self) -> None:
        if self.document:
            self._start_ocr(list(range(self.document.page_count)))

    def cancel_ocr(self, wait: bool = False) -> None:
        if self.worker is not None:
            self.worker.cancel()
            if wait:
                self.worker.wait()

    def make_searchable(self) -> None:
        if not self.document:
            return
        results = self.ocr_panel.results
        if not results:
            QMessageBox.information(self, "Searchable PDF", "Run OCR first (OCR this page / OCR all pages).")
            return
        base = os.path.splitext(self.document.path or os.path.join(self.settings.last_dir, "document"))[0]
        path, _ = QFileDialog.getSaveFileName(self, "Save searchable PDF as", f"{base}_ocr.pdf", "PDF files (*.pdf)")
        if not path:
            return
        total = 0
        for res in results.values():
            total += ocr_mod.add_text_layer(self.document, res)
        try:
            self.document.save(path)
        except Exception as exc:
            QMessageBox.critical(self, "Searchable PDF", f"Could not save:\n{exc}")
            return
        self.settings.add_recent(path)
        self.view.invalidate_all()
        self._update_ui()
        QMessageBox.information(self, "Searchable PDF", f"Added an invisible text layer ({total} words on {len(results)} page(s)) and saved\n{path}")

    def export_text(self) -> None:
        results = self.ocr_panel.results
        if not results:
            QMessageBox.information(self, "Export text", "Run OCR first.")
            return
        base = os.path.splitext(self.document.path or "document")[0] if self.document else "document"
        path, _ = QFileDialog.getSaveFileName(self, "Export OCR text", f"{base}.txt", "Text files (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ocr_mod.results_to_text(results))
        self.statusBar().showMessage(f"Exported text to {path}", 5000)

    # ---------------------------------------------------------------- misc
    def set_default_viewer(self) -> None:
        QMessageBox.information(
            self, "Default PDF viewer",
            "Windows only lets you pick the default app yourself.\n\n"
            "The Settings page will open: find '.pdf' (or 'PDF Reader OCR' in the app list) and choose this app.",
        )
        if sys.platform == "win32":
            QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))

    def about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>A free, open-source PDF reader with OCR.</p>"
            "<p>Built with PySide6, PyMuPDF and Tesseract OCR.<br>"
            "Licensed under the MIT License; bundled components keep their own licenses "
            "(PyMuPDF: AGPL-3.0, Tesseract: Apache-2.0, Qt: LGPL-3.0).</p>"
            "<p><a href='https://github.com/zimba7768/pdf-reader-ocr'>github.com/zimba7768/pdf-reader-ocr</a></p>",
        )
