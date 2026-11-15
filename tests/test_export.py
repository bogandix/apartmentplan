"""DXF / SVG exports: real dimensions when calibrated, clear labels when not."""

from __future__ import annotations

import math
import re
from pathlib import Path

import ezdxf
import pytest

from apartment_plan.export_dxf import export_dxf
from apartment_plan.export_svg import export_svg
from apartment_plan.models import Confidence, EntityType, Point2D, Polyline, Project, Segment, SourceInfo
from apartment_plan.pipeline import export_project, process_input
from apartment_plan.project_io import load_project
from apartment_plan.transform import apply_calibration


def _room_project() -> Project:
    """A 400 x 300 px rectangle of walls; 400 px will be calibrated to 5 m."""
    project = Project.new(SourceInfo(original_path="x.png", image_width=600, image_height=500))
    project.calibration.origin_px = Point2D(100, 100)  # bottom-left corner (x=100, y=400)
    corners = [(100, 100), (500, 100), (500, 400), (100, 400)]
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        project.walls.append(
            Segment(f"w{i}", EntityType.WALL, Point2D(*a), Point2D(*b), Confidence.USER, thickness_px=16)
        )
    project.openings.append(Segment("d1", EntityType.DOOR, Point2D(200, 400), Point2D(280, 400)))
    project.rooms.append(
        Polyline("r1", EntityType.ROOM, [Point2D(*c) for c in corners], label="ROOM")
    )
    return project


def _dxf_wall_lines(path: Path):
    doc = ezdxf.readfile(path)
    lines = [e for e in doc.modelspace() if e.dxftype() == "LINE" and e.dxf.layer == "WALLS"]
    return doc, lines


def _texts(doc) -> str:
    return " | ".join(e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT")


def test_calibrated_dxf_is_in_millimetres_with_true_wall_lengths(tmp_path: Path):
    project = _room_project()
    apply_calibration(project, measured_mm=5000, pixel_start=Point2D(100, 100), pixel_end=Point2D(500, 100))
    doc, lines = _dxf_wall_lines(export_dxf(project, tmp_path / "plan.dxf"))

    assert doc.header["$INSUNITS"] == 4  # millimetres
    assert doc.header["$MEASUREMENT"] == 1  # metric
    lengths = sorted(round(e.dxf.start.distance(e.dxf.end), 3) for e in lines)
    assert lengths == [3750.0, 3750.0, 5000.0, 5000.0]
    xs = [c for e in lines for c in (e.dxf.start.x, e.dxf.end.x)]
    ys = [c for e in lines for c in (e.dxf.start.y, e.dxf.end.y)]
    assert (min(xs), max(xs)) == pytest.approx((0.0, 5000.0))
    assert (min(ys), max(ys)) == pytest.approx((0.0, 3750.0))
    # y is flipped: the image-top wall (y=100 px) is the CAD-top wall
    top = [e for e in lines if e.dxf.start.y == pytest.approx(3750) and e.dxf.end.y == pytest.approx(3750)]
    assert len(top) == 1

    layers = {layer.dxf.name for layer in doc.layers}
    assert {"WALLS", "OPENINGS", "ROOMS", "CALIBRATION", "NOTES"} <= layers
    door = [e for e in doc.modelspace() if e.dxftype() == "LINE" and e.dxf.layer == "OPENINGS"]
    assert door[0].dxf.start.distance(door[0].dxf.end) == pytest.approx(1000.0)
    text = _texts(doc)
    assert "calibrated_mm" in text and "18.75 m2" in text  # 5.0 m x 3.75 m
    assert "UNCALIBRATED" not in text and "PROVISIONAL" not in text


def test_uncalibrated_dxf_is_unitless_and_warns(tmp_path: Path):
    doc, lines = _dxf_wall_lines(export_dxf(_room_project(), tmp_path / "plan.dxf"))
    assert doc.header["$INSUNITS"] == 0  # not millimetres
    assert sorted(round(e.dxf.start.distance(e.dxf.end)) for e in lines) == [300, 300, 400, 400]
    text = _texts(doc)
    assert "UNCALIBRATED" in text and "PIXELS" in text
    assert " m2" not in text  # no areas without a scale


def test_provisional_dxf_is_marked(tmp_path: Path):
    project = _room_project()
    apply_calibration(
        project, measured_mm=5000, pixel_start=Point2D(100, 100), pixel_end=Point2D(500, 100), method="printed"
    )
    doc, lines = _dxf_wall_lines(export_dxf(project, tmp_path / "plan.dxf"))
    assert doc.header["$INSUNITS"] == 4
    assert max(e.dxf.start.distance(e.dxf.end) for e in lines) == pytest.approx(5000.0)
    assert "PROVISIONAL" in _texts(doc)


def test_calibrated_svg_has_millimetre_size_and_lengths(tmp_path: Path):
    project = _room_project()
    apply_calibration(project, measured_mm=5000, pixel_start=Point2D(100, 100), pixel_end=Point2D(500, 100))
    svg = export_svg(project, tmp_path / "plan.svg").read_text()

    width_mm = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
    view_w = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
    assert width_mm == pytest.approx(view_w)  # 1 user unit = 1 mm
    assert 'data-scale-state="calibrated"' in svg and 'data-units="mm"' in svg
    lengths = sorted(float(v) for v in re.findall(r'data-length-mm="([\d.]+)"', svg))
    assert lengths == [3750.0, 3750.0, 5000.0, 5000.0]
    # geometry check straight from coordinates
    spans = []
    for x1, y1, x2, y2 in re.findall(r'class="wall"[^>]*x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', svg):
        spans.append(round(math.hypot(float(x2) - float(x1), float(y2) - float(y1))))
    assert sorted(spans) == [3750, 3750, 5000, 5000]
    assert "18.75 m²" in svg


def test_uncalibrated_svg_is_in_pixels_and_labelled(tmp_path: Path):
    svg = export_svg(_room_project(), tmp_path / "plan.svg").read_text()
    assert 'data-scale-state="UNCALIBRATED"' in svg and 'data-units="pixels"' in svg
    assert re.search(r'width="[\d.]+px"', svg) and "mm\"" not in svg.split("viewBox")[0]
    assert "UNCALIBRATED — pixel units, NOT real scale." in svg
    assert "data-length-mm" not in svg


def test_export_file_names_follow_scale_state_and_stale_files_are_removed(workspace: Path):
    project, project_dir = process_input(workspace, run_ocr=False, rotate=0)
    exports = project_dir / "exports"
    assert sorted(p.name for p in exports.iterdir()) == ["plan_UNCALIBRATED.dxf", "plan_UNCALIBRATED.svg"]

    apply_calibration(
        project, measured_mm=8000, pixel_start=Point2D(110, 110), pixel_end=Point2D(890, 110), method="printed"
    )
    export_project(project, project_dir)
    assert sorted(p.name for p in exports.iterdir()) == ["plan_PROVISIONAL.dxf", "plan_PROVISIONAL.svg"]

    apply_calibration(project, measured_mm=8000, pixel_start=Point2D(110, 110), pixel_end=Point2D(890, 110))
    export_project(project, project_dir)
    assert sorted(p.name for p in exports.iterdir()) == ["plan_calibrated.dxf", "plan_calibrated.svg"]

    # End to end: the detected 780 px top wall is 8.000 m in the DXF
    _doc, lines = _dxf_wall_lines(exports / "plan_calibrated.dxf")
    assert max(e.dxf.start.distance(e.dxf.end) for e in lines) == pytest.approx(8000, abs=40)
    assert load_project(project_dir).scale_state() == "calibrated"
