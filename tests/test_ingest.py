"""PDF / image input handling."""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import pymupdf
import pytest

from apartment_plan.ingest import (
    SUPPORTED_EXTENSIONS,
    UnsupportedInputError,
    find_input_file,
    load_plan_image,
)
from apartment_plan.pipeline import process_input

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = ROOT / "input" / "IMG_20261115_0002.pdf"


@pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".tif", ".tiff"])
def test_raster_formats_load(tmp_path: Path, synthetic_plan, ext: str):
    path = tmp_path / f"plan{ext}"
    assert cv2.imwrite(str(path), synthetic_plan)
    image, _warnings = load_plan_image(path)
    assert image.shape == synthetic_plan.shape


def _make_pdf(path: Path, png: Path, pages: int = 1) -> None:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=500, height=350)
        page.insert_image(page.rect, filename=str(png))
    doc.save(path)
    doc.close()


def test_pdf_page_renders_at_requested_dpi(tmp_path: Path, synthetic_plan):
    png = tmp_path / "plan.png"
    cv2.imwrite(str(png), synthetic_plan)
    pdf = tmp_path / "plan.pdf"
    _make_pdf(pdf, png)
    image, _ = load_plan_image(pdf, dpi=144)
    # 500x350 pt at 144 dpi = 1000x700 px
    assert image.shape[:2] == (700, 1000)


def test_pdf_page_out_of_range_is_actionable(tmp_path: Path, synthetic_plan):
    png = tmp_path / "plan.png"
    cv2.imwrite(str(png), synthetic_plan)
    pdf = tmp_path / "plan.pdf"
    _make_pdf(pdf, png, pages=2)
    load_plan_image(pdf, page_index=1)
    with pytest.raises(UnsupportedInputError, match="--page"):
        load_plan_image(pdf, page_index=2)


def test_unsupported_extension_lists_supported_types(tmp_path: Path):
    bad = tmp_path / "plan.docx"
    bad.write_text("nope")
    with pytest.raises(UnsupportedInputError) as exc:
        load_plan_image(bad)
    for ext in (".pdf", ".png", ".jpg", ".tiff"):
        assert ext in str(exc.value)
        assert ext in SUPPORTED_EXTENSIONS


def test_corrupt_files_are_rejected(tmp_path: Path):
    fake_png = tmp_path / "plan.png"
    fake_png.write_bytes(b"this is not an image")
    with pytest.raises(UnsupportedInputError):
        load_plan_image(fake_png)
    fake_pdf = tmp_path / "plan.pdf"
    fake_pdf.write_bytes(b"this is not a pdf")
    with pytest.raises(UnsupportedInputError):
        load_plan_image(fake_pdf)


def test_input_folder_must_hold_exactly_one_plan(tmp_path: Path, synthetic_plan):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="Supported"):
        find_input_file(input_dir)
    cv2.imwrite(str(input_dir / "a.png"), synthetic_plan)
    (input_dir / "notes.txt").write_text("ignored")
    assert find_input_file(input_dir).name == "a.png"
    cv2.imwrite(str(input_dir / "b.jpg"), synthetic_plan)
    with pytest.raises(UnsupportedInputError, match="one at a time"):
        find_input_file(input_dir)


def test_processing_leaves_original_untouched_and_writes_elsewhere(workspace: Path):
    original = workspace / "input" / "plan.png"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    project, project_dir = process_input(workspace, run_ocr=False, rotate=0)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    assert project.source.original_sha256 == before
    assert project_dir == workspace / "projects" / "plan"
    assert sorted(p.name for p in (workspace / "input").iterdir()) == ["plan.png"]
    for name in ("source.png", "overlay.png", "project.json"):
        assert (project_dir / name).is_file()


def test_blurry_small_scan_warns(tmp_path: Path, synthetic_plan):
    small = cv2.GaussianBlur(cv2.resize(synthetic_plan, (300, 210)), (0, 0), 4)
    path = tmp_path / "blurry.png"
    cv2.imwrite(str(path), small)
    _image, warnings = load_plan_image(path)
    text = " ".join(warnings).lower()
    assert "small" in text and "blurry" in text


@pytest.mark.skipif(not SAMPLE_PDF.is_file(), reason="sample PDF not present in input/")
def test_real_scan_pdf_produces_reviewable_uncalibrated_draft(tmp_path: Path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / SAMPLE_PDF.name).symlink_to(SAMPLE_PDF)
    project, project_dir = process_input(tmp_path, run_ocr=False, rotate=90)
    assert not project.is_calibrated()
    assert project.scale_state() == "UNCALIBRATED"
    assert project.source.rotation_deg == 90
    assert project.source.image_width > project.source.image_height  # landscape after rotation
    assert 15 <= len(project.active_walls()) <= 80
    assert any("Ignored" in w for w in project.source.warnings)  # key plan / stamp skipped
    assert (project_dir / "overlay.png").is_file()
    assert (project_dir / "exports" / "plan_UNCALIBRATED.dxf").is_file()
