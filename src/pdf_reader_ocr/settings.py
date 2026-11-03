"""Persistent user settings (QSettings-backed)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from pdf_reader_ocr import APP_NAME, ORG_NAME

MAX_RECENT = 12


class Settings:
    def __init__(self) -> None:
        self._s = QSettings(ORG_NAME, APP_NAME)

    # ---- recent files -------------------------------------------------
    def recent_files(self) -> list[str]:
        value = self._s.value("recent/files", [])
        if isinstance(value, str):
            value = [value]
        return [p for p in (value or []) if os.path.isfile(p)]

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        files = [p for p in self.recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        files.insert(0, path)
        self._s.setValue("recent/files", files[:MAX_RECENT])

    def clear_recent(self) -> None:
        self._s.setValue("recent/files", [])

    # ---- appearance ---------------------------------------------------
    @property
    def dark_mode(self) -> bool:
        return self._s.value("ui/dark", False, type=bool)

    @dark_mode.setter
    def dark_mode(self, value: bool) -> None:
        self._s.setValue("ui/dark", bool(value))

    def geometry(self) -> bytes | None:
        return self._s.value("ui/geometry")

    def set_geometry(self, data) -> None:
        self._s.setValue("ui/geometry", data)

    def window_state(self):
        return self._s.value("ui/state")

    def set_window_state(self, data) -> None:
        self._s.setValue("ui/state", data)

    # ---- OCR ----------------------------------------------------------
    @property
    def ocr_language(self) -> str:
        return self._s.value("ocr/lang", "eng", type=str)

    @ocr_language.setter
    def ocr_language(self, value: str) -> None:
        self._s.setValue("ocr/lang", value)

    @property
    def ocr_dpi(self) -> int:
        return self._s.value("ocr/dpi", 300, type=int)

    @ocr_dpi.setter
    def ocr_dpi(self, value: int) -> None:
        self._s.setValue("ocr/dpi", int(value))

    @property
    def tesseract_path(self) -> str:
        return self._s.value("ocr/tesseract", "", type=str)

    @tesseract_path.setter
    def tesseract_path(self, value: str) -> None:
        self._s.setValue("ocr/tesseract", value)

    @property
    def last_dir(self) -> str:
        return self._s.value("files/last_dir", "", type=str)

    @last_dir.setter
    def last_dir(self, value: str) -> None:
        self._s.setValue("files/last_dir", value)
