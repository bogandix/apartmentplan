"""End-to-end processing: ingest → normalize → detect → project artifacts."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import cv2

from .detect import detect_geometry, point_in_polygon
from .export_dxf import export_dxf
from .export_svg import export_svg
from .ingest import find_input_file, load_plan_image
from .models import Point2D, Project, SourceInfo
from .ocr import extract_text_labels, room_name_candidates
from .overlay import save_overlay
from .preprocess import preprocess
from .project_io import load_project, save_project
from .transform import export_suffix


class ProjectExistsError(RuntimeError):
    pass


def project_id_for(input_path: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(input_path).stem).strip("_")
    return slug or "plan"


def _portable_path(path: Path, root: Path) -> str:
    """Path relative to the project root when possible (keeps project files shareable)."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def process_input(
    root: Path,
    input_path: Path | None = None,
    *,
    page_index: int = 0,
    dpi: int = 200,
    run_ocr: bool = True,
    rotate: str | int = "auto",
    force: bool = False,
) -> tuple[Project, Path]:
    """
    Process one plan from input/ (or an explicit path) into projects/<name>/.

    The original file is only read. Returns (project, project_dir).
    """
    root = Path(root)
    input_path = find_input_file(root / "input") if input_path is None else Path(input_path)

    project_id = project_id_for(input_path)
    project_dir = root / "projects" / project_id
    if (project_dir / "project.json").is_file() and not force:
        existing = load_project(project_dir)
        if existing.edits or existing.is_calibrated():
            raise ProjectExistsError(
                f"{project_dir} already holds reviewed work ({len(existing.edits)} edit(s), "
                f"scale: {existing.scale_state()}). Re-run with --force to discard it, "
                "or continue with: apartment-plan review"
            )

    image, warnings = load_plan_image(input_path, page_index=page_index, dpi=dpi)
    prepared = preprocess(image, rotate=rotate)
    warnings.extend(prepared.warnings)
    detection = detect_geometry(prepared.fill_mask)
    warnings.extend(detection.warnings)

    texts = []
    if run_ocr:
        texts, ocr_warnings = extract_text_labels(prepared.image, detection.plan_bbox)
        warnings.extend(ocr_warnings)

    h, w = prepared.image.shape[:2]
    source = SourceInfo(
        original_path=_portable_path(input_path, root),
        page_index=page_index,
        image_width=w,
        image_height=h,
        rendered_path="source.png",
        warnings=warnings,
        rotation_deg=prepared.rotation_deg,
        skew_deg=round(prepared.skew_deg, 3),
        dpi=dpi if input_path.suffix.lower() == ".pdf" else None,
        plan_bbox=list(detection.plan_bbox) if detection.plan_bbox else None,
        original_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
    )
    project = Project.new(source)
    project.id = project_id
    project.walls = detection.walls
    project.openings = detection.openings
    project.rooms = detection.rooms
    project.texts = texts
    label_rooms_from_text(project)
    if detection.plan_bbox:
        # World origin at the bottom-left corner of the plan region
        x0, _y0, _x1, y1 = detection.plan_bbox
        project.calibration.origin_px = Point2D(float(x0), float(h - y1))

    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)
    cv2.imwrite(str(project_dir / "source.png"), prepared.image)
    cv2.imwrite(str(project_dir / "wall_mask.png"), prepared.fill_mask)
    export_project(project, project_dir)
    return project, project_dir


def label_rooms_from_text(project: Project) -> None:
    """Attach an OCR word found inside a room as its *suggested* name."""
    names = room_name_candidates(project.active_texts())
    for room in project.active_rooms():
        if room.label:
            continue
        inside = [
            t for t in names
            if point_in_polygon(t.position.x + t.width / 2, t.position.y + t.height / 2, room)
        ]
        if inside:
            room.label = max(inside, key=lambda t: t.height).text + " (?)"


def export_project(project: Project, project_dir: Path) -> dict[str, Path]:
    """Save project.json, refresh the overlay and write DXF/SVG for the current scale state."""
    project_dir = Path(project_dir)
    exports = project_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    suffix = export_suffix(project)
    # Remove exports from a previous scale state so stale files cannot be mistaken for current
    for old in exports.glob("plan_*"):
        if old.suffix in (".dxf", ".svg") and old.stem != f"plan_{suffix}":
            old.unlink()
    dxf = export_dxf(project, exports / f"plan_{suffix}.dxf")
    svg = export_svg(project, exports / f"plan_{suffix}.svg")
    save_project(project, project_dir)

    image = cv2.imread(str(project_dir / "source.png"))
    if image is not None:
        save_overlay(image, project, project_dir / "overlay.png")
    return {"dxf": dxf, "svg": svg, "project": project_dir / "project.json"}
