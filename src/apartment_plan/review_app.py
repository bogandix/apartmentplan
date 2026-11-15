"""Local Flask review UI: correct geometry, calibrate scale, preview 3D.

Everything is served from 127.0.0.1 and from files inside this package —
no CDN, no external requests, no uploads.
"""

from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, request, send_from_directory

from .detect import polygon_area_px, suggest_rooms
from .models import Confidence, EntityType, Point2D, Project, Segment, project_to_dict
from .pipeline import export_project, label_rooms_from_text
from .project_io import latest_project_dir, load_project
from .transform import apply_calibration, clear_calibration, export_suffix

UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
SEGMENT_KINDS = {
    "wall": EntityType.WALL,
    "door": EntityType.DOOR,
    "window": EntityType.WINDOW,
    "opening": EntityType.OPENING,
}


class ApiError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def create_app(root: Path, project_dir: Path | None = None) -> Flask:
    root = Path(root)
    web_dir = Path(__file__).resolve().parent / "web"
    app = Flask(__name__, static_folder=str(web_dir), static_url_path="/static")
    state = {"project_dir": Path(project_dir) if project_dir else latest_project_dir(root)}

    def _dir() -> Path:
        pd = state["project_dir"]
        if pd is None or not (pd / "project.json").is_file():
            raise ApiError("No project found. Run: apartment-plan process", 404)
        return pd

    def _commit(project: Project, action: str, **details):
        """Record the edit, save, and refresh overlay + exports."""
        project.log_edit(action, **details)
        export_project(project, _dir())
        return jsonify(_payload(project, _dir()))

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return jsonify({"error": str(exc)}), exc.status

    @app.after_request
    def _no_cache(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @app.get("/api/project")
    def api_project():
        return jsonify(_payload(load_project(_dir()), _dir()))

    @app.get("/api/source.png")
    def api_source():
        return send_from_directory(_dir(), "source.png")

    @app.get("/api/overlay.png")
    def api_overlay():
        return send_from_directory(_dir(), "overlay.png")

    @app.get("/api/exports/<path:name>")
    def api_export_file(name: str):
        return send_from_directory(_dir() / "exports", name, as_attachment=True)

    # ---- geometry edits ------------------------------------------------- #

    @app.post("/api/entities")
    def add_entity():
        project = load_project(_dir())
        body = _json()
        kind = str(body.get("kind", "wall"))
        if kind not in SEGMENT_KINDS:
            raise ApiError(f"kind must be one of {sorted(SEGMENT_KINDS)}")
        start, end = _point(body, "start"), _point(body, "end")
        if math.hypot(end.x - start.x, end.y - start.y) < 2.0:
            raise ApiError("Segment is too short; click two distinct points.")
        seg = Segment(
            id=str(uuid4()),
            entity_type=SEGMENT_KINDS[kind],
            start=start,
            end=end,
            confidence=Confidence.USER,
            thickness_px=_optional_positive(body.get("thickness_px"), "thickness_px"),
            source="user",
        )
        (project.walls if kind == "wall" else project.openings).append(seg)
        return _commit(project, "add", kind=kind, id=seg.id)

    @app.patch("/api/entities/<entity_id>")
    def update_entity(entity_id: str):
        project = load_project(_dir())
        body = _json()
        entity, group = _find(project, entity_id)
        changed = []
        if group in ("walls", "openings"):
            if "start" in body:
                entity.start = _point(body, "start")
                changed.append("start")
            if "end" in body:
                entity.end = _point(body, "end")
                changed.append("end")
            if math.hypot(entity.end.x - entity.start.x, entity.end.y - entity.start.y) < 2.0:
                raise ApiError("Segment would become too short.")
            if "thickness_px" in body:
                entity.thickness_px = _optional_positive(body["thickness_px"], "thickness_px")
                changed.append("thickness_px")
            if "kind" in body:
                kind = str(body["kind"])
                if group == "walls" or kind not in ("door", "window", "opening"):
                    raise ApiError("Only openings can change kind (door, window, opening).")
                entity.entity_type = SEGMENT_KINDS[kind]
                changed.append("kind")
        if "label" in body:
            label = str(body["label"] or "").strip()[:80]
            if group == "texts":
                entity.text = label
            else:
                entity.label = label or None
            changed.append("label")
        if not changed:
            raise ApiError("Nothing to update for this entity.")
        entity.confidence = Confidence.USER
        entity.source = "user"
        return _commit(project, "update", id=entity_id, group=group, fields=changed)

    @app.delete("/api/entities/<entity_id>")
    def remove_entity(entity_id: str):
        project = load_project(_dir())
        entity, group = _find(project, entity_id)
        entity.removed = True
        return _commit(project, "remove", id=entity_id, group=group)

    @app.post("/api/entities/<entity_id>/restore")
    def restore_entity(entity_id: str):
        project = load_project(_dir())
        entity, group = _find(project, entity_id)
        entity.removed = False
        return _commit(project, "restore", id=entity_id, group=group)

    @app.post("/api/undo-remove")
    def undo_remove():
        project = load_project(_dir())
        restored = {e.get("id") for e in project.edits if e["action"] == "restore"}
        for edit in reversed(project.edits):
            if edit["action"] == "remove" and edit.get("id"):
                try:
                    entity, group = _find(project, edit["id"])
                except ApiError:
                    continue
                if entity.removed:
                    entity.removed = False
                    return _commit(project, "restore", id=edit["id"], group=group)
            if edit["action"] == "remove_low_confidence":
                ids = [i for i in edit.get("ids", []) if i not in restored]
                hit = False
                for wall in project.walls:
                    if wall.id in ids and wall.removed:
                        wall.removed = False
                        hit = True
                if hit:
                    return _commit(project, "restore_low_confidence", ids=ids)
        raise ApiError("Nothing to undo.")

    @app.post("/api/remove-low-confidence")
    def remove_low_confidence():
        project = load_project(_dir())
        ids = []
        for wall in project.walls:
            if not wall.removed and wall.confidence == Confidence.LOW:
                wall.removed = True
                ids.append(wall.id)
        if not ids:
            raise ApiError("No low-confidence walls left.")
        return _commit(project, "remove_low_confidence", ids=ids)

    @app.post("/api/rooms/recompute")
    def recompute_rooms():
        project = load_project(_dir())
        shape = (project.source.image_height, project.source.image_width)
        project.rooms = suggest_rooms(project.active_walls(), project.active_openings(), shape)
        label_rooms_from_text(project)
        return _commit(project, "recompute_rooms", count=len(project.rooms))

    # ---- scale ---------------------------------------------------------- #

    @app.post("/api/calibrate")
    def calibrate():
        project = load_project(_dir())
        body = _json()
        try:
            if "measured_mm" in body:
                measured_mm = float(body["measured_mm"])
            else:
                unit = str(body.get("unit", "m"))
                if unit not in UNIT_TO_MM:
                    raise ValueError("unit must be m, cm or mm")
                measured_mm = float(body["length"]) * UNIT_TO_MM[unit]
            apply_calibration(
                project,
                measured_mm=measured_mm,
                pixel_start=_point(body, "start"),
                pixel_end=_point(body, "end"),
                segment_id=body.get("segment_id"),
                method=str(body.get("method", "measured")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(str(exc) or "Invalid calibration request") from exc
        return _commit(
            project,
            "calibrate",
            measured_mm=project.calibration.measured_mm,
            method=project.calibration.method,
        )

    @app.post("/api/calibration/clear")
    def calibration_clear():
        project = load_project(_dir())
        clear_calibration(project)
        return _commit(project, "clear_calibration")

    @app.post("/api/wall-height")
    def wall_height():
        project = load_project(_dir())
        height = _optional_positive(_json().get("wall_height_mm"), "wall_height_mm")
        if height is None:
            raise ApiError("wall_height_mm is required")
        project.wall_height_mm = height
        return _commit(project, "wall_height", wall_height_mm=height)

    @app.post("/api/export")
    def api_export():
        project = load_project(_dir())
        export_project(project, _dir())
        return jsonify(_payload(project, _dir()))

    # ---- 3D ------------------------------------------------------------- #

    @app.get("/api/scene")
    def api_scene():
        return jsonify(build_scene(load_project(_dir())))

    return app


def build_scene(project: Project) -> dict:
    """
    Geometry for the Three.js preview.

    Calibrated: metres. Uncalibrated: an arbitrary display scale (longest side
    = 12 units) — proportions only, flagged so the UI can say so.
    """
    from .transform import pixel_to_world

    calibrated = project.is_calibrated()
    walls = project.active_walls()
    h = project.source.image_height
    if calibrated:
        k = float(project.calibration.scale_mm_per_px) / 1000.0  # m per px
    else:
        xs = [p for w in walls for p in (w.start.x, w.end.x)] or [0.0, 1.0]
        ys = [p for w in walls for p in (w.start.y, w.end.y)] or [0.0, 1.0]
        k = 12.0 / max(max(xs) - min(xs), max(ys) - min(ys), 1.0)

    def pt(p: Point2D) -> list[float]:
        if calibrated:
            wp = pixel_to_world(p, project.calibration, h)
            return [wp.x / 1000.0, wp.y / 1000.0]
        return [(p.x - project.calibration.origin_px.x) * k, (h - p.y - project.calibration.origin_px.y) * k]

    return {
        "scale_state": project.scale_state(),
        "calibrated": calibrated,
        "note": project.calibration.note,
        "units": "metres" if calibrated else "arbitrary display units (not metres)",
        "wall_height": project.wall_height_mm / 1000.0,
        "walls": [
            {
                "id": w.id,
                "a": pt(w.start),
                "b": pt(w.end),
                "thickness": max((w.thickness_px or 0.0) * k, 0.06 if calibrated else 0.05),
            }
            for w in walls
        ],
        "openings": [
            {"id": o.id, "kind": o.entity_type.value, "a": pt(o.start), "b": pt(o.end)}
            for o in project.active_openings()
        ],
        "rooms": [
            {"id": r.id, "label": r.label, "points": [pt(p) for p in r.points]}
            for r in project.active_rooms()
        ],
    }


def _payload(project: Project, project_dir: Path) -> dict:
    data = project_to_dict(project)
    scale = project.calibration.scale_mm_per_px if project.is_calibrated() else None
    data["scale_state"] = project.scale_state()
    data["project_dir"] = str(project_dir)
    for group in ("walls", "openings"):
        for item in data[group]:
            px = math.hypot(item["end"]["x"] - item["start"]["x"], item["end"]["y"] - item["start"]["y"])
            item["length_px"] = px
            item["length_m"] = px * scale / 1000.0 if scale else None
    for item, room in zip(data["rooms"], project.rooms):
        area = polygon_area_px(room)
        item["area_px"] = area
        item["area_m2"] = area * scale * scale / 1e6 if scale else None
    suffix = export_suffix(project)
    data["exports"] = [
        {"name": f"plan_{suffix}.{ext}", "url": f"/api/exports/plan_{suffix}.{ext}"}
        for ext in ("dxf", "svg")
        if (project_dir / "exports" / f"plan_{suffix}.{ext}").is_file()
    ]
    return data


def _json() -> dict:
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        raise ApiError("Request body must be a JSON object.")
    return body


def _point(body: dict, key: str) -> Point2D:
    try:
        x, y = float(body[key]["x"]), float(body[key]["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(f"'{key}' must be an object with numeric x and y.") from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ApiError(f"'{key}' must be finite.")
    return Point2D(x, y)


def _optional_positive(value, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{name} must be a number.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ApiError(f"{name} must be a positive finite number.")
    return number


def _find(project: Project, entity_id: str):
    for group in ("walls", "openings", "rooms", "texts"):
        for entity in getattr(project, group):
            if entity.id == entity_id:
                return entity, group
    raise ApiError("Entity not found.", 404)


def run_review(root: Path, host: str = "127.0.0.1", port: int = 8765, project_dir: Path | None = None) -> None:
    app = create_app(root, project_dir=project_dir)
    print(f"Review UI: http://{host}:{port}")
    print("Local only — the plan is not uploaded anywhere.")
    app.run(host=host, port=port, debug=False)
