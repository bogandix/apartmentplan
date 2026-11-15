"""Local Flask review UI: correct geometry, calibrate scale, preview 3D."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, request, send_from_directory

from .models import Confidence, EntityType, Point2D, Segment
from .pipeline import export_project
from .project_io import latest_project_dir, load_project, save_project
from .transform import apply_calibration


def create_app(root: Path, project_dir: Path | None = None) -> Flask:
    root = Path(root)
    web_dir = Path(__file__).resolve().parent / "web"
    app = Flask(__name__, static_folder=str(web_dir), static_url_path="/static")
    state = {"project_dir": Path(project_dir) if project_dir else latest_project_dir(root)}

    def _project_dir() -> Path:
        pd = state["project_dir"]
        if pd is None or not (pd / "project.json").is_file():
            raise FileNotFoundError("No project found. Run: apartment-plan process")
        return pd

    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @app.get("/api/project")
    def api_project():
        pd = _project_dir()
        project = load_project(pd)
        data = _serialize(project)
        data["project_dir"] = str(pd)
        data["source_image_url"] = "/api/source.png"
        data["overlay_image_url"] = "/api/overlay.png"
        return jsonify(data)

    @app.get("/api/source.png")
    def api_source():
        pd = _project_dir()
        return send_from_directory(pd, "source.png")

    @app.get("/api/overlay.png")
    def api_overlay():
        pd = _project_dir()
        return send_from_directory(pd, "overlay.png")

    @app.post("/api/walls/<wall_id>/remove")
    def remove_wall(wall_id: str):
        pd = _project_dir()
        project = load_project(pd)
        for wall in project.walls:
            if wall.id == wall_id:
                wall.removed = True
                break
        else:
            return jsonify({"error": "wall not found"}), 404
        save_project(project, pd)
        export_project(project, pd)
        return jsonify({"ok": True})

    @app.post("/api/walls")
    def add_wall():
        pd = _project_dir()
        project = load_project(pd)
        body = request.get_json(force=True)
        wall = Segment(
            id=str(uuid4()),
            entity_type=EntityType.WALL,
            start=Point2D(float(body["start"]["x"]), float(body["start"]["y"])),
            end=Point2D(float(body["end"]["x"]), float(body["end"]["y"])),
            confidence=Confidence.USER,
            source="user",
        )
        project.walls.append(wall)
        save_project(project, pd)
        export_project(project, pd)
        return jsonify({"ok": True, "wall": _seg(wall)})

    @app.post("/api/calibrate")
    def calibrate():
        pd = _project_dir()
        project = load_project(pd)
        body = request.get_json(force=True)
        try:
            measured = float(body["measured_mm"])
            start = Point2D(float(body["start"]["x"]), float(body["start"]["y"]))
            end = Point2D(float(body["end"]["x"]), float(body["end"]["y"]))
            apply_calibration(
                project,
                measured_mm=measured,
                pixel_start=start,
                pixel_end=end,
                segment_id=body.get("segment_id"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        paths = export_project(project, pd)
        return jsonify(
            {
                "ok": True,
                "calibrated": True,
                "note": project.calibration.note,
                "exports": {k: str(v) for k, v in paths.items()},
            }
        )

    @app.post("/api/wall-height")
    def wall_height():
        pd = _project_dir()
        project = load_project(pd)
        body = request.get_json(force=True)
        try:
            height = float(body["wall_height_mm"])
            if height <= 0:
                raise ValueError("wall_height_mm must be positive")
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        project.wall_height_mm = height
        save_project(project, pd)
        return jsonify({"ok": True, "wall_height_mm": height})

    @app.post("/api/export")
    def api_export():
        pd = _project_dir()
        project = load_project(pd)
        paths = export_project(project, pd)
        return jsonify({"ok": True, "exports": {k: str(v) for k, v in paths.items()}})

    @app.get("/api/scene")
    def api_scene():
        """Geometry for Three.js preview in metres."""
        pd = _project_dir()
        project = load_project(pd)
        from .transform import pixel_to_world

        h = project.source.image_height
        scale = project.calibration.scale_mm_per_px or 1.0
        walls = []
        for wall in project.active_walls():
            a = pixel_to_world(wall.start, project.calibration, h)
            b = pixel_to_world(wall.end, project.calibration, h)
            walls.append(
                {
                    "id": wall.id,
                    "a": [a.x / 1000.0, a.y / 1000.0],
                    "b": [b.x / 1000.0, b.y / 1000.0],
                }
            )
        return jsonify(
            {
                "calibrated": project.is_calibrated(),
                "note": project.calibration.note,
                "wall_height_m": project.wall_height_mm / 1000.0,
                "units": "metres" if project.is_calibrated() else "UNCALIBRATED_pseudo_metres",
                "walls": walls,
            }
        )

    return app


def _seg(wall: Segment) -> dict:
    return {
        "id": wall.id,
        "start": {"x": wall.start.x, "y": wall.start.y},
        "end": {"x": wall.end.x, "y": wall.end.y},
        "confidence": wall.confidence.value,
        "source": wall.source,
        "removed": wall.removed,
    }


def _serialize(project) -> dict:
    from .models import project_to_dict

    return project_to_dict(project)


def run_review(root: Path, host: str = "127.0.0.1", port: int = 8765, project_dir: Path | None = None) -> None:
    app = create_app(root, project_dir=project_dir)
    print(f"Review UI: http://{host}:{port}")
    print("Local only — plans are not uploaded.")
    app.run(host=host, port=port, debug=False)
