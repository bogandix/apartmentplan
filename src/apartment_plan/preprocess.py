"""Image cleanup: deskew, contrast, binary mask for line detection."""

from __future__ import annotations

import cv2
import numpy as np


def preprocess(image_bgr: np.ndarray) -> dict[str, np.ndarray]:
    """
    Normalize a plan scan for geometry detection.

    Returns:
      original, gray, deskewed, binary, edges
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, h=8, templateWindowSize=7, searchWindowSize=21)

    angle = estimate_skew_angle(gray)
    deskewed = rotate_image(image_bgr, angle) if abs(angle) > 0.3 else image_bgr.copy()
    deskewed_gray = cv2.cvtColor(deskewed, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(deskewed_gray)

    binary = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        8,
    )

    # Close small gaps in wall strokes
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    edges = cv2.Canny(enhanced, 50, 150, apertureSize=3)
    edges = cv2.bitwise_or(edges, binary)

    return {
        "original": image_bgr,
        "gray": gray,
        "deskewed": deskewed,
        "binary": binary,
        "edges": edges,
        "skew_angle_deg": angle,  # type: ignore[dict-item]
    }


def estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate dominant skew using Hough lines; returns degrees (CCW)."""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(120, gray.shape[1] // 8))
    if lines is None:
        return 0.0

    angles: list[float] = []
    for rho_theta in lines[:80]:
        rho, theta = rho_theta[0]
        angle = (theta * 180.0 / np.pi) - 90.0
        # Prefer near-horizontal / near-vertical
        if abs(angle) < 45:
            if abs(angle) < 20:
                angles.append(angle)
        else:
            # near vertical → ignore for deskew of page
            pass

    if not angles:
        return 0.0
    return float(np.median(angles))


def rotate_image(image: np.ndarray, angle_deg: float) -> np.ndarray:
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
        borderMode=cv2.BORDER_REPLICATE,
    )
