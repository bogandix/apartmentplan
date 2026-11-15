"""Load PDF pages and raster images into a normalized BGR image."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pymupdf

SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
SUPPORTED_PDF = {".pdf"}
SUPPORTED_EXTENSIONS = SUPPORTED_IMAGES | SUPPORTED_PDF


class UnsupportedInputError(ValueError):
    pass


def find_input_file(input_dir: Path) -> Path:
    """Pick the single newest supported plan file from input_dir."""
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    files = [
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not p.name.startswith(".")
    ]
    if not files:
        raise FileNotFoundError(
            f"No supported plan found in {input_dir}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def load_plan_image(path: Path, page_index: int = 0, dpi: int = 200) -> tuple[np.ndarray, list[str]]:
    """Return (BGR image, warnings) from a PDF page or raster file."""
    path = Path(path)
    suffix = path.suffix.lower()
    warnings: list[str] = []

    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedInputError(
            f"Unsupported file type '{suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if suffix in SUPPORTED_PDF:
        image = _render_pdf_page(path, page_index=page_index, dpi=dpi)
    else:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise UnsupportedInputError(f"Could not read image: {path}")

    h, w = image.shape[:2]
    if min(h, w) < 400:
        warnings.append("Source image is small; detection quality may be poor.")
    if max(h, w) > 8000:
        warnings.append("Source image is very large; processing may be slow.")

    blur = _blur_score(image)
    if blur < 80:
        warnings.append(
            f"Source looks blurry (sharpness score {blur:.0f}). "
            "Consider rescanning at higher quality."
        )

    return image, warnings


def _render_pdf_page(path: Path, page_index: int, dpi: int) -> np.ndarray:
    doc = pymupdf.open(path)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise UnsupportedInputError(
                f"PDF page index {page_index} out of range (0..{len(doc) - 1})"
            )
        page = doc[page_index]
        zoom = dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    finally:
        doc.close()


def _blur_score(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
