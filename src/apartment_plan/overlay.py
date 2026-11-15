"""Draw detected draft overlaid on the source scan for review."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .models import Project


def render_overlay(image_bgr: np.ndarray, project: Project) -> np.ndarray:
    out = image_bgr.copy()
    for wall in project.active_walls():
        color = {
            "high": (40, 180, 40),
            "medium": (0, 165, 255),
            "low": (0, 0, 220),
            "user": (255, 128, 0),
        }.get(wall.confidence.value, (0, 165, 255))
        pt1 = (int(wall.start.x), int(wall.start.y))
        pt2 = (int(wall.end.x), int(wall.end.y))
        cv2.line(out, pt1, pt2, color, 2, cv2.LINE_AA)

    for room in project.active_rooms():
        pts = np.array([[int(p.x), int(p.y)] for p in room.points], dtype=np.int32)
        if len(pts) >= 3:
            cv2.polylines(out, [pts], True, (80, 200, 120), 2, cv2.LINE_AA)

    for label in project.active_texts()[:80]:
        org = (int(label.position.x), int(label.position.y))
        cv2.putText(
            out,
            label.text[:24],
            org,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (180, 60, 60),
            1,
            cv2.LINE_AA,
        )

    # OpenCV Hershey fonts are ASCII-only
    banner = "UNCALIBRATED - enter a measured wall length before trusting dimensions"
    if project.is_calibrated():
        banner = project.calibration.note.encode("ascii", "replace").decode("ascii")
        color = (40, 140, 40)
    else:
        color = (0, 0, 200)
    cv2.rectangle(out, (0, 0), (out.shape[1], 36), (255, 255, 255), -1)
    cv2.putText(out, banner[:120], (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return out


def save_overlay(image_bgr: np.ndarray, project: Project, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    overlay = render_overlay(image_bgr, project)
    cv2.imwrite(str(path), overlay)
    return path
