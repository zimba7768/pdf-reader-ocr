# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PDF Reader OCR.

Build (from the repository root):
    pyinstaller packaging/pdf_reader_ocr.spec --noconfirm
Output: dist/PDFReaderOCR/PDFReaderOCR.exe  (one-folder build)
"""
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

datas = [(os.path.join(SRC, "pdf_reader_ocr", "resources"), os.path.join("pdf_reader_ocr", "resources"))]
datas += collect_data_files("pymupdf")

a = Analysis(
    [os.path.join(SRC, "pdf_reader_ocr", "__main__.py")],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=["pytesseract", "PIL.Image", "PySide6.QtPrintSupport"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
        "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "tkinter", "unittest", "pydoc", "numpy", "yaml",
    ],
    noarchive=False,
)

# Drop Qt modules PyInstaller pulls in transitively but the app never loads.
_DROP_BINARIES = (
    "opengl32sw.dll", "qt6quick", "qt6qml", "qt6virtualkeyboard", "qt6pdf", "qt6network", "qtnetwork",
    "qt6svg", "qt6opengl", "d3dcompiler", "libegl", "libglesv2", "numpy",
)
_DROP_DATAS = ("pyside6\\translations", "pyside6/translations", "qml")


def _keep_binary(entry):
    name = entry[0].lower()
    return not any(p in name for p in _DROP_BINARIES)


def _keep_data(entry):
    name = entry[0].lower()
    return not any(p in name for p in _DROP_DATAS)


a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_data(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFReaderOCR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(SRC, "pdf_reader_ocr", "resources", "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PDFReaderOCR",
)
