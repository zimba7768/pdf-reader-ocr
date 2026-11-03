"""Continuous-scroll page viewer with selection, search overlay and annotation tools."""
from __future__ import annotations

from collections import OrderedDict
from enum import Enum, auto

import pymupdf
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QGuiApplication
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QMenu,
)

from pdf_reader_ocr.document import Document

GAP = 14
MAX_CACHE = 48
ZOOM_MIN, ZOOM_MAX = 0.1, 8.0


class Tool(Enum):
    SELECT = auto()
    HAND = auto()
    HIGHLIGHT = auto()
    UNDERLINE = auto()
    NOTE = auto()
    INK = auto()


class PageItem(QGraphicsItem):
    def __init__(self, view: "PageView", pno: int) -> None:
        super().__init__()
        self.view = view
        self.pno = pno
        self.size = QSizeF(100, 100)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, self.size.width(), self.size.height())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        view = self.view
        img = view.image_for(self.pno)
        if img is not None:
            painter.drawImage(0, 0, img)
        else:
            painter.fillRect(self.boundingRect(), Qt.GlobalColor.white)

        # search hits
        hits = view.search_hits.get(self.pno)
        if hits:
            for i, r in enumerate(hits):
                qr = view.page_rect_to_item(self.pno, r)
                if view.current_hit == (self.pno, i):
                    painter.fillRect(qr, QColor(255, 140, 0, 140))
                    painter.setPen(QPen(QColor(220, 90, 0), 1.5))
                    painter.drawRect(qr)
                else:
                    painter.fillRect(qr, QColor(255, 220, 0, 110))

        # text selection
        if view.selection_page == self.pno:
            for r in view.selection_rects:
                painter.fillRect(view.page_rect_to_item(self.pno, r), QColor(30, 120, 255, 80))
            if view.drag_rect is not None and view.tool in (Tool.SELECT, Tool.HIGHLIGHT, Tool.UNDERLINE):
                painter.setPen(QPen(QColor(30, 120, 255, 160), 1, Qt.PenStyle.DashLine))
                painter.drawRect(view.page_rect_to_item(self.pno, view.drag_rect))

        # in-progress ink stroke
        if view.ink_page == self.pno and len(view.ink_points) > 1:
            path = QPainterPath()
            pts = [view.page_point_to_item(self.pno, p) for p in view.ink_points]
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            painter.setPen(QPen(QColor(220, 30, 30), 2.5 * view.zoom, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)

        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawRect(self.boundingRect().adjusted(0, 0, -1, -1))


class PageView(QGraphicsView):
    current_page_changed = Signal(int)
    zoom_changed = Signal(float)
    document_modified = Signal()
    selection_changed = Signal(str)
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.document: Document | None = None
        self.zoom = 1.0
        self.zoom_mode = "fit-width"  # "fit-width" | "fit-page" | "custom"
        self.rotation = 0
        self.tool = Tool.SELECT
        self.items: list[PageItem] = []
        self._cache: OrderedDict[int, tuple[float, int, QImage]] = OrderedDict()
        self._current_page = 0

        self.search_hits: dict[int, list[pymupdf.Rect]] = {}
        self.current_hit: tuple[int, int] | None = None

        self.selection_page: int | None = None
        self.selection_rects: list[pymupdf.Rect] = []
        self.selection_text = ""
        self.drag_rect: pymupdf.Rect | None = None
        self._drag_start: tuple[int, pymupdf.Point] | None = None

        self.ink_page: int | None = None
        self.ink_points: list[pymupdf.Point] = []

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setBackgroundBrush(QColor(82, 86, 89))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.verticalScrollBar().valueChanged.connect(self._track_current_page)

        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(80)
        self._relayout_timer.timeout.connect(self._apply_zoom_mode)

    # ------------------------------------------------------------------ setup
    def set_document(self, document: Document | None) -> None:
        self._scene.clear()
        self.items.clear()
        self._cache.clear()
        self.search_hits.clear()
        self.current_hit = None
        self.clear_selection()
        self.document = document
        self.rotation = 0
        if document is None:
            self._scene.setSceneRect(QRectF())
            return
        for pno in range(document.page_count):
            item = PageItem(self, pno)
            self._scene.addItem(item)
            self.items.append(item)
        self._apply_zoom_mode()
        self.verticalScrollBar().setValue(0)
        self._current_page = -1
        self._track_current_page()

    def rebuild_items(self) -> None:
        """Call after pages were added/removed/reordered."""
        doc = self.document
        page = self.current_page()
        self.set_document(doc)
        self.goto_page(min(page, (doc.page_count - 1) if doc else 0))

    # --------------------------------------------------------------- geometry
    def _mat(self) -> pymupdf.Matrix:
        return Document.render_matrix(self.zoom, self.rotation)

    def _offset(self, pno: int) -> tuple[int, int]:
        r = self.document.rendered_rect(pno, self.zoom, self.rotation)
        return r.x0, r.y0

    def page_rect_to_item(self, pno: int, rect: pymupdf.Rect) -> QRectF:
        page = self.document.page(pno)
        r = pymupdf.Rect(rect) * page.rotation_matrix * self._mat()
        ox, oy = self._offset(pno)
        return QRectF(r.x0 - ox, r.y0 - oy, r.width, r.height)

    def page_point_to_item(self, pno: int, pt: pymupdf.Point) -> QPointF:
        page = self.document.page(pno)
        p = pymupdf.Point(pt) * page.rotation_matrix * self._mat()
        ox, oy = self._offset(pno)
        return QPointF(p.x - ox, p.y - oy)

    def item_to_page_point(self, pno: int, qpt: QPointF) -> pymupdf.Point:
        page = self.document.page(pno)
        ox, oy = self._offset(pno)
        return pymupdf.Point(qpt.x() + ox, qpt.y() + oy) * ~self._mat() * page.derotation_matrix

    def _relayout(self) -> None:
        if not self.document:
            return
        sizes = [self.document.rendered_rect(i, self.zoom, self.rotation) for i in range(len(self.items))]
        max_w = max((s.width for s in sizes), default=0)
        y = GAP
        for item, s in zip(self.items, sizes):
            item.prepareGeometryChange()
            item.size = QSizeF(s.width, s.height)
            item.setPos(GAP + (max_w - s.width) / 2, y)
            y += s.height + GAP
        self._scene.setSceneRect(0, 0, max_w + 2 * GAP, y)
        self._cache.clear()
        self.viewport().update()

    # ------------------------------------------------------------------- zoom
    def _viewport_width(self) -> int:
        return max(50, self.viewport().width() - 2 * GAP)

    def _apply_zoom_mode(self) -> None:
        if not self.document or not self.items:
            return
        base = [self.document.rendered_rect(i, 1.0, self.rotation) for i in range(len(self.items))]
        max_w = max(b.width for b in base)
        max_h = max(b.height for b in base)
        if self.zoom_mode == "fit-width":
            self.zoom = self._viewport_width() / max_w
        elif self.zoom_mode == "fit-page":
            h = max(50, self.viewport().height() - 2 * GAP)
            self.zoom = min(self._viewport_width() / max_w, h / max_h)
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom))
        self._keep_position(self._relayout)
        self.zoom_changed.emit(self.zoom)

    def _keep_position(self, fn) -> None:
        sb = self.verticalScrollBar()
        total = max(1, self._scene.sceneRect().height())
        frac = (sb.value() + self.viewport().height() / 2) / total
        fn()
        total = max(1, self._scene.sceneRect().height())
        sb.setValue(int(frac * total - self.viewport().height() / 2))

    def set_zoom(self, zoom: float) -> None:
        self.zoom_mode = "custom"
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        self._keep_position(self._relayout)
        self.zoom_changed.emit(self.zoom)

    def set_zoom_mode(self, mode: str) -> None:
        self.zoom_mode = mode
        self._apply_zoom_mode()

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / 1.25)

    def rotate_view(self, degrees: int) -> None:
        self.rotation = (self.rotation + degrees) % 360
        self._apply_zoom_mode()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.zoom_mode != "custom":
            self._relayout_timer.start()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    # --------------------------------------------------------------- rendering
    def image_for(self, pno: int) -> QImage | None:
        if not self.document:
            return None
        entry = self._cache.get(pno)
        if entry and entry[0] == self.zoom and entry[1] == self.rotation:
            self._cache.move_to_end(pno)
            return entry[2]
        try:
            img = self.document.render(pno, self.zoom, self.rotation)
        except Exception:
            return None
        self._cache[pno] = (self.zoom, self.rotation, img)
        while len(self._cache) > MAX_CACHE:
            self._cache.popitem(last=False)
        return img

    def invalidate_page(self, pno: int) -> None:
        self._cache.pop(pno, None)
        self.document.invalidate(pno)
        if 0 <= pno < len(self.items):
            self.items[pno].update()

    def invalidate_all(self) -> None:
        self._cache.clear()
        if self.document:
            self.document.invalidate()
        self.viewport().update()

    # ------------------------------------------------------------- navigation
    def page_count(self) -> int:
        return len(self.items)

    def current_page(self) -> int:
        return max(0, self._current_page)

    def _track_current_page(self) -> None:
        if not self.items:
            return
        center_y = self.verticalScrollBar().value() + self.viewport().height() / 2
        best = 0
        for item in self.items:
            if item.y() <= center_y:
                best = item.pno
            else:
                break
        if best != self._current_page:
            self._current_page = best
            self.current_page_changed.emit(best)

    def goto_page(self, pno: int) -> None:
        if not self.items:
            return
        pno = max(0, min(len(self.items) - 1, pno))
        self.verticalScrollBar().setValue(int(self.items[pno].y() - GAP))
        self._current_page = pno
        self.current_page_changed.emit(pno)

    def next_page(self) -> None:
        self.goto_page(self.current_page() + 1)

    def prev_page(self) -> None:
        self.goto_page(self.current_page() - 1)

    # ----------------------------------------------------------------- search
    def set_search_hits(self, hits: dict[int, list[pymupdf.Rect]]) -> None:
        self.search_hits = hits
        self.current_hit = None
        self.viewport().update()

    def hit_count(self) -> int:
        return sum(len(v) for v in self.search_hits.values())

    def _ordered_hits(self) -> list[tuple[int, int]]:
        return [(p, i) for p in sorted(self.search_hits) for i in range(len(self.search_hits[p]))]

    def step_hit(self, forward: bool = True) -> int:
        """Move to next/previous hit. Returns 1-based index of current hit (0 if none)."""
        order = self._ordered_hits()
        if not order:
            return 0
        if self.current_hit is None:
            # start from the first hit on/after the current page
            idx = next((k for k, (p, _) in enumerate(order) if p >= self.current_page()), 0)
            if not forward:
                idx = (idx - 1) % len(order)
        else:
            idx = order.index(self.current_hit) if self.current_hit in order else 0
            idx = (idx + (1 if forward else -1)) % len(order)
        self.current_hit = order[idx]
        pno, i = self.current_hit
        rect = self.page_rect_to_item(pno, self.search_hits[pno][i])
        self.centerOn(self.items[pno].mapToScene(rect.center()))
        self.viewport().update()
        return idx + 1

    # -------------------------------------------------------------- selection
    def clear_selection(self) -> None:
        old = self.selection_page
        self.selection_page = None
        self.selection_rects = []
        self.selection_text = ""
        self.drag_rect = None
        if old is not None and old < len(self.items):
            self.items[old].update()
        self.selection_changed.emit("")

    def select_all_on_page(self, pno: int | None = None) -> None:
        pno = self.current_page() if pno is None else pno
        words = self.document.words(pno)
        self.selection_page = pno
        self.selection_rects = [w.rect for w in words]
        self.selection_text = _words_to_text(words)
        self.items[pno].update()
        self.selection_changed.emit(self.selection_text)

    def copy_selection(self) -> None:
        if self.selection_text:
            QGuiApplication.clipboard().setText(self.selection_text)
            self.status.emit("Copied selection to clipboard")

    def _update_selection(self, pno: int, rect: pymupdf.Rect) -> None:
        words = [w for w in self.document.words(pno) if w.rect.intersects(rect)]
        self.selection_page = pno
        self.selection_rects = [w.rect for w in words]
        self.selection_text = _words_to_text(words)
        self.drag_rect = rect
        self.items[pno].update()

    # ------------------------------------------------------------------- tools
    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.clear_selection()
        if tool == Tool.HAND:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        cursors = {
            Tool.SELECT: Qt.CursorShape.IBeamCursor,
            Tool.HAND: Qt.CursorShape.OpenHandCursor,
            Tool.HIGHLIGHT: Qt.CursorShape.CrossCursor,
            Tool.UNDERLINE: Qt.CursorShape.CrossCursor,
            Tool.NOTE: Qt.CursorShape.PointingHandCursor,
            Tool.INK: Qt.CursorShape.CrossCursor,
        }
        self.viewport().setCursor(cursors[tool])

    def _page_at(self, viewport_pos) -> tuple[int, QPointF] | None:
        scene_pos = self.mapToScene(viewport_pos)
        for item in self._scene.items(scene_pos):
            if isinstance(item, PageItem):
                return item.pno, item.mapFromScene(scene_pos)
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.document or event.button() != Qt.MouseButton.LeftButton or self.tool == Tool.HAND:
            return super().mousePressEvent(event)
        hit = self._page_at(event.position().toPoint())
        if hit is None:
            self.clear_selection()
            return super().mousePressEvent(event)
        pno, item_pt = hit
        page_pt = self.item_to_page_point(pno, item_pt)
        if self.tool in (Tool.SELECT, Tool.HIGHLIGHT, Tool.UNDERLINE):
            self.clear_selection()
            self._drag_start = (pno, page_pt)
        elif self.tool == Tool.INK:
            self.ink_page = pno
            self.ink_points = [page_pt]
        elif self.tool == Tool.NOTE:
            self._add_note(pno, page_pt)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            pno, start = self._drag_start
            hit = self._page_at(event.position().toPoint())
            if hit is not None and hit[0] == pno:
                cur = self.item_to_page_point(pno, hit[1])
            else:
                # clamp to the page we started on
                item = self.items[pno]
                local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
                local.setX(max(0.0, min(item.size.width(), local.x())))
                local.setY(max(0.0, min(item.size.height(), local.y())))
                cur = self.item_to_page_point(pno, local)
            rect = pymupdf.Rect(start, cur).normalize()
            self._update_selection(pno, rect)
            event.accept()
            return
        if self.ink_page is not None:
            hit = self._page_at(event.position().toPoint())
            if hit is not None and hit[0] == self.ink_page:
                self.ink_points.append(self.item_to_page_point(self.ink_page, hit[1]))
                self.items[self.ink_page].update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            pno, _ = self._drag_start
            self._drag_start = None
            self.drag_rect = None
            if self.tool == Tool.HIGHLIGHT and self.selection_rects:
                self._add_markup(pno, "highlight")
            elif self.tool == Tool.UNDERLINE and self.selection_rects:
                self._add_markup(pno, "underline")
            else:
                self.items[pno].update()
                self.selection_changed.emit(self.selection_text)
            event.accept()
            return
        if self.ink_page is not None:
            pno, pts = self.ink_page, self.ink_points
            self.ink_page, self.ink_points = None, []
            if len(pts) > 1:
                with self.document.lock:
                    annot = self.document.page(pno).add_ink_annot([[(p.x, p.y) for p in pts]])
                    annot.set_colors(stroke=(0.86, 0.12, 0.12))
                    annot.set_border(width=2)
                    annot.update()
                self._after_edit(pno)
            else:
                self.items[pno].update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self.document:
            return
        hit = self._page_at(event.pos())
        menu = QMenu(self)
        if self.selection_text:
            menu.addAction("Copy", self.copy_selection)
            menu.addAction("Highlight selection", lambda: self._add_markup(self.selection_page, "highlight"))
            menu.addAction("Underline selection", lambda: self._add_markup(self.selection_page, "underline"))
            menu.addSeparator()
        if hit is not None:
            pno, item_pt = hit
            page_pt = self.item_to_page_point(pno, item_pt)
            annots = self._annots_at(pno, page_pt)
            for annot_xref, label in annots:
                menu.addAction(f"Delete {label}", lambda x=annot_xref, p=pno: self._delete_annot(p, x))
            menu.addAction("Select all text on page", lambda p=pno: self.select_all_on_page(p))
        if menu.actions():
            menu.exec(event.globalPos())

    # ------------------------------------------------------------ annotations
    def _add_markup(self, pno: int, kind: str) -> None:
        rects = list(self.selection_rects)
        if pno is None or not rects:
            return
        with self.document.lock:
            page = self.document.page(pno)
            if kind == "highlight":
                annot = page.add_highlight_annot(rects)
            else:
                annot = page.add_underline_annot(rects)
            annot.update()
        self.clear_selection()
        self._after_edit(pno)

    def _add_note(self, pno: int, pt: pymupdf.Point) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Add note", "Note text:")
        if not ok or not text.strip():
            return
        with self.document.lock:
            annot = self.document.page(pno).add_text_annot(pt, text, icon="Comment")
            annot.update()
        self._after_edit(pno)

    def _annots_at(self, pno: int, pt: pymupdf.Point) -> list[tuple[int, str]]:
        found = []
        with self.document.lock:
            for annot in self.document.page(pno).annots():
                if annot.rect.contains(pt):
                    found.append((annot.xref, annot.type[1].lower() or "annotation"))
        return found

    def _delete_annot(self, pno: int, xref: int) -> None:
        with self.document.lock:
            page = self.document.page(pno)
            for annot in page.annots():
                if annot.xref == xref:
                    page.delete_annot(annot)
                    break
        self._after_edit(pno)

    def _after_edit(self, pno: int) -> None:
        self.document.mark_modified()
        self.invalidate_page(pno)
        self.document_modified.emit()


def _words_to_text(words) -> str:
    lines: list[str] = []
    current: list[str] = []
    key = None
    for w in sorted(words, key=lambda w: (w.block, w.line, w.index)):
        k = (w.block, w.line)
        if k != key and current:
            lines.append(" ".join(current))
            current = []
        key = k
        current.append(w.text)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)
