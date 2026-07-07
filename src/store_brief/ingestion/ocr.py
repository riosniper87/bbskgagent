"""Local OCR for scanned PDF pages (Tesseract kor, offline)."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_tesseract_checked = False
_tesseract_available = False


def tesseract_available() -> bool:
    """Return True if tesseract binary and kor data are reachable."""
    global _tesseract_checked, _tesseract_available
    if _tesseract_checked:
        return _tesseract_available
    _tesseract_checked = True
    if not shutil.which("tesseract"):
        log.info("tesseract not found on PATH — OCR disabled")
        return False
    try:
        import pytesseract
        pytesseract.get_languages(config="")
        _tesseract_available = True
    except Exception as exc:
        log.info("pytesseract unavailable: %s", exc)
        _tesseract_available = False
    return _tesseract_available


def ocr_image(path: str | Path, *, lang: str = "kor") -> str:
    """Run Tesseract OCR on a PNG/JPEG image file."""
    if not tesseract_available():
        return ""
    import pytesseract
    from PIL import Image

    img = Image.open(path)
    text = pytesseract.image_to_string(img, lang=lang)
    return (text or "").strip()


def ocr_pixmap(pix, *, lang: str = "kor") -> str:
    """OCR a PyMuPDF pixmap (in-memory)."""
    if not tesseract_available():
        return ""
    import io

    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return (pytesseract.image_to_string(img, lang=lang) or "").strip()
