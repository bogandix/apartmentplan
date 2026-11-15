"""Export reviewed geometry to SVG.

With a scale, the SVG is in real millimetres (width/height in mm, viewBox in
mm) so it opens at true size in Inkscape and similar tools. Without one it is
in pixel units and carries a visible UNCALIBRATED banner.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .detect import polygon_area_px, polygon_centroid
from .models import Project
from .transform import scale_label, world_polyline_points, world_walls


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
    min_y, max_y = min(ys) - pad - 4 * font, max(ys) + pad
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
        "<style>"
        ".wall{stroke:#2b2b2b;stroke-linecap:square;fill:none}"
        f".axis{{stroke:#fff;stroke-width:{thin:.2f};fill:none;stroke-dasharray:{thin * 6:.1f} {thin * 4:.1f}}}"
        f".room{{stroke:#2a7;stroke-width:{thin:.2f};fill:rgba(42,170,119,0.10)}}"
        f".opening{{stroke:#c3c;stroke-width:{thin * 2.5:.2f};fill:none}}"
        f"text{{font-family:sans-serif;font-size:{font:.2f}px}}"
        ".roomlabel{fill:#175;text-anchor:middle}"
        ".note{fill:#b30000;font-weight:bold}"
        ".prov{fill:#b35c00;font-weight:bold}"
        ".ok{fill:#226622}"
        "</style>",
    ]

    parts.append('<g id="rooms">')
    for room, pts in rooms:
        if len(pts) < 3:
            continue
        d = "M " + " L ".join(f"{sx(p.x):.2f},{sy(p.y):.2f}" for p in pts) + " Z"
        parts.append(f'<path class="room" d="{d}"/>')
        centre = polygon_centroid(pts)
        cx, cy = centre.x, centre.y
        label = room.label or "room"
        if calibrated:
            label += f" ≈{polygon_area_px(room) * scale * scale / 1e6:.2f} m²"
        parts.append(
            f'<text class="roomlabel" x="{sx(cx):.2f}" y="{sy(cy):.2f}">{escape(label)}</text>'
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
        parts.append(f'<line class="wall" id="wall-{escape(wall.id)}" stroke-width="{sw:.2f}" {coords}{length_attr}/>')
        parts.append(f'<line class="axis" {coords}/>')
    parts.append("</g>")

    parts.append('<g id="openings">')
    for opening in project.active_openings():
        pts = world_polyline_points(project, [opening.start, opening.end])
        parts.append(
            f'<line class="opening" data-type="{opening.entity_type.value}" '
            f'x1="{sx(pts[0].x):.2f}" y1="{sy(pts[0].y):.2f}" '
            f'x2="{sx(pts[1].x):.2f}" y2="{sy(pts[1].y):.2f}"/>'
        )
    parts.append("</g>")

    if state == "UNCALIBRATED":
        css, lines = "note", [
            "UNCALIBRATED — pixel units, NOT real scale.",
            "Enter a measured wall length in the review step before using dimensions.",
        ]
    elif state == "PROVISIONAL":
        css, lines = "prov", ["PROVISIONAL scale (printed dimension, not verified).", project.calibration.note]
    else:
        css, lines = "ok", [project.calibration.note, "Units: millimetres."]
    for i, line in enumerate(lines):
        parts.append(
            f'<text class="{css}" x="{pad:.2f}" y="{height - (len(lines) - i) * 1.4 * font:.2f}">'
            f"{escape(line)}</text>"
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
