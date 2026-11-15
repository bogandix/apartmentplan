"""Optional OCR for dimension/text suggestions (never trusted as ground truth)."""

from __future__ import annotations

from uuid import uuid4

import cv2
import numpy as np

from .models import Confidence, Point2D, TextLabel


def extract_text_labels(image_bgr: np.ndarray) -> tuple[list[TextLabel], list[str]]:
    warnings: list[str] = []
    try:
        import pytesseract
    except ImportError:
        warnings.append("pytesseract not installed; skipping OCR.")
        return [], warnings

    try:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        # Upscale slightly for small printed dimensions
        scale = 1.5
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        # psm 6 = assume a single uniform block of text (plan annotations)
        data = pytesseract.image_to_data(
            gray,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
        )
    except Exception as exc:  # noqa: BLE001 — OCR is best-effort
        warnings.append(f"OCR failed ({exc}); continuing without text suggestions.")
        return [], warnings

    labels: list[TextLabel] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text or len(text) < 2:
            continue
        conf_raw = float(data["conf"][i])
        if conf_raw < 40:
            continue
        x = float(data["left"][i]) / scale
        y = float(data["top"][i]) / scale
        conf = Confidence.HIGH if conf_raw >= 70 else Confidence.MEDIUM if conf_raw >= 55 else Confidence.LOW
        labels.append(
            TextLabel(
                id=str(uuid4()),
                text=text,
                position=Point2D(x, y),
                confidence=conf,
                source="ocr",
            )
        )

    if not labels:
        warnings.append("OCR found no confident text. Enter dimensions manually during calibration.")
    return labels, warnings
