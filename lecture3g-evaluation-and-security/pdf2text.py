# PDF-to-text utility with automatic OCR fallback for image-only PDFs.
#
# to use you must 'brew install tesseract poppler' to get the needed system tools

import re
from dataclasses import dataclass
from typing import List, Optional

from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract


@dataclass
class OCRResult:
    text: str
    used_ocr: bool
    page_count: int
    ocr_pages: int
    warnings: List[str]


def _clean_text(txt: str) -> str:
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def pdf_text_or_ocr(
    pdf_path: str,
    *,
    dpi: int = 200,
    lang: str = "eng",
    poppler_path: Optional[str] = None,
    tesseract_cmd: Optional[str] = None,
    min_text_len: int = 20,
    psm: Optional[int] = None,
) -> OCRResult:
    warnings: List[str] = []

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    embedded_text_parts: List[str] = []
    page_count = 0
    try:
        reader = PdfReader(pdf_path)
        page_count = len(reader.pages)
        for page in reader.pages:
            embedded_text_parts.append(page.extract_text() or "")
    except Exception as exc:
        warnings.append(f"pypdf extract_text failed: {exc}")

    embedded_text = "\n".join(text for text in embedded_text_parts if text).strip()
    if len(embedded_text) >= min_text_len:
        return OCRResult(
            text=_clean_text(embedded_text),
            used_ocr=False,
            page_count=page_count or 0,
            ocr_pages=0,
            warnings=warnings,
        )

    convert_kwargs = {"dpi": dpi}
    if poppler_path:
        convert_kwargs["poppler_path"] = poppler_path

    try:
        images = convert_from_path(pdf_path, **convert_kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"Rasterization failed. Ensure 'poppler' is installed and on PATH. Detail: {exc}"
        )

    ocr_text_parts: List[str] = []
    ocr_pages = 0
    tess_config = f"--psm {psm}" if psm is not None else ""

    for image in images:
        ocr_pages += 1
        ocr_text_parts.append(pytesseract.image_to_string(image, lang=lang, config=tess_config))

    ocr_text = "\n".join(ocr_text_parts)
    if not ocr_text.strip():
        raise RuntimeError(
            "OCR returned empty text. Consider increasing dpi (e.g., 300), "
            "installing the correct language packs, or adjusting --psm."
        )

    return OCRResult(
        text=_clean_text(ocr_text),
        used_ocr=True,
        page_count=len(images),
        ocr_pages=ocr_pages,
        warnings=warnings,
    )


def ocr_tool(pdf_path: str, lang: str = "eng") -> dict:
    result = pdf_text_or_ocr(pdf_path, lang=lang)
    return {
        "text": result.text,
        "used_ocr": result.used_ocr,
        "page_count": result.page_count,
        "ocr_pages": result.ocr_pages,
        "warnings": result.warnings,
    }
