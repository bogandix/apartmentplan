"""End-to-end processing: ingest → detect → project artifacts."""

from __future__ import annotations

from pathlib import Path

import cv2

from .detect import detect_geometry
from .export_dxf import export_dxf
from .export_svg import export_svg
from .ingest import find_input_file, load_plan_image
from .models import Project, SourceInfo
from .ocr import extract_text_labels
from .overlay import save_overlay
from .preprocess import preprocess
from .project_io import save_project


def process_input(
    root: Path,
    input_path: Path | None = None,
    *,
    page_index: int = 0,
    dpi: int = 200,
    run_ocr: bool = True,
) -> tuple[Project, Path]:
    """
    Process one plan from input/ (or an explicit path).

    Returns (project, project_dir).
    """
    root = Path(root)
    input_dir = root / "input"
    if input_path is None:
        input_path = find_input_file(input_dir)
    else:
        input_path = Path(input_path)

    image, warnings = load_plan_image(input_path, page_index=page_index, dpi=dpi)
    prepared = preprocess(image)
    deskewed = prepared["deskewed"]
    assert isinstance(deskewed, type(image))

    walls, rooms, detect_warnings = detect_geometry(prepared["binary"], prepared["edges"])
    warnings.extend(detect_warnings)

    texts = []
    if run_ocr:
        texts, ocr_warnings = extract_text_labels(deskewed)
        warnings.extend(ocr_warnings)

    h, w = deskewed.shape[:2]
    source = SourceInfo(
        original_path=str(input_path.resolve()),
        page_index=page_index,
        image_width=w,
        image_height=h,
        warnings=warnings,
    )
    project = Project.new(source)
    project.walls = walls
    project.rooms = rooms
    project.texts = texts

    project_dir = root / "projects" / project.id
    project_dir.mkdir(parents=True, exist_ok=True)

    rendered = project_dir / "source.png"
    cv2.imwrite(str(rendered), deskewed)
    project.source.rendered_path = str(rendered)

    binary_path = project_dir / "binary.png"
    cv2.imwrite(str(binary_path), prepared["binary"])

    save_overlay(deskewed, project, project_dir / "overlay.png")
    save_project(project, project_dir)

    # Draft exports — clearly uncalibrated until user measures a wall
    export_dxf(project, project_dir / "exports" / "plan_UNCALIBRATED.dxf")
    export_svg(project, project_dir / "exports" / "plan_UNCALIBRATED.svg")

    return project, project_dir


def export_project(project: Project, project_dir: Path) -> dict[str, Path]:
    project_dir = Path(project_dir)
    exports = project_dir / "exports"
    suffix = "calibrated" if project.is_calibrated() else "UNCALIBRATED"
    dxf = export_dxf(project, exports / f"plan_{suffix}.dxf")
    svg = export_svg(project, exports / f"plan_{suffix}.svg")
    save_project(project, project_dir)

    rendered = project.source.rendered_path
    if rendered and Path(rendered).is_file():
        image = cv2.imread(rendered)
        if image is not None:
            save_overlay(image, project, project_dir / "overlay.png")

    return {"dxf": dxf, "svg": svg, "project": project_dir / "project.json"}
