"""Light / dark theme handling."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, dark: bool) -> None:
    app.setStyle("Fusion")
    if not dark:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")
        return

    p = QPalette()
    base = QColor(37, 37, 38)
    window = QColor(45, 45, 48)
    text = QColor(220, 220, 220)
    disabled = QColor(128, 128, 128)
    highlight = QColor(42, 130, 218)

    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, window)
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, window)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.ColorRole.Link, highlight)
    p.setColor(QPalette.ColorRole.Highlight, highlight)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    app.setPalette(p)
    app.setStyleSheet(
        "QToolTip { color: #ddd; background: #252526; border: 1px solid #555; }"
        "QDockWidget::title { background: #3a3a3d; padding: 4px; }"
    )
