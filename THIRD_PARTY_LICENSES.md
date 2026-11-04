# Third-party licenses

The PDF Reader OCR application code is MIT licensed (see [LICENSE](LICENSE)).
The Windows installer bundles the following components, which keep their own
licenses:

| Component | License | Source |
|-----------|---------|--------|
| PyMuPDF / MuPDF | GNU AGPL v3 | https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright |
| Tesseract OCR | Apache License 2.0 | https://github.com/tesseract-ocr/tesseract |
| Leptonica | BSD 2-Clause | https://github.com/DanBloomberg/leptonica |
| Qt / PySide6 | GNU LGPL v3 | https://www.qt.io/licensing |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |
| pytesseract | Apache License 2.0 | https://github.com/madmaze/pytesseract |
| Python | PSF License | https://www.python.org/psf/license/ |
| Tesseract runtime DLLs (libarchive, libcurl, libpng, libjpeg, libtiff, libwebp, OpenJPEG, zlib, zstd, xz, lz4, bzip2, brotli, OpenSSL and others) | Their respective permissive licenses | Shipped by the UB-Mannheim Tesseract build |

Because PyMuPDF is AGPL-3.0, redistributing a modified build of this
application requires making the corresponding source available under the
AGPL's terms. The source of this project is public at
https://github.com/zimba7768/pdf-reader-ocr.
