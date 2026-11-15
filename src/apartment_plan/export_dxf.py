"""Export reviewed geometry to DXF.

Calibrated (or provisional) projects are written in millimetres with
$INSUNITS = 4. Uncalibrated projects are written in raw pixel units, declared
unitless, with a warning note — pixels are never presented as millimetres.
"""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
from ezdxf import units

from .detect import polygon_area_px, polygon_centroid
from .models import Point2D, Project
from .transform import pixel_to_world, scale_label, world_polyline_points, world_walls

LAYERS = {
    "WALLS": 7,  # centre-lines (the editable geometry)
    "WALL_THICKNESS_ESTIMATE": 8,  # outlines from scan thickness — unverified
    "OPENINGS": 5,
    "ROOMS": 3,
    "TEXT_OCR": 2,
    "CALIBRATION": 6,
    "NOTES": 1,
}


def export_dxf(project: Project, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    calibrated = project.is_calibrated()
    doc = ezdxf.new("R2010")
    doc.units = units.MM if calibrated else 0
    doc.header["$INSUNITS"] = units.MM if calibrated else 0
    doc.header["$MEASUREMENT"] = 1  # metric
    msp = doc.modelspace()
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)

    scale = project.calibration.scale_mm_per_px or 1.0
    h = project.source.image_height
    walls = world_walls(project)

    xs = [p for a, b, _ in walls for p in (a.x, b.x)] or [0.0, 1000.0]
    ys = [p for a, b, _ in walls for p in (a.y, b.y)] or [0.0, 1000.0]
    extent = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    text_h = extent / 90.0

    for a, b, wall in walls:
        msp.add_line((a.x, a.y), (b.x, b.y), dxfattribs={"layer": "WALLS"})
        if wall.thickness_px:
            corners = _band_corners(a, b, wall.thickness_px * scale)
            if corners:
                msp.add_lwpolyline(
                    corners, close=True, dxfattribs={"layer": "WALL_THICKNESS_ESTIMATE"}
                )

    for opening in project.active_openings():
        pts = world_polyline_points(project, [opening.start, opening.end])
        msp.add_line(
            (pts[0].x, pts[0].y), (pts[1].x, pts[1].y), dxfattribs={"layer": "OPENINGS"}
        )
        mid = ((pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2)
        msp.add_text(
            opening.entity_type.value,
            dxfattribs={"layer": "OPENINGS", "height": text_h * 0.6, "insert": mid},
        )

    for room in project.active_rooms():
        pts = world_polyline_points(project, room.points)
        if len(pts) < 3:
            continue
        msp.add_lwpolyline(
            [(p.x, p.y) for p in pts], close=room.closed, dxfattribs={"layer": "ROOMS"}
        )
        centre = polygon_centroid(pts)
        cx, cy = centre.x, centre.y
        label = room.label or "room"
        if calibrated:
            label += f" ~{polygon_area_px(room) * scale * scale / 1e6:.2f} m2"
        msp.add_text(label, dxfattribs={"layer": "ROOMS", "height": text_h, "insert": (cx, cy)})

    for label in project.active_texts():
        pos = pixel_to_world(
            Point2D(label.position.x, label.position.y + label.height), project.calibration, h
        )
        msp.add_text(
            label.text,
            dxfattribs={"layer": "TEXT_OCR", "height": text_h * 0.7, "insert": (pos.x, pos.y)},
        )

    cal = project.calibration
    if calibrated and cal.pixel_start and cal.pixel_end:
        a = pixel_to_world(cal.pixel_start, cal, h)
        b = pixel_to_world(cal.pixel_end, cal, h)
        msp.add_line((a.x, a.y), (b.x, b.y), dxfattribs={"layer": "CALIBRATION"})
        msp.add_text(
            f"calibration length {cal.measured_mm:.0f} mm ({cal.method})",
            dxfattribs={"layer": "CALIBRATION", "height": text_h * 0.7, "insert": (a.x, a.y)},
        )

    lines = [f"SCALE STATE: {scale_label(project)}"]
    state = project.scale_state()
    if state == "UNCALIBRATED":
        lines.append("WARNING: UNCALIBRATED - coordinates are scan PIXELS, not millimetres.")
        lines.append("Enter a measured wall length in the review step before using dimensions.")
    elif state == "PROVISIONAL":
        lines.append("WARNING: PROVISIONAL scale taken from a printed dimension - not verified.")
        lines.append(_ascii(cal.note))
    else:
        lines.append(_ascii(cal.note))
        lines.append("Units: millimetres. Geometry is a reviewed trace, not a survey.")
    y = min(ys) - 3 * text_h
    for line in lines:
        msp.add_text(line, dxfattribs={"layer": "NOTES", "height": text_h, "insert": (min(xs), y)})
        y -= 1.6 * text_h

    doc.saveas(path)
    return path


def _band_corners(a: Point2D, b: Point2D, thickness: float) -> list[tuple[float, float]]:
    length = math.hypot(b.x - a.x, b.y - a.y)
    if length < 1e-9 or thickness <= 0:
        return []
    nx, ny = -(b.y - a.y) / length * thickness / 2, (b.x - a.x) / length * thickness / 2
    return [(a.x + nx, a.y + ny), (b.x + nx, b.y + ny), (b.x - nx, b.y - ny), (a.x - nx, a.y - ny)]


def _ascii(text: str) -> str:
    return text.replace("—", "-").encode("ascii", "replace").decode("ascii")
