"""Detect wall-like line segments and room outlines from a preprocessed plan."""

from __future__ import annotations

from uuid import uuid4

import cv2
import numpy as np

from .models import Confidence, EntityType, Point2D, Polyline, Segment


def detect_geometry(
    binary: np.ndarray,
    edges: np.ndarray,
) -> tuple[list[Segment], list[Polyline], list[str]]:
    """Return (walls, rooms, warnings) in pixel coordinates."""
    warnings: list[str] = []
    walls = detect_walls(edges, binary)
    rooms = detect_rooms(binary)

    if len(walls) < 4:
        warnings.append(
            "Few wall-like lines detected. Check scan quality or edit the draft manually."
        )
    if len(walls) > 200:
        warnings.append(
            f"Many segments kept ({len(walls)}). Prefer removing extras in review; "
            "detection favours longer axis-aligned strokes."
        )
    if not rooms:
        warnings.append("No closed room outlines detected automatically.")

    return walls, rooms, warnings


def detect_walls(edges: np.ndarray, binary: np.ndarray) -> list[Segment]:
    h, w = edges.shape[:2]
    min_len = max(80, min(h, w) // 18)

    # Detect ONLY on thick structural strokes — furniture hatch lives in thin edges
    wall_mask = _structural_wall_mask(binary)
    detect_img = wall_mask

    lines = cv2.HoughLinesP(
        detect_img,
        rho=1,
        theta=np.pi / 180,
        threshold=50,
        minLineLength=min_len,
        maxLineGap=28,
    )
    if lines is None:
        # Fallback: edges ∩ dilated thick mask
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        detect_img = cv2.bitwise_and(edges, cv2.dilate(wall_mask, k, iterations=2))
        lines = cv2.HoughLinesP(
            detect_img,
            rho=1,
            theta=np.pi / 180,
            threshold=60,
            minLineLength=min_len,
            maxLineGap=20,
        )
    if lines is None:
        return []

    raw: list[tuple[float, float, float, float]] = []
    for line in lines:
        x1, y1, x2, y2 = map(float, line[0])
        length = _segment_length(x1, y1, x2, y2)
        if length < min_len:
            continue
        # Drop strong diagonals (often stamps / noise on scans)
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
        axis_err = min(angle, abs(90 - angle), abs(180 - angle))
        if axis_err > 12:
            continue
        if not _supported_by_mask(wall_mask, x1, y1, x2, y2):
            continue
        x1, y1, x2, y2 = _snap_axis(x1, y1, x2, y2, axis_err)
        raw.append((x1, y1, x2, y2))

    merged = merge_collinear_segments(raw, dist_tol=14.0, angle_tol_deg=5.0)
    # Keep longest segments; drop tiny leftovers after merge
    merged = [s for s in merged if _segment_length(*s) >= min_len]
    merged.sort(key=lambda s: _segment_length(*s), reverse=True)
    # Collapse near-duplicates that survived merge
    merged = _dedupe_near(merged, dist_tol=12.0)
    merged = merged[:80]

    walls: list[Segment] = []
    for x1, y1, x2, y2 in merged:
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
        axis_err = min(angle, abs(90 - angle), abs(180 - angle))
        length = _segment_length(x1, y1, x2, y2)
        if axis_err <= 5 and length >= min_len * 1.5:
            conf = Confidence.HIGH
        elif axis_err <= 12:
            conf = Confidence.MEDIUM
        else:
            conf = Confidence.LOW
        walls.append(
            Segment(
                id=str(uuid4()),
                entity_type=EntityType.WALL,
                start=Point2D(x1, y1),
                end=Point2D(x2, y2),
                confidence=conf,
                source="auto",
            )
        )
    return walls


def _structural_wall_mask(binary: np.ndarray) -> np.ndarray:
    """Keep thicker strokes; suppress thin furniture hatch/grid."""
    # binary: walls/ink white. Two erodes remove hatch; dilate restores wall width.
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    thick = cv2.erode(binary, k, iterations=2)
    thick = cv2.dilate(thick, k, iterations=3)

    # Long horizontal / vertical runs typical of walls
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 35))
    horiz = cv2.morphologyEx(thick, cv2.MORPH_OPEN, h_kernel)
    vert = cv2.morphologyEx(thick, cv2.MORPH_OPEN, v_kernel)
    aligned = cv2.bitwise_or(horiz, vert)

    # Prefer intersection with thick ink, then close gaps at corners
    mask = cv2.bitwise_and(thick, cv2.bitwise_or(aligned, thick))
    close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close, iterations=1)


def _supported_by_mask(
    mask: np.ndarray, x1: float, y1: float, x2: float, y2: float, samples: int = 12
) -> bool:
    hits = 0
    for i in range(samples):
        t = i / max(samples - 1, 1)
        x = int(round(x1 + (x2 - x1) * t))
        y = int(round(y1 + (y2 - y1) * t))
        if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x] > 0:
            hits += 1
    return hits >= samples * 0.45


def _snap_axis(
    x1: float, y1: float, x2: float, y2: float, axis_err: float
) -> tuple[float, float, float, float]:
    if axis_err > 8:
        return x1, y1, x2, y2
    angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
    if angle < 45 or angle > 135:
        # horizontal
        y = (y1 + y2) / 2.0
        return x1, y, x2, y
    # vertical
    x = (x1 + x2) / 2.0
    return x, y1, x, y2


