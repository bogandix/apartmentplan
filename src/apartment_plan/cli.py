"""Command-line interface for the apartment plan digitizer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .models import Point2D
from .ingest import UnsupportedInputError
from .pipeline import ProjectExistsError, export_project, process_input
from .project_io import latest_project_dir, load_project
from .review_app import run_review
from .transform import apply_calibration


def _repo_root() -> Path:
    # Prefer CWD so users can run from the project folder with input/
    return Path.cwd()


def cmd_process(args: argparse.Namespace) -> int:
    root = Path(args.root or _repo_root())
    input_path = Path(args.input) if args.input else None
    project, project_dir = process_input(
        root,
        input_path=input_path,
        page_index=args.page,
        dpi=args.dpi,
        run_ocr=not args.no_ocr,
        rotate=args.rotate,
        force=args.force,
    )
    print(f"Project: {project.id}")
    print(f"Directory: {project_dir}")
    print(f"Walls drafted: {len(project.active_walls())}")
    print(f"Openings suggested: {len(project.active_openings())}")
    print(f"Rooms outlined: {len(project.active_rooms())}")
    print(f"OCR texts: {len(project.active_texts())}")
    if project.source.warnings:
        print("Warnings:")
        for w in project.source.warnings:
            print(f"  - {w}")
    print("Status: UNCALIBRATED automatic draft — not checked, not real scale.")
    print(f"Draft overlay: {project_dir / 'overlay.png'}")
    print(f"Draft exports (pixel units): {project_dir / 'exports'}")
    print("Next: apartment-plan review   (check the trace, then enter a measured wall length)")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    root = Path(args.root or _repo_root())
    project_dir = Path(args.project) if args.project else latest_project_dir(root)
    if project_dir is None:
        print("No project found. Run: apartment-plan process", file=sys.stderr)
        return 1
    run_review(root, host=args.host, port=args.port, project_dir=project_dir)
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    root = Path(args.root or _repo_root())
    project_dir = Path(args.project) if args.project else latest_project_dir(root)
    if project_dir is None:
        print("No project found.", file=sys.stderr)
        return 1
    project = load_project(project_dir)
    given = [(v, f) for v, f in ((args.mm, 1.0), (args.cm, 10.0), (args.m, 1000.0)) if v is not None]
    if len(given) != 1:
        print("Give the known length exactly once: --m, --cm or --mm.", file=sys.stderr)
        return 2
    try:
        apply_calibration(
            project,
            measured_mm=given[0][0] * given[0][1],
            pixel_start=Point2D(args.x1, args.y1),
            pixel_end=Point2D(args.x2, args.y2),
            segment_id=args.segment_id,
            method="printed" if args.printed else "measured",
        )
    except ValueError as exc:
        print(f"Calibration rejected: {exc}", file=sys.stderr)
        return 2
    project.log_edit(
        "calibrate", measured_mm=project.calibration.measured_mm, method=project.calibration.method
    )
    paths = export_project(project, project_dir)
    print(project.calibration.note)
    for k, v in paths.items():
        print(f"{k}: {v}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    root = Path(args.root or _repo_root())
    project_dir = Path(args.project) if args.project else latest_project_dir(root)
    if project_dir is None:
        print("No project found.", file=sys.stderr)
        return 1
    project = load_project(project_dir)
    paths = export_project(project, project_dir)
    for k, v in paths.items():
        print(f"{k}: {v}")
    state = project.scale_state()
    if state == "UNCALIBRATED":
        print("WARNING: exports are UNCALIBRATED (pixel units, not real scale).")
    elif state == "PROVISIONAL":
        print("WARNING: exports use a PROVISIONAL scale from a printed dimension (not verified).")
    return 0


def cmd_blender_export(args: argparse.Namespace) -> int:
    from .export_blender import export_from_project_dir

    root = Path(args.root or _repo_root())
    project_dir = Path(args.project) if args.project else latest_project_dir(root)
    if project_dir is None:
        print("No project found. Run: apartment-plan process", file=sys.stderr)
        return 1
    output = Path(args.output) if args.output else root / "blender" / "apartment_demo"
    out = export_from_project_dir(
        project_dir,
        output_dir=output,
        wall_thickness_m=args.thickness,
        provisional_mm_per_px=args.provisional_mm_per_px,
    )
    print(f"Blender project: {out}")
    print(f"Next: open {out / 'README.md'}")
    print(
        "Build .blend with:\n"
        f'  blender --background --python "{out / "scripts" / "setup_scene.py"}"'
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apartment-plan",
        description="Digitize a scanned apartment plan into DXF/SVG + 3D preview (local).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--root",
        help="Project root containing input/ (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser("process", help="Process one plan from input/")
    p_process.add_argument("--input", help="Explicit input PDF/image path")
    p_process.add_argument("--page", type=int, default=0, help="PDF page index (default 0)")
    p_process.add_argument("--dpi", type=int, default=200, help="PDF render DPI (default 200)")
    p_process.add_argument("--no-ocr", action="store_true", help="Skip OCR text extraction")
    p_process.add_argument(
        "--rotate",
        default="auto",
        choices=["auto", "0", "90", "180", "270"],
        help="Clockwise rotation to make the plan upright (default: auto via OCR)",
    )
    p_process.add_argument(
        "--force", action="store_true", help="Overwrite an existing reviewed project"
    )
    p_process.set_defaults(func=cmd_process)

    p_review = sub.add_parser("review", help="Open local review + 3D preview UI")
    p_review.add_argument("--project", help="Path to a projects/<id> directory")
    p_review.add_argument("--host", default="127.0.0.1")
    p_review.add_argument("--port", type=int, default=8765)
    p_review.set_defaults(func=cmd_review)

    p_cal = sub.add_parser("calibrate", help="Calibrate scale from a measured wall (CLI)")
    p_cal.add_argument("--project", help="Path to a projects/<id> directory")
    p_cal.add_argument("--m", type=float, help="Known wall length in metres")
    p_cal.add_argument("--cm", type=float, help="Known wall length in centimetres")
    p_cal.add_argument("--mm", type=float, help="Known wall length in millimetres")
    p_cal.add_argument(
        "--printed",
        action="store_true",
        help="The length was read from a dimension printed on the plan, not measured "
        "(scale is then marked PROVISIONAL)",
    )
    p_cal.add_argument("--x1", type=float, required=True, help="Segment ends in pixels of source.png")
    p_cal.add_argument("--y1", type=float, required=True)
    p_cal.add_argument("--x2", type=float, required=True)
    p_cal.add_argument("--y2", type=float, required=True)
    p_cal.add_argument("--segment-id", default=None)
    p_cal.set_defaults(func=cmd_calibrate)

    p_export = sub.add_parser("export", help="Re-export DXF/SVG from the current project")
    p_export.add_argument("--project", help="Path to a projects/<id> directory")
    p_export.set_defaults(func=cmd_export)

    p_blend = sub.add_parser(
        "blender-export",
        help="Build a Blender project folder (OBJ walls/floor + setup script)",
    )
    p_blend.add_argument("--project", help="Path to a projects/<id> directory")
    p_blend.add_argument(
        "--output",
        help="Output folder (default: blender/apartment_demo)",
    )
    p_blend.add_argument(
        "--thickness",
        type=float,
        default=0.12,
        help="Wall thickness in metres (default 0.12)",
    )
    p_blend.add_argument(
        "--provisional-mm-per-px",
        type=float,
        default=None,
        help="If uncalibrated, provisional mm/px scale for mesh export",
    )
    p_blend.set_defaults(func=cmd_blender_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (UnsupportedInputError, FileNotFoundError, ProjectExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
