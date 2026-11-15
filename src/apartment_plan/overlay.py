"""Draw the detected draft over the source scan for review."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .models import Project

_WALL_COLORS = {  # BGR
    "high": (40, 160, 40),
    "medium": (0, 150, 255),
    "low": (40, 40, 220),
    "user": (200, 90, 20),
}


def render_overlay(image_bgr: np.ndarray, project: Project) -> np.ndarray:
    out = image_bgr.copy()

    fill = out.copy()
    for room in project.active_rooms():
        pts = np.array([[int(p.x), int(p.y)] for p in room.points], dtype=np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(fill, [pts], (200, 235, 200))
    out = cv2.addWeighted(fill, 0.45, out, 0.55, 0)
    for room in project.active_rooms():
        pts = np.array([[int(p.x), int(p.y)] for p in room.points], dtype=np.int32)
        if len(pts) >= 3:
            cv2.polylines(out, [pts], True, (90, 170, 90), 1, cv2.LINE_AA)
            if room.label:
                m = pts.mean(axis=0).astype(int)
                cv2.putText(out, _ascii(room.label)[:24], (int(m[0]) - 40, int(m[1]) + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 110, 40), 1, cv2.LINE_AA)

    for wall in project.active_walls():
        color = _WALL_COLORS.get(wall.confidence.value, (0, 150, 255))
        pt1 = (int(round(wall.start.x)), int(round(wall.start.y)))
        pt2 = (int(round(wall.end.x)), int(round(wall.end.y)))
        cv2.line(out, pt1, pt2, color, 3, cv2.LINE_AA)
        cv2.circle(out, pt1, 4, color, -1, cv2.LINE_AA)
        cv2.circle(out, pt2, 4, color, -1, cv2.LINE_AA)

    for opening in project.active_openings():
        pt1 = (int(round(opening.start.x)), int(round(opening.start.y)))
        pt2 = (int(round(opening.end.x)), int(round(opening.end.y)))
        cv2.line(out, pt1, pt2, (220, 60, 200), 2, cv2.LINE_AA)

    for label in project.active_texts():
        if label.kind != "dimension" or not label.width:
            continue
        p1 = (int(label.position.x) - 2, int(label.position.y) - 2)
        p2 = (int(label.position.x + label.width) + 2, int(label.position.y + label.height) + 2)
        cv2.rectangle(out, p1, p2, (200, 120, 0), 1)

    state = project.scale_state()
    if state == "UNCALIBRATED":
        banner = "UNCALIBRATED DRAFT - not real scale. Review the trace and enter a measured wall length."
        color = (0, 0, 200)
    elif state == "PROVISIONAL":
        banner = "PROVISIONAL SCALE (printed dimension, not verified) - " + _ascii(project.calibration.note)
        color = (0, 110, 220)
    else:
        banner = _ascii(project.calibration.note)
        color = (40, 140, 40)
    bar = np.full((40, out.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, banner[:170], (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return np.vstack([bar, out])


def _ascii(text: str) -> str:
    # OpenCV Hershey fonts are ASCII-only
    return text.replace("—", "-").encode("ascii", "replace").decode("ascii")


def save_overlay(image_bgr: np.ndarray, project: Project, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), render_overlay(image_bgr, project))
    return path
