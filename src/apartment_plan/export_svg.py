"""Export reviewed geometry to SVG.

With a scale, the SVG is in real millimetres (width/height in mm, viewBox in
mm) so it opens at true size in Inkscape and similar tools. Without one it is
in pixel units and carries a visible UNCALIBRATED banner.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

from .detect import polygon_area_px, polygon_centroid
from .models import Project
from .transform import scale_label, world_polyline_points, world_walls


_OPENING_COLORS = {"door": "#8a4b12", "window": "#0a8fb8", "opening": "#cc33cc"}


def export_svg(project: Project, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    calibrated = project.is_calibrated()
    state = project.scale_state()
    scale = project.calibration.scale_mm_per_px or 1.0
    walls = world_walls(project)
    rooms = [(r, world_polyline_points(project, r.points)) for r in project.active_rooms()]

    xs = [p for a, b, _ in walls for p in (a.x, b.x)]
    ys = [p for a, b, _ in walls for p in (a.y, b.y)]
    for _r, pts in rooms:
        xs += [p.x for p in pts]
        ys += [p.y for p in pts]
    if not xs:
        xs, ys = [0.0, 1000.0], [0.0, 1000.0]

    extent = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    pad = extent * 0.06
    font = extent / 70.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad - 6 * font, max(ys) + pad
    width, height = max_x - min_x, max_y - min_y

    def sx(x: float) -> float:
        return x - min_x

    def sy(y: float) -> float:  # SVG y grows downward
        return max_y - y

    unit = "mm" if calibrated else "px"
    thin = extent / 600.0
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}{unit}" '
        f'height="{height:.2f}{unit}" viewBox="0 0 {width:.2f} {height:.2f}" '
        f'data-scale-state="{state}" data-units="{"mm" if calibrated else "pixels"}">',
        f"<title>Apartment plan - {escape(scale_label(project))}</title>",
    ]
    # Presentation attributes (not a <style> block) so CAD importers and simple
    # renderers that ignore CSS still draw the plan correctly.
    text_attr = f'font-family="sans-serif" font-size="{font:.2f}"'

    parts.append('<g id="rooms">')
    for room, pts in rooms:
        if len(pts) < 3:
            continue
        d = "M " + " L ".join(f"{sx(p.x):.2f},{sy(p.y):.2f}" for p in pts) + " Z"
        parts.append(f'<path class="room" d="{d}" fill="#2aaa77" fill-opacity="0.10" '
            f'stroke="#22aa77" stroke-width="{thin:.2f}"/>')
        centre = polygon_centroid(pts)
        cx, cy = centre.x, centre.y
        label = room.label or "room"
        if calibrated:
            label += f" ≈{polygon_area_px(room) * scale * scale / 1e6:.2f} m²"
        parts.append(
            f'<text class="roomlabel" {text_attr} fill="#117755" text-anchor="middle" '
            f'x="{sx(cx):.2f}" y="{sy(cy):.2f}">{escape(label)}</text>'
        )
    parts.append("</g>")

    parts.append('<g id="walls">')
    for a, b, wall in walls:
        sw = max((wall.thickness_px or 0.0) * scale, thin * 3)
        length_attr = ""
        if calibrated:
            length_attr = f' data-length-mm="{((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5:.1f}"'
        coords = (
            f'x1="{sx(a.x):.2f}" y1="{sy(a.y):.2f}" x2="{sx(b.x):.2f}" y2="{sy(b.y):.2f}"'
        )
        parts.append(f'<line class="wall" id="wall-{escape(wall.id)}" stroke="#2b2b2b" stroke-linecap="square" stroke-width="{sw:.2f}" {coords}{length_attr}/>')
        parts.append(f'<line class="axis" stroke="#ffffff" stroke-width="{thin:.2f}" '
            f'stroke-dasharray="{thin * 6:.1f} {thin * 4:.1f}" {coords}/>')
    parts.append("</g>")

    parts.append('<g id="openings">')
    for opening in project.active_openings():
        pts = world_polyline_points(project, [opening.start, opening.end])
        parts.append(
            f'<line class="opening" data-type="{opening.entity_type.value}" '
            f'stroke="{_OPENING_COLORS.get(opening.entity_type.value, "#cc33cc")}" stroke-width="{thin * 3:.2f}" '
            f'x1="{sx(pts[0].x):.2f}" y1="{sy(pts[0].y):.2f}" '
            f'x2="{sx(pts[1].x):.2f}" y2="{sy(pts[1].y):.2f}"/>'
        )
    parts.append("</g>")

    if state == "UNCALIBRATED":
        css, colour, lines = "note", "#b30000", [
            "UNCALIBRATED — pixel units, NOT real scale.",
            "Enter a measured wall length in the review step before using dimensions.",
        ]
    elif state == "PROVISIONAL":
        css, colour, lines = "prov", "#b35c00", ["PROVISIONAL scale (printed dimension, not verified).", project.calibration.note]
    else:
        css, colour, lines = "ok", "#226622", [project.calibration.note, "Units: millimetres."]
    lines = [part for line in lines for part in textwrap.wrap(line, 95)]
    min_needed = (len(lines) + 1) * 1.4 * font
    if min_needed > pad + 6 * font:  # keep the note inside the page
        lines = lines[: max(1, int((pad + 6 * font) / (1.4 * font)) - 1)]
    for i, line in enumerate(lines):
        parts.append(
            f'<text class="{css}" {text_attr} font-weight="bold" fill="{colour}" x="{pad:.2f}" y="{height - (len(lines) - i) * 1.4 * font:.2f}">'
            f"{escape(line)}</text>"
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
