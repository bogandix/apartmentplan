"""Export reviewed geometry to SVG."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .models import Project
from .transform import scale_label, world_polyline_points, world_walls


def export_svg(project: Project, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    walls = world_walls(project)
    room_polys = [
        world_polyline_points(project, room.points) for room in project.active_rooms()
    ]

    xs: list[float] = []
    ys: list[float] = []
    for a, b, _ in walls:
        xs.extend([a.x, b.x])
        ys.extend([a.y, b.y])
    for pts in room_polys:
        for p in pts:
            xs.append(p.x)
            ys.append(p.y)

    if not xs:
        xs, ys = [0.0, 1000.0], [0.0, 1000.0]

    pad = 200.0 if project.is_calibrated() else 40.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)

    # SVG Y grows downward; flip world Y for display
    def sx(x: float) -> float:
        return x - min_x

    def sy(y: float) -> float:
        return max_y - y

    stroke = 8.0 if project.is_calibrated() else 2.0
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width:.2f}" height="{height:.2f}" '
        f'viewBox="0 0 {width:.2f} {height:.2f}">',
        "<style>"
        ".wall{stroke:#222;stroke-width:" + f"{stroke:.1f}" + ";fill:none}"
        ".room{stroke:#2a7;stroke-width:" + f"{stroke * 0.6:.1f}" + ";fill:rgba(42,119,85,0.08)}"
        ".opening{stroke:#28c;stroke-width:" + f"{stroke * 0.8:.1f}" + ";fill:none;stroke-dasharray:12 8}"
        ".note{font:14px sans-serif;fill:#a30}"
        ".ok{font:14px sans-serif;fill:#262}"
        "</style>",
    ]

    for pts in room_polys:
        if len(pts) < 2:
            continue
        d = "M " + " L ".join(f"{sx(p.x):.2f},{sy(p.y):.2f}" for p in pts)
        if True:
            d += " Z"
        parts.append(f'<path class="room" d="{d}"/>')

    for a, b, _ in walls:
        parts.append(
            f'<line class="wall" x1="{sx(a.x):.2f}" y1="{sy(a.y):.2f}" '
            f'x2="{sx(b.x):.2f}" y2="{sy(b.y):.2f}"/>'
        )

    for opening in project.active_openings():
        pts = world_polyline_points(project, [opening.start, opening.end])
        parts.append(
            f'<line class="opening" x1="{sx(pts[0].x):.2f}" y1="{sy(pts[0].y):.2f}" '
            f'x2="{sx(pts[1].x):.2f}" y2="{sy(pts[1].y):.2f}"/>'
        )

    label = scale_label(project)
    css = "note" if not project.is_calibrated() else "ok"
    parts.append(
        f'<text class="{css}" x="12" y="24">{escape(label)} — {escape(project.calibration.note)}</text>'
    )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
