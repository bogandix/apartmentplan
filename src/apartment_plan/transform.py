"""Pixel ↔ world (millimetre) coordinate transforms."""

from __future__ import annotations

from .models import Calibration, Point2D, Project, Segment


class UncalibratedError(ValueError):
    pass


def validate_measured_mm(value: float) -> float:
    if value is None or not isinstance(value, (int, float)):
        raise ValueError("Measured length must be a number (millimetres).")
    measured = float(value)
    if not (measured > 0) or measured != measured or measured == float("inf"):
        raise ValueError("Measured length must be a positive finite number (millimetres).")
    return measured


def apply_calibration(
    project: Project,
    *,
    measured_mm: float,
    pixel_start: Point2D,
    pixel_end: Point2D,
    segment_id: str | None = None,
) -> Project:
    """Set scale from one known wall length in millimetres."""
    measured_mm = validate_measured_mm(measured_mm)
    dx = pixel_end.x - pixel_start.x
    dy = pixel_end.y - pixel_start.y
    pixel_len = (dx * dx + dy * dy) ** 0.5
    if pixel_len < 1e-6:
        raise ValueError("Calibration segment endpoints must be distinct.")

    scale = measured_mm / pixel_len
    project.calibration.segment_id = segment_id
    project.calibration.pixel_start = pixel_start
    project.calibration.pixel_end = pixel_end
    project.calibration.measured_mm = measured_mm
    project.calibration.scale_mm_per_px = scale
    project.calibration.calibrated = True
    project.calibration.note = (
        f"Calibrated: {measured_mm:.1f} mm over {pixel_len:.1f} px "
        f"({scale:.4f} mm/px)"
    )
    return project


def pixel_to_world(point: Point2D, calibration: Calibration, image_height: int) -> Point2D:
    """Convert pixel coords to world millimetres. Uses identity scale if uncalibrated."""
    scale = calibration.scale_mm_per_px
    if scale is None:
        # Explicit non-metric working units — caller must label as uncalibrated
        scale = 1.0
    ox = calibration.origin_px.x
    oy = calibration.origin_px.y
    x = (point.x - ox) * scale
    if calibration.flip_y:
        y = (image_height - point.y - oy) * scale
    else:
        y = (point.y - oy) * scale
    return Point2D(x, y)


def world_walls(project: Project) -> list[tuple[Point2D, Point2D, Segment]]:
    """Walls in world mm (or uncalibrated px-as-mm)."""
    h = project.source.image_height
    out = []
    for wall in project.active_walls():
        a = pixel_to_world(wall.start, project.calibration, h)
        b = pixel_to_world(wall.end, project.calibration, h)
        out.append((a, b, wall))
    return out


def world_polyline_points(project: Project, points: list[Point2D]) -> list[Point2D]:
    h = project.source.image_height
    return [pixel_to_world(p, project.calibration, h) for p in points]


def scale_label(project: Project) -> str:
    if project.is_calibrated():
        return "calibrated_mm"
    return "UNCALIBRATED_pixel_units"
