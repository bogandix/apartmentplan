"""Scale calibration and pixel <-> world coordinate conversion."""

from __future__ import annotations

import math

import pytest

from apartment_plan.models import (
    Confidence,
    EntityType,
    Point2D,
    Project,
    Segment,
    SourceInfo,
    project_from_dict,
    project_to_dict,
)
from apartment_plan.transform import (
    apply_calibration,
    clear_calibration,
    pixel_to_world,
    scale_label,
    segment_length_mm,
    validate_measured_mm,
    world_to_pixel,
)


def _project(width=1000, height=800) -> Project:
    return Project.new(SourceInfo(original_path="x.png", image_width=width, image_height=height))


@pytest.mark.parametrize("bad", [0, -10, float("nan"), float("inf"), -float("inf"), None, "3500", True])
def test_measured_length_must_be_positive_finite_number(bad):
    with pytest.raises(ValueError):
        validate_measured_mm(bad)


def test_measured_length_accepts_int_and_float():
    assert validate_measured_mm(3500) == 3500.0
    assert validate_measured_mm(0.5) == 0.5


def test_new_project_is_uncalibrated_and_says_so():
    project = _project()
    assert not project.is_calibrated()
    assert project.scale_state() == "UNCALIBRATED"
    assert scale_label(project) == "UNCALIBRATED_pixel_units"
    wall = Segment("w", EntityType.WALL, Point2D(0, 0), Point2D(100, 0))
    assert segment_length_mm(project, wall) is None  # never pixels-as-millimetres


def test_calibration_records_segment_scale_and_method():
    project = _project()
    apply_calibration(
        project,
        measured_mm=4000,
        pixel_start=Point2D(100, 100),
        pixel_end=Point2D(500, 100),  # 400 px -> 10 mm/px
        segment_id="wall-1",
    )
    cal = project.calibration
    assert project.scale_state() == "calibrated"
    assert project.is_verified_scale()
    assert cal.scale_mm_per_px == pytest.approx(10.0)
    assert (cal.pixel_start.x, cal.pixel_end.x, cal.segment_id) == (100, 500, "wall-1")
    assert cal.measured_mm == 4000
    assert "4.000 m" in cal.note and "(100,100)-(500,100)" in cal.note


def test_diagonal_calibration_segment():
    project = _project()
    apply_calibration(
        project, measured_mm=5000, pixel_start=Point2D(0, 0), pixel_end=Point2D(300, 400)
    )
    assert project.calibration.scale_mm_per_px == pytest.approx(10.0)


def test_printed_dimension_gives_provisional_not_verified_scale():
    project = _project()
    apply_calibration(
        project,
        measured_mm=4000,
        pixel_start=Point2D(0, 0),
        pixel_end=Point2D(400, 0),
        method="printed",
    )
    assert project.is_calibrated()
    assert not project.is_verified_scale()
    assert project.scale_state() == "PROVISIONAL"
    assert "PROVISIONAL" in project.calibration.note
    assert scale_label(project).startswith("PROVISIONAL")


def test_calibration_rejects_bad_segments_and_methods():
    project = _project()
    with pytest.raises(ValueError, match="too close"):
        apply_calibration(
            project, measured_mm=1000, pixel_start=Point2D(5, 5), pixel_end=Point2D(6, 5)
        )
    with pytest.raises(ValueError, match="finite"):
        apply_calibration(
            project, measured_mm=1000, pixel_start=Point2D(math.nan, 0), pixel_end=Point2D(50, 0)
        )
    with pytest.raises(ValueError, match="method"):
        apply_calibration(
            project, measured_mm=1000, pixel_start=Point2D(0, 0), pixel_end=Point2D(50, 0), method="guess"
        )
    assert not project.is_calibrated()


def test_clear_calibration_returns_to_uncalibrated():
    project = _project()
    project.calibration.origin_px = Point2D(40, 60)
    apply_calibration(project, measured_mm=1000, pixel_start=Point2D(0, 0), pixel_end=Point2D(100, 0))
    clear_calibration(project)
    assert project.scale_state() == "UNCALIBRATED"
    assert project.calibration.origin_px.x == 40  # origin is kept


def test_pixel_to_world_flips_y_and_applies_origin_and_scale():
    project = _project(height=800)
    project.calibration.origin_px = Point2D(100, 50)
    apply_calibration(project, measured_mm=4000, pixel_start=Point2D(100, 100), pixel_end=Point2D(500, 100))
    world = pixel_to_world(Point2D(300, 700), project.calibration, 800)
    assert world.x == pytest.approx((300 - 100) * 10.0)
    assert world.y == pytest.approx((800 - 700 - 50) * 10.0)
    # image y grows down, world y grows up
    higher = pixel_to_world(Point2D(300, 600), project.calibration, 800)
    assert higher.y > world.y


@pytest.mark.parametrize("calibrated", [False, True])
def test_pixel_world_round_trip(calibrated: bool):
    project = _project(height=777)
    project.calibration.origin_px = Point2D(12.5, 30.25)
    if calibrated:
        apply_calibration(project, measured_mm=2575, pixel_start=Point2D(10, 10), pixel_end=Point2D(310, 10))
    for x, y in [(0, 0), (123.4, 567.8), (999, 776)]:
        back = world_to_pixel(pixel_to_world(Point2D(x, y), project.calibration, 777), project.calibration, 777)
        assert back.x == pytest.approx(x)
        assert back.y == pytest.approx(y)


def test_distances_scale_uniformly():
    project = _project()
    apply_calibration(project, measured_mm=3000, pixel_start=Point2D(0, 0), pixel_end=Point2D(0, 200))
    wall = Segment("w", EntityType.WALL, Point2D(50, 50), Point2D(350, 450), Confidence.USER)
    assert segment_length_mm(project, wall) == pytest.approx(500 * 15.0)


def test_project_file_round_trip_keeps_calibration_and_edits():
    project = _project()
    project.walls.append(Segment("w", EntityType.WALL, Point2D(1, 2), Point2D(3, 4), thickness_px=7.0))
    apply_calibration(project, measured_mm=1234, pixel_start=Point2D(0, 0), pixel_end=Point2D(100, 0), method="printed")
    project.log_edit("add", id="w")
    loaded = project_from_dict(project_to_dict(project))
    assert loaded.schema_version == project.schema_version
    assert loaded.scale_state() == "PROVISIONAL"
    assert loaded.calibration.scale_mm_per_px == pytest.approx(12.34)
    assert loaded.walls[0].thickness_px == 7.0
    assert loaded.edits[0]["action"] == "add"


def test_version_1_project_files_still_load():
    old = {
        "id": "abc",
        "schema_version": 1,
        "source": {"original_path": "x.pdf", "image_width": 10, "image_height": 10},
        "calibration": {"calibrated": True, "scale_mm_per_px": 5.0, "measured_mm": 500.0},
        "walls": [{"id": "w", "entity_type": "wall", "start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}}],
    }
    project = project_from_dict(old)
    assert project.schema_version == 2
    assert project.scale_state() == "calibrated"  # v1 could only be calibrated by measurement
    assert project.edits == []
