"""Image cleanup: orientation, deskew, and masks used by geometry detection.

The original input file is never modified; everything here works on an
in-memory copy and the result is written to the project folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Prepared:
    image: np.ndarray  # normalized BGR image (rotated + deskewed)
    gray: np.ndarray
    fill_mask: np.ndarray  # 255 where ink is thick/filled (walls, filled furniture)
    rotation_deg: int = 0  # clockwise quarter turns applied, in degrees
    skew_deg: float = 0.0  # fine rotation applied after the quarter turn
    warnings: list[str] = field(default_factory=list)


def preprocess(image_bgr: np.ndarray, rotate: str | int = "auto") -> Prepared:
    """Normalize a plan scan for geometry detection."""
    warnings: list[str] = []

    if rotate == "auto":
        rotation, note = detect_orientation(image_bgr)
        if note:
            warnings.append(note)
    else:
        rotation = int(rotate) % 360
        if rotation not in (0, 90, 180, 270):
            raise ValueError("rotate must be auto, 0, 90, 180 or 270")
    image = rotate_quarter(image_bgr, rotation)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    skew = estimate_skew_angle(gray)
    if abs(skew) > 8.0:
        warnings.append(
            f"Scan looks strongly skewed ({skew:.1f}°). It was straightened, but "
            "check the overlay or rescan with the sheet square to the scanner."
        )
    if abs(skew) > 0.15:
        image = rotate_image(image, skew)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        skew = 0.0

    return Prepared(
        image=image,
        gray=gray,
        fill_mask=filled_ink_mask(gray),
        rotation_deg=rotation,
        skew_deg=float(skew),
        warnings=warnings,
    )


def filled_ink_mask(gray: np.ndarray) -> np.ndarray:
    """
    Mask of filled / thick ink: solid or halftone-filled wall bands survive,
    thin linework (hatching, dimension lines, text strokes) does not.
    """
    scale = max(gray.shape[:2]) / 2300.0  # tuned on ~200 dpi A4 scans
    blur = cv2.GaussianBlur(gray, (0, 0), max(1.0, 1.5 * scale))
    paper = float(np.percentile(blur, 60))
    ink = float(np.percentile(blur, 1))
    # Halftone fills sit well below paper white once blurred
    threshold = paper - 0.22 * max(paper - ink, 1.0)
    mask = (blur < threshold).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    k = max(3, int(round(6 * scale)))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))


def detect_orientation(image_bgr: np.ndarray) -> tuple[int, str | None]:
    """
    Decide which quarter turn (clockwise degrees) makes printed text upright.

    Uses Tesseract when available: counts confidently-read words in each of the
    four orientations. Returns (0, note) when OCR is unavailable or undecided.
    """
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 — OCR is optional
        return 0, (
            "Tesseract not available, so sheet orientation was not checked. "
            "Use --rotate 90/180/270 if the plan is sideways."
        )

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    target = 1600.0
    f = min(1.0, target / max(gray.shape[:2]))
    small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else gray

    scores: dict[int, float] = {}
    for rot in (0, 90, 180, 270):
        try:
            data = pytesseract.image_to_data(
                rotate_quarter(small, rot),
                output_type=pytesseract.Output.DICT,
                config="--psm 11",
            )
        except Exception:  # noqa: BLE001
            return 0, "Orientation check failed; left the sheet as scanned."
        score = 0.0
        for text, conf in zip(data["text"], data["conf"]):
            text = (text or "").strip()
            if len(text) >= 3 and float(conf) >= 70 and any(c.isalnum() for c in text):
                score += len(text)
        scores[rot] = score

    best = max(scores, key=lambda r: scores[r])
    others = sorted((s for r, s in scores.items() if r != best), reverse=True)
    if scores[best] < 12 or scores[best] < 1.3 * (others[0] + 1):
        return 0, None  # not enough readable text to justify turning the sheet
    if best == 0:
        return 0, None
    return best, f"Sheet was scanned sideways; rotated {best}° clockwise so the text reads upright."


def rotate_quarter(image: np.ndarray, degrees_cw: int) -> np.ndarray:
    degrees_cw %= 360
    if degrees_cw == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if degrees_cw == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if degrees_cw == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image.copy()


def estimate_skew_angle(gray: np.ndarray) -> float:
    """
    Small residual skew in degrees, measured on long near-horizontal and
    near-vertical lines. Positive means the content is rotated clockwise on
    screen, and `rotate_image(image, angle)` straightens it.
    """
    f = min(1.0, 1800.0 / max(gray.shape[:2]))
    small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else gray
    edges = cv2.Canny(small, 50, 150)
    min_len = int(min(small.shape[:2]) * 0.18)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 1800, threshold=120, minLineLength=min_len, maxLineGap=6
    )
    if lines is None:
        return 0.0
    angles: list[float] = []
    weights: list[float] = []
    for x1, y1, x2, y2 in lines[:, 0, :].astype(float):
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        ang = (ang + 45.0) % 90.0 - 45.0  # deviation from the nearest axis
        if abs(ang) <= 15.0:
            angles.append(ang)
            weights.append(float(np.hypot(x2 - x1, y2 - y1)))
    if len(angles) < 3:
        return 0.0
    order = np.argsort(angles)
    cum = np.cumsum(np.array(weights)[order])
    median = float(np.array(angles)[order][int(np.searchsorted(cum, cum[-1] / 2.0))])
    return median


def rotate_image(image: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate about the centre (positive = counter-clockwise), growing the canvas."""
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    matrix[0, 2] += (new_w / 2) - center[0]
    matrix[1, 2] += (new_h / 2) - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255) if image.ndim == 3 else 255,
    )
