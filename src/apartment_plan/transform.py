"""Pixel ↔ world (millimetre) coordinate transforms.

Pixel coordinates: origin top-left of the normalized scan, y down.
World coordinates: millimetres, y up (CAD convention), origin at
`calibration.origin_px` measured from the bottom-left of the image.

Without a calibration there is no millimetre scale. Exports then use raw
pixel units and must be labelled as such — see `scale_label`.
"""

from __future__ import annotations

import math

from .models import Calibration, Point2D, Project, Segment

CALIBRATION_METHODS = ("measured", "printed")


class UncalibratedError(ValueError):
    pass


def validate_measured_mm(value: float) -> float:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Measured length must be a number (millimetres).")
    measured = float(value)
    if not math.isfinite(measured) or measured <= 0:
        raise ValueError("Measured length must be a positive finite number (millimetres).")
    return measured


def apply_calibration(
    project: Project,
    *,
    measured_mm: float,
    pixel_start: Point2D,
    pixel_end: Point2D,
    segment_id: str | None = None,
    method: str = "measured",
) -> Project:
    """
    Set the scale from one known length between two pixel points.

    method="measured": the user measured the real wall (trusted).
    method="printed":  the length was read from a dimension printed on the
                       plan — usable, but exports stay marked PROVISIONAL.
    """
    measured_mm = validate_measured_mm(measured_mm)
    if method not in CALIBRATION_METHODS:
        raise ValueError(f"Calibration method must be one of {CALIBRATION_METHODS}.")
    coords = (pixel_start.x, pixel_start.y, pixel_end.x, pixel_end.y)
    if not all(isinstance(c, (int, float)) and math.isfinite(c) for c in coords):
        raise ValueError("Calibration endpoints must be finite pixel coordinates.")
    pixel_len = math.hypot(pixel_end.x - pixel_start.x, pixel_end.y - pixel_start.y)
    if pixel_len < 5.0:
        raise ValueError(
            "Calibration endpoints are too close together; pick the two ends of a long wall."
        )

    scale = measured_mm / pixel_len
    cal = project.calibration
    cal.segment_id = segment_id
    cal.pixel_start = pixel_start
    cal.pixel_end = pixel_end
    cal.measured_mm = measured_mm
    cal.scale_mm_per_px = scale
    cal.calibrated = True
    cal.method = method
    span = (
        f"({pixel_start.x:.0f},{pixel_start.y:.0f})-({pixel_end.x:.0f},{pixel_end.y:.0f}) px"
    )
    if method == "measured":
        cal.note = (
            f"Calibrated from a measured wall: {measured_mm / 1000.0:.3f} m over "
            f"{pixel_len:.1f} px {span} = {scale:.4f} mm/px"
        )
    else:
        cal.note = (
            f"PROVISIONAL scale from a dimension printed on the plan: "
            f"{measured_mm / 1000.0:.3f} m over {pixel_len:.1f} px {span} = {scale:.4f} mm/px. "
            "Not verified - measure a real wall to confirm."
        )
    return project


def clear_calibration(project: Project) -> Project:
    origin = project.calibration.origin_px
    project.calibration = Calibration(origin_px=origin)
    return project


def pixel_to_world(point: Point2D, calibration: Calibration, image_height: int) -> Point2D:
    """Pixel → world. Uses scale 1 (pixel units) when uncalibrated; callers must label that."""
    scale = calibration.scale_mm_per_px or 1.0
    x = (point.x - calibration.origin_px.x) * scale
    if calibration.flip_y:
        y = (image_height - point.y - calibration.origin_px.y) * scale
    else:
        y = (point.y - calibration.origin_px.y) * scale
    return Point2D(x, y)


def world_to_pixel(point: Point2D, calibration: Calibration, image_height: int) -> Point2D:
    """Inverse of `pixel_to_world`."""
    scale = calibration.scale_mm_per_px or 1.0
    x = point.x / scale + calibration.origin_px.x
    if calibration.flip_y:
        y = image_height - point.y / scale - calibration.origin_px.y
    else:
        y = point.y / scale + calibration.origin_px.y
    return Point2D(x, y)


def world_walls(project: Project) -> list[tuple[Point2D, Point2D, Segment]]:
    """Active walls in world units (mm if calibrated, otherwise pixel units)."""
    h = project.source.image_height
    return [
        (
            pixel_to_world(wall.start, project.calibration, h),
            pixel_to_world(wall.end, project.calibration, h),
            wall,
        )
        for wall in project.active_walls()
    ]


def world_polyline_points(project: Project, points: list[Point2D]) -> list[Point2D]:
    h = project.source.image_height
    return [pixel_to_world(p, project.calibration, h) for p in points]


def segment_length_mm(project: Project, seg: Segment) -> float | None:
    """Real length in mm, or None when the project has no scale."""
    if not project.is_calibrated():
        return None
    return seg.length_world() * float(project.calibration.scale_mm_per_px)


def scale_label(project: Project) -> str:
    state = project.scale_state()
    if state == "calibrated":
        return "calibrated_mm"
    if state == "PROVISIONAL":
        return "PROVISIONAL_mm_from_printed_dimension"
    return "UNCALIBRATED_pixel_units"


def export_suffix(project: Project) -> str:
    return project.scale_state()  # UNCALIBRATED | PROVISIONAL | calibrated
