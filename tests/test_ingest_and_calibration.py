from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from apartment_plan.export_dxf import export_dxf
from apartment_plan.export_svg import export_svg
from apartment_plan.ingest import UnsupportedInputError, load_plan_image
from apartment_plan.models import Point2D, Project, Segment, SourceInfo, EntityType, Confidence
from apartment_plan.pipeline import process_input
from apartment_plan.transform import apply_calibration, pixel_to_world, validate_measured_mm


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = ROOT / "input" / "IMG_20261115_0002.pdf"


def test_validate_measured_mm_rejects_bad_values():
    with pytest.raises(ValueError):
        validate_measured_mm(0)
    with pytest.raises(ValueError):
        validate_measured_mm(-10)
    with pytest.raises(ValueError):
        validate_measured_mm(float("nan"))
    assert validate_measured_mm(3500) == 3500.0


def test_unsupported_extension(tmp_path: Path):
    bad = tmp_path / "plan.txt"
    bad.write_text("nope")
    with pytest.raises(UnsupportedInputError):
        load_plan_image(bad)


def test_calibration_sets_scale_and_world_coords():
    source = SourceInfo(original_path="x.png", image_width=1000, image_height=800)
    project = Project.new(source)
    apply_calibration(
        project,
        measured_mm=4000,
        pixel_start=Point2D(100, 100),
        pixel_end=Point2D(500, 100),  # 400 px → 10 mm/px
    )
    assert project.is_calibrated()
    assert project.calibration.scale_mm_per_px == pytest.approx(10.0)
    world = pixel_to_world(Point2D(100, 100), project.calibration, 800)
    # y flipped: (800-100)*10 = 7000
    assert world.x == pytest.approx(1000.0)  # (100-0)*10
    assert world.y == pytest.approx(7000.0)


def test_export_dimensions_match_calibration(tmp_path: Path):
    source = SourceInfo(original_path="x.png", image_width=500, image_height=400)
    project = Project.new(source)
    project.walls = [
        Segment(
            id="w1",
            entity_type=EntityType.WALL,
            start=Point2D(0, 0),
            end=Point2D(200, 0),
            confidence=Confidence.USER,
            source="user",
        )
    ]
    apply_calibration(
        project,
        measured_mm=2000,
        pixel_start=Point2D(0, 0),
        pixel_end=Point2D(200, 0),
    )
    dxf_path = export_dxf(project, tmp_path / "plan.dxf")
    svg_path = export_svg(project, tmp_path / "plan.svg")
    assert dxf_path.is_file()
    assert svg_path.is_file()
    text = dxf_path.read_text(errors="ignore")
    # 200 px * 10 mm/px = 2000 mm wall should appear as coordinate 2000
    assert "2000" in text
    svg = svg_path.read_text()
    assert "calibrated_mm" in svg


@pytest.mark.skipif(not SAMPLE_PDF.is_file(), reason="sample PDF missing")
def test_process_sample_pdf(tmp_path: Path):
    # Use a temp root with a copy of the sample input
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    # symlink to avoid copying large PDF
    target = input_dir / SAMPLE_PDF.name
    target.symlink_to(SAMPLE_PDF)

    project, project_dir = process_input(tmp_path, run_ocr=False)
    assert project.source.image_width > 0
    assert (project_dir / "source.png").is_file()
    assert (project_dir / "overlay.png").is_file()
    assert (project_dir / "project.json").is_file()
    assert (project_dir / "exports" / "plan_UNCALIBRATED.dxf").is_file()
    assert not project.is_calibrated()
    # Should find some geometry on a real scan
    assert len(project.walls) >= 1


def test_synthetic_plan_detection(tmp_path: Path):
    # Draw a simple rectangular floor plan
    img = np.full((600, 800, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (80, 80), (720, 520), (0, 0, 0), 8)
    cv2.line(img, (400, 80), (400, 520), (0, 0, 0), 6)
    path = tmp_path / "input" / "synthetic.png"
    path.parent.mkdir()
    cv2.imwrite(str(path), img)

    project, project_dir = process_input(tmp_path, input_path=path, run_ocr=False)
    assert len(project.active_walls()) >= 3
    assert (project_dir / "exports" / "plan_UNCALIBRATED.svg").is_file()
