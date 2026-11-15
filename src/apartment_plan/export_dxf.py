"""Export reviewed geometry to DXF (millimetres when calibrated)."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import units

from .models import Project
from .transform import scale_label, world_polyline_points, world_walls


def export_dxf(project: Project, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2010")
    doc.units = units.MM
    doc.header["$INSUNITS"] = units.MM
    msp = doc.modelspace()

    _ensure_layer(doc, "WALLS", color=7)
    _ensure_layer(doc, "ROOMS", color=3)
    _ensure_layer(doc, "OPENINGS", color=5)
    _ensure_layer(doc, "TEXT", color=2)
    _ensure_layer(doc, "NOTES", color=1)

    for a, b, wall in world_walls(project):
        msp.add_line((a.x, a.y), (b.x, b.y), dxfattribs={"layer": "WALLS"})

    for opening in project.active_openings():
        pts = world_polyline_points(project, [opening.start, opening.end])
        msp.add_line(
            (pts[0].x, pts[0].y),
            (pts[1].x, pts[1].y),
            dxfattribs={"layer": "OPENINGS"},
        )

    for room in project.active_rooms():
        pts = world_polyline_points(project, room.points)
        if len(pts) < 2:
            continue
        coords = [(p.x, p.y) for p in pts]
        if room.closed and coords[0] != coords[-1]:
            coords.append(coords[0])
        msp.add_lwpolyline(coords, close=room.closed, dxfattribs={"layer": "ROOMS"})

    for label in project.active_texts():
        pos = world_polyline_points(project, [label.position])[0]
        msp.add_text(
            label.text,
            dxfattribs={
                "layer": "TEXT",
                "height": 100.0 if project.is_calibrated() else 12.0,
                "insert": (pos.x, pos.y),
            },
        )

    note = scale_label(project)
    if not project.is_calibrated():
        note = (
            "WARNING: UNCALIBRATED — coordinates are NOT real millimetres. "
            + project.calibration.note
        )
    else:
        note = project.calibration.note
    msp.add_text(
        note,
        dxfattribs={"layer": "NOTES", "height": 150.0 if project.is_calibrated() else 18.0, "insert": (0, -200)},
    )

    doc.saveas(path)
    return path


def _ensure_layer(doc, name: str, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)
