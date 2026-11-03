"""Application entry point."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pdf_reader_ocr import APP_NAME, ORG_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # Keep HiDPI rendering crisp.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)

    from pdf_reader_ocr.main_window import MainWindow, app_icon

    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    for arg in argv[1:]:
        if os.path.isfile(arg):
            window.open_file(arg)
            break
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
