"""Optional OCR for text/dimension suggestions (never trusted as ground truth)."""

from __future__ import annotations

import re
from uuid import uuid4

import cv2
import numpy as np

from .models import Confidence, Point2D, TextLabel

_DIMENSION = re.compile(r"^\d{2,4}(?:[.,]\d{1,2})?$")


def extract_text_labels(
    image_bgr: np.ndarray,
    bbox: tuple[int, int, int, int] | None = None,
) -> tuple[list[TextLabel], list[str]]:
    """
    Read text inside `bbox` (x0, y0, x1, y1) of the normalized image.

    Positions are returned in full-image pixel coordinates. Numbers that look
    like printed lengths are tagged kind="dimension"; they are hints only.
    """
    warnings: list[str] = []
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001
        warnings.append(
            "Tesseract OCR not available; no text suggestions. "
            "Install it (macOS: brew install tesseract) or enter dimensions manually."
        )
        return [], warnings

    h, w = image_bgr.shape[:2]
    if bbox is None:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        pad = int(0.03 * max(w, h))
        x0, y0 = max(0, bbox[0] - pad), max(0, bbox[1] - pad)
        x1, y1 = min(w, bbox[2] + pad), min(h, bbox[3] + pad)

    gray = cv2.cvtColor(image_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    scale = 2.0 if max(gray.shape) < 3000 else 1.0
    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    try:
        # psm 11 = sparse text: annotations scattered over a drawing
        data = pytesseract.image_to_data(
            gray, output_type=pytesseract.Output.DICT, config="--psm 11"
        )
    except Exception as exc:  # noqa: BLE001 — OCR is best-effort
        warnings.append(f"OCR failed ({exc}); continuing without text suggestions.")
        return [], warnings

    labels: list[TextLabel] = []
    for i in range(len(data.get("text", []))):
        text = (data["text"][i] or "").strip()
        if len(text) < 2 or not any(c.isalnum() for c in text):
            continue
        conf_raw = float(data["conf"][i])
        if conf_raw < 50:
            continue
        conf = (
            Confidence.HIGH if conf_raw >= 85 else Confidence.MEDIUM if conf_raw >= 65 else Confidence.LOW
        )
        labels.append(
            TextLabel(
                id=str(uuid4()),
                text=text,
                position=Point2D(x0 + data["left"][i] / scale, y0 + data["top"][i] / scale),
                confidence=conf,
                source="ocr",
                width=data["width"][i] / scale,
                height=data["height"][i] / scale,
                kind="dimension" if _DIMENSION.match(text) else "label",
            )
        )

    if not labels:
        warnings.append("OCR found no confident text. Enter dimensions manually during calibration.")
    return labels, warnings


def room_name_candidates(labels: list[TextLabel]) -> list[TextLabel]:
    """Upper-case words that plausibly name a room (suggestions only)."""
    out = []
    for label in labels:
        t = label.text.strip()
        if label.kind == "label" and len(t) >= 3 and t.isalpha() and t.isupper():
            out.append(label)
    return out