def detect_rooms(binary: np.ndarray) -> list[Polyline]:
    """Find large closed contours that may represent rooms/outer shell."""
    h, w = binary.shape[:2]
    wall_mask = _structural_wall_mask(binary)
    # Dilate walls so rooms become separated voids
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    thick = cv2.dilate(wall_mask, k, iterations=2)
    room_mask = cv2.bitwise_not(thick)
    margin = 6
    room_mask[:margin, :] = 0
    room_mask[-margin:, :] = 0
    room_mask[:, :margin] = 0
    room_mask[:, -margin:] = 0

    contours, _ = cv2.findContours(room_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_img = float(h * w)
    rooms: list[Polyline] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < area_img * 0.015 or area > area_img * 0.92:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.012 * peri, True)
        if len(approx) < 4:
            continue
        points = [Point2D(float(p[0][0]), float(p[0][1])) for p in approx]
        rooms.append(
            Polyline(
                id=str(uuid4()),
                entity_type=EntityType.ROOM,
                points=points,
                closed=True,
                confidence=Confidence.LOW,
                source="auto",
            )
        )

    rooms.sort(key=lambda r: _polyline_area(r), reverse=True)
    return rooms[:12]


def merge_collinear_segments(
    segments: list[tuple[float, float, float, float]],
    dist_tol: float = 8.0,
    angle_tol_deg: float = 8.0,
) -> list[tuple[float, float, float, float]]:
    """Greedy merge of nearly collinear overlapping/adjacent segments."""
    if not segments:
        return []

    segs = list(segments)
    changed = True
    while changed:
        changed = False
        out: list[tuple[float, float, float, float]] = []
        used = [False] * len(segs)
        for i, a in enumerate(segs):
            if used[i]:
                continue
            merged = a
            used[i] = True
            for j, b in enumerate(segs):
                if used[j]:
                    continue
                if _can_merge(merged, b, dist_tol, angle_tol_deg):
                    merged = _merge_pair(merged, b)
                    used[j] = True
                    changed = True
            out.append(merged)
        segs = out
    return segs


def _can_merge(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    dist_tol: float,
    angle_tol_deg: float,
) -> bool:
    a_ang = np.degrees(np.arctan2(a[3] - a[1], a[2] - a[0])) % 180
    b_ang = np.degrees(np.arctan2(b[3] - b[1], b[2] - b[0])) % 180
    dang = min(abs(a_ang - b_ang), 180 - abs(a_ang - b_ang))
    if dang > angle_tol_deg:
        return False

    pts_a = [(a[0], a[1]), (a[2], a[3])]
    pts_b = [(b[0], b[1]), (b[2], b[3])]
    min_end = min(np.hypot(pa[0] - pb[0], pa[1] - pb[1]) for pa in pts_a for pb in pts_b)
    mid_b = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    if _point_line_distance(mid_b, a) > dist_tol:
        return False
    if min_end > dist_tol * 3 and not _near_segment_span(mid_b, a, pad=dist_tol * 2):
        return False
    return True


def _merge_pair(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    pts = [(a[0], a[1]), (a[2], a[3]), (b[0], b[1]), (b[2], b[3])]
    dx = abs(a[2] - a[0]) + abs(b[2] - b[0])
    dy = abs(a[3] - a[1]) + abs(b[3] - b[1])
    if dx >= dy:
        pts.sort(key=lambda p: p[0])
    else:
        pts.sort(key=lambda p: p[1])
    return (pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])


def _point_line_distance(point: tuple[float, float], seg: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = seg
    px, py = point
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return float(np.hypot(px - x1, py - y1))
    return abs(dy * px - dx * py + x2 * y1 - y2 * x1) / (np.hypot(dx, dy) + 1e-9)


def _near_segment_span(
    point: tuple[float, float],
    seg: tuple[float, float, float, float],
    pad: float,
) -> bool:
    x1, y1, x2, y2 = seg
    px, py = point
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    if length2 < 1e-9:
        return True
    t = ((px - x1) * dx + (py - y1) * dy) / length2
    return -pad / (length2**0.5) <= t <= 1 + pad / (length2**0.5)


def _dedupe_near(
    segments: list[tuple[float, float, float, float]],
    dist_tol: float,
) -> list[tuple[float, float, float, float]]:
    kept: list[tuple[float, float, float, float]] = []
    for seg in segments:
        duplicate = False
        for other in kept:
            if _nearly_same(seg, other, dist_tol):
                duplicate = True
                break
        if not duplicate:
            kept.append(seg)
    return kept


def _nearly_same(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    tol: float,
) -> bool:
    # Same endpoints (either orientation) and similar length
    d1 = np.hypot(a[0] - b[0], a[1] - b[1]) + np.hypot(a[2] - b[2], a[3] - b[3])
    d2 = np.hypot(a[0] - b[2], a[1] - b[3]) + np.hypot(a[2] - b[0], a[3] - b[1])
    if min(d1, d2) <= tol * 2:
        return True
    # Parallel and overlapping with tiny lateral distance
    if _point_line_distance(((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), b) <= tol:
        a_ang = np.degrees(np.arctan2(a[3] - a[1], a[2] - a[0])) % 180
        b_ang = np.degrees(np.arctan2(b[3] - b[1], b[2] - b[0])) % 180
        dang = min(abs(a_ang - b_ang), 180 - abs(a_ang - b_ang))
        if dang <= 5 and abs(_segment_length(*a) - _segment_length(*b)) < tol * 3:
            # midpoints close along the line
            mid_a = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
            mid_b = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            if np.hypot(mid_a[0] - mid_b[0], mid_a[1] - mid_b[1]) < max(_segment_length(*a), _segment_length(*b)) * 0.35:
                return True
    return False


def _segment_length(x1: float, y1: float, x2: float, y2: float) -> float:
    return float(np.hypot(x2 - x1, y2 - y1))


def _polyline_area(poly: Polyline) -> float:
    pts = poly.points
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        area += pts[i].x * pts[j].y - pts[j].x * pts[i].y
    return abs(area) * 0.5
