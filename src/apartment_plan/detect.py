"""Automatic draft: wall centre-lines, opening suggestions and room outlines.

Everything here is a *suggestion* in pixel coordinates. Nothing is trusted
until the user has reviewed it; uncertain items carry a low confidence.

Approach (works for plans whose walls are drawn as filled or hatched bands):

1. Isolate the main drawing: the largest cluster of filled ink. Key plans,
   stamps, title blocks and page edges are ignored.
2. Drop blobs that are too thick to be a wall (filled furniture).
3. Split the remaining bands into horizontal and vertical strips and replace
   each strip by its centre-line plus a measured pixel thickness.
4. Join strips at corners, propose openings in gaps between collinear walls,
   and trace enclosed areas as room outlines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import cv2
import numpy as np

from .models import Confidence, EntityType, Point2D, Polyline, Segment


@dataclass
class Detection:
    walls: list[Segment] = field(default_factory=list)
    openings: list[Segment] = field(default_factory=list)
    rooms: list[Polyline] = field(default_factory=list)
    plan_bbox: tuple[int, int, int, int] | None = None  # x0, y0, x1, y1
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Strip:
    horizontal: bool
    c: float  # centre-line coordinate (y for horizontal, x for vertical)
    a: float  # start along the axis
    b: float  # end along the axis
    t: float  # thickness in pixels
    joined: int = 0

    @property
    def length(self) -> float:
        return self.b - self.a


def detect_geometry(fill_mask: np.ndarray) -> Detection:
    """Return the automatic draft for a filled-ink mask (255 = ink)."""
    out = Detection()
    h, w = fill_mask.shape[:2]

    region, bbox, ignored = _main_plan_region(fill_mask)
    if bbox is None:
        out.warnings.append(
            "No wall-like filled geometry found. Draw the walls manually in the review step."
        )
        return out
    out.plan_bbox = bbox
    x0, y0, x1, y1 = bbox
    if ignored:
        out.warnings.append(
            f"Ignored {ignored} smaller drawing(s)/marks outside the main plan "
            "(e.g. key plan, stamp, title block)."
        )
    if x0 <= 2 or y0 <= 2 or x1 >= w - 3 or y1 >= h - 3:
        out.warnings.append(
            "The plan touches the edge of the scan and may be clipped. "
            "Rescan with a margin around the drawing if walls are missing."
        )

    long_side = max(x1 - x0, y1 - y0)
    t_max = int(np.clip(round(0.04 * long_side), 12, 120))
    strips = _extract_strips(region, t_max)
    _join_corners(strips)

    for s in strips:
        out.walls.append(_strip_to_segment(s, t_max))

    if len(out.walls) < 4:
        out.warnings.append(
            "Few wall-like bands detected; the automatic draft is unreliable. "
            "Check scan quality or draw walls manually."
        )

    out.openings = suggest_openings(out.walls, max_gap=0.22 * long_side, min_gap=0.4 * t_max)
    out.rooms = suggest_rooms(out.walls, out.openings, (h, w), bbox)
    if not out.rooms:
        out.warnings.append(
            "No enclosed room outlines found automatically. Close wall gaps in review, "
            "then use 'Recompute rooms'."
        )
    return out


# --------------------------------------------------------------------------- #
# Plan region
# --------------------------------------------------------------------------- #


def _main_plan_region(
    fill_mask: np.ndarray,
) -> tuple[np.ndarray, tuple[int, int, int, int] | None, int]:
    """Keep only the largest cluster of filled ink. Returns (mask, bbox, ignored_count)."""
    h, w = fill_mask.shape[:2]
    r = max(5, int(round(0.012 * max(h, w))))
    grown = cv2.dilate(fill_mask, cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 1, 2 * r + 1)))
    n, labels = cv2.connectedComponents(grown)
    if n <= 1:
        return np.zeros_like(fill_mask), None, 0
    ink = fill_mask > 0
    counts = np.bincount(labels[ink], minlength=n)
    counts[0] = 0
    best = int(np.argmax(counts))
    if counts[best] < 0.0005 * h * w:
        return np.zeros_like(fill_mask), None, 0
    region = np.where((labels == best) & ink, 255, 0).astype(np.uint8)
    ys, xs = np.nonzero(region)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    ignored = int(np.sum(counts > 0.02 * counts[best])) - 1
    return region, bbox, max(ignored, 0)


# --------------------------------------------------------------------------- #
# Walls
# --------------------------------------------------------------------------- #


def _run_lengths(mask: np.ndarray, horizontal: bool) -> np.ndarray:
    """For every ink pixel, the length of the straight ink run through it."""
    m = mask if horizontal else mask.T
    padded = np.zeros((m.shape[0], m.shape[1] + 1), bool)
    padded[:, :-1] = m
    flat = padded.ravel()
    starts = flat & ~np.concatenate(([False], flat[:-1]))
    run_id = np.cumsum(starts)
    lengths = np.bincount(run_id[flat], minlength=int(run_id[-1]) + 1)
    out = np.where(flat, lengths[run_id], 0).reshape(padded.shape)[:, :-1]
    return out if horizontal else out.T


def _extract_strips(region: np.ndarray, t_max: int) -> list[_Strip]:
    """
    Split filled ink into horizontal and vertical bands.

    Each ink pixel is given to the direction in which its straight run is
    longer, so a wall keeps its full length through corners and a thick wall is
    never mistaken for a short perpendicular one. Bands thicker than a wall
    could plausibly be (filled furniture) are dropped.
    """
    ink = region > 0
    run_h = _run_lengths(ink, True)
    run_v = _run_lengths(ink, False)
    l_min = int(round(1.25 * t_max))
    t_limit = 1.7 * t_max

    strips: list[_Strip] = []
    for horizontal in (True, False):
        if horizontal:
            band = ink & (run_h >= l_min) & (run_h >= run_v)
        else:
            band = ink & (run_v >= l_min) & (run_v > run_h)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(
            band.astype(np.uint8), connectivity=4
        )
        for i in range(1, n):
            x, y, bw, bh, _area = stats[i]
            comp = labels[y : y + bh, x : x + bw] == i
            if not horizontal:
                comp = comp.T  # rows = across the band, columns = along it
            comp = comp.copy()
            origin_c, origin_a = (y, x) if horizontal else (x, y)
            # Peel bands off one at a time, best-covered first, so a thin
            # partition fused with a piece of furniture is still found.
            for _ in range(6):
                cov = comp.mean(axis=1)
                peak = float(cov.max())
                if peak * comp.shape[1] < l_min:
                    break
                k = int(np.argmax(cov))
                lo = hi = k
                while lo > 0 and cov[lo - 1] >= 0.75 * peak:
                    lo -= 1
                while hi < len(cov) - 1 and cov[hi + 1] >= 0.75 * peak:
                    hi += 1
                thickness = float(hi - lo + 1)
                along = np.nonzero(comp[lo : hi + 1].mean(axis=0) >= 0.5)[0]
                comp[lo : hi + 1] = False
                if thickness < 3 or thickness > t_limit or along.size == 0:
                    continue
                for run in np.split(along, np.nonzero(np.diff(along) > 6)[0] + 1):
                    length = run[-1] - run[0] + 1
                    # Thick bands must be clearly elongated to count as a wall
                    if length < l_min or (thickness > t_max and length < 3 * thickness):
                        continue
                    strips.append(
                        _Strip(
                            horizontal,
                            origin_c + (lo + hi + 1) / 2.0,
                            origin_a + float(run[0]),
                            origin_a + run[-1] + 1.0,
                            thickness,
                        )
                    )
    return strips


def _join_corners(strips: list[_Strip], tol: float = 6.0) -> None:
    """Extend strip ends onto the centre-line of a perpendicular strip they touch."""
    updates: list[tuple[_Strip, str, float]] = []
    for s in strips:
        for end in ("a", "b"):
            pos = getattr(s, end)
            best: tuple[float, float] | None = None
            for o in strips:
                if o.horizontal == s.horizontal:
                    continue
                reach = o.t / 2.0 + s.t / 2.0 + tol
                if abs(pos - o.c) > reach:
                    continue
                if not (o.a - s.t - tol <= s.c <= o.b + s.t + tol):
                    continue
                d = abs(pos - o.c)
                if best is None or d < best[0]:
                    best = (d, o.c)
            if best is not None:
                updates.append((s, end, best[1]))
    for s, end, value in updates:
        setattr(s, end, value)
        s.joined += 1
    # A strip pulled onto a perpendicular centre-line may now end beyond the
    # perpendicular's own extent; stretch the perpendicular so the corner closes.
    for s in strips:
        for o in strips:
            if o.horizontal == s.horizontal:
                continue
            for pos in (s.a, s.b):
                if abs(pos - o.c) < 1e-6:
                    if o.a > s.c >= o.a - s.t - tol:
                        o.a = s.c
                    if o.b < s.c <= o.b + s.t + tol:
                        o.b = s.c


def _strip_to_segment(s: _Strip, t_max: int) -> Segment:
    if s.horizontal:
        start, end = Point2D(float(s.a), float(s.c)), Point2D(float(s.b), float(s.c))
    else:
        start, end = Point2D(float(s.c), float(s.a)), Point2D(float(s.c), float(s.b))
    if s.joined == 0:
        conf = Confidence.LOW  # free-standing band: may be furniture
    elif s.length >= 2.5 * t_max and s.joined >= 1:
        conf = Confidence.HIGH
    else:
        conf = Confidence.MEDIUM
    return Segment(
        id=str(uuid4()),
        entity_type=EntityType.WALL,
        start=start,
        end=end,
        confidence=conf,
        thickness_px=float(s.t),
        source="auto",
    )


# --------------------------------------------------------------------------- #
# Openings
# --------------------------------------------------------------------------- #


def _axis(seg: Segment) -> tuple[bool, float, float, float] | None:
    """(horizontal, centre, start, end) for an axis-aligned segment, else None."""
    dx, dy = seg.end.x - seg.start.x, seg.end.y - seg.start.y
    if abs(dy) <= 0.02 * abs(dx) + 1.0:
        return True, (seg.start.y + seg.end.y) / 2.0, min(seg.start.x, seg.end.x), max(seg.start.x, seg.end.x)
    if abs(dx) <= 0.02 * abs(dy) + 1.0:
        return False, (seg.start.x + seg.end.x) / 2.0, min(seg.start.y, seg.end.y), max(seg.start.y, seg.end.y)
    return None


def suggest_openings(walls: list[Segment], *, max_gap: float, min_gap: float) -> list[Segment]:
    """Propose an opening wherever two collinear walls are separated by a gap."""
    items = [(w, _axis(w)) for w in walls if not w.removed]
    items = [(w, ax) for w, ax in items if ax is not None]
    openings: list[Segment] = []
    for horizontal in (True, False):
        group = sorted((it for it in items if it[1][0] == horizontal), key=lambda it: it[1][2])
        perp = [it for it in items if it[1][0] != horizontal]
        for i, (wa, (_, ca, _a0, a1)) in enumerate(group):
            ta = wa.thickness_px or 6.0
            best = None
            for wb, (_, cb, b0, _b1) in group[i + 1 :]:
                tb = wb.thickness_px or 6.0
                if abs(ca - cb) > max(ta, tb) / 2.0 + 4.0:
                    continue
                best = (wb, cb, b0)
                break  # nearest collinear wall further along
            if best is None:
                continue
            _wb, cb, b0 = best
            gap = b0 - a1
            if not (min_gap <= gap <= max_gap):
                continue
            c = (ca + cb) / 2.0
            # A perpendicular wall ending in the gap means it is a junction, not an opening
            blocked = any(
                a1 + 2 < pc < b0 - 2 and p0 - 8 <= c <= p1 + 8 for _w, (_h, pc, p0, p1) in perp
            )
            if blocked:
                continue
            if horizontal:
                start, end = Point2D(a1, c), Point2D(b0, c)
            else:
                start, end = Point2D(c, a1), Point2D(c, b0)
            openings.append(
                Segment(
                    id=str(uuid4()),
                    entity_type=EntityType.OPENING,
                    start=start,
                    end=end,
                    confidence=Confidence.LOW,
                    label="opening? (door or window — check)",
                    source="auto",
                )
            )
    return openings


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #


def suggest_rooms(
    walls: list[Segment],
    openings: list[Segment],
    image_shape: tuple[int, int],
    bbox: tuple[int, int, int, int] | None = None,
) -> list[Polyline]:
    """Trace areas fully enclosed by walls and openings (inner wall faces)."""
    h, w = image_shape[:2]
    active = [s for s in walls if not s.removed]
    if not active:
        return []
    if bbox is None:
        xs = [p for s in active for p in (s.start.x, s.end.x)]
        ys = [p for s in active for p in (s.start.y, s.end.y)]
        bbox = (int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1)
    pad = 12
    x0, y0 = max(0, int(bbox[0]) - pad), max(0, int(bbox[1]) - pad)
    x1, y1 = min(w, int(bbox[2]) + pad), min(h, int(bbox[3]) + pad)
    if x1 - x0 < 10 or y1 - y0 < 10:
        return []

    barrier = np.zeros((y1 - y0, x1 - x0), np.uint8)

    def draw(seg: Segment, thickness: float) -> None:
        a = (int(round(seg.start.x - x0)), int(round(seg.start.y - y0)))
        b = (int(round(seg.end.x - x0)), int(round(seg.end.y - y0)))
        cv2.line(barrier, a, b, 255, max(3, int(round(thickness))))

    for seg in active:
        draw(seg, (seg.thickness_px or 4.0) + 2.0)
    for seg in openings:
        if not seg.removed:
            draw(seg, 3.0)

    free = cv2.bitwise_not(barrier)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    border = set(np.unique(labels[0, :])) | set(np.unique(labels[-1, :]))
    border |= set(np.unique(labels[:, 0])) | set(np.unique(labels[:, -1]))
    min_area = 0.004 * (x1 - x0) * (y1 - y0)

    rooms: list[Polyline] = []
    for i in range(1, n):
        if i in border or stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        comp = (labels == i).astype(np.uint8)
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        approx = cv2.approxPolyDP(contour, 3.0, True)
        if len(approx) < 3:
            continue
        rooms.append(
            Polyline(
                id=str(uuid4()),
                entity_type=EntityType.ROOM,
                points=[Point2D(float(p[0][0] + x0), float(p[0][1] + y0)) for p in approx],
                closed=True,
                confidence=Confidence.LOW,
                source="auto",
            )
        )
    rooms.sort(key=polygon_area_px, reverse=True)
    return rooms


def polygon_area_px(poly: Polyline) -> float:
    pts = poly.points
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        area += pts[i].x * pts[j].y - pts[j].x * pts[i].y
    return abs(area) * 0.5


def point_in_polygon(x: float, y: float, poly: Polyline) -> bool:
    pts = np.array([[p.x, p.y] for p in poly.points], dtype=np.float32)
    return cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0


def polygon_centroid(points: list[Point2D]) -> Point2D:
    """Area centroid of a simple polygon (vertex mean if degenerate)."""
    a = cx = cy = 0.0
    n = len(points)
    for i in range(n):
        p, q = points[i - 1], points[i]
        f = p.x * q.y - q.x * p.y
        a += f
        cx += (p.x + q.x) * f
        cy += (p.y + q.y) * f
    if abs(a) < 1e-9:
        return Point2D(sum(p.x for p in points) / n, sum(p.y for p in points) / n)
    return Point2D(cx / (3 * a), cy / (3 * a))
