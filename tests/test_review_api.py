"""Local review API: correcting the draft, calibrating, 3D scene data."""

from __future__ import annotations

from pathlib import Path

import pytest

from apartment_plan.pipeline import ProjectExistsError, process_input
from apartment_plan.project_io import load_project
from apartment_plan.review_app import create_app


@pytest.fixture
def client(workspace: Path):
    _project, project_dir = process_input(workspace, run_ocr=False, rotate=0)
    app = create_app(workspace, project_dir=project_dir)
    app.testing = True
    with app.test_client() as c:
        c.project_dir = project_dir
        c.workspace = workspace
        yield c


def _active(data, group):
    return [e for e in data[group] if not e["removed"]]


def test_draft_is_served_with_scan_and_uncalibrated_state(client):
    data = client.get("/api/project").get_json()
    assert data["scale_state"] == "UNCALIBRATED"
    assert all(w["length_m"] is None for w in data["walls"])  # no fake metres
    assert all(r["area_m2"] is None for r in data["rooms"])
    assert [e["name"] for e in data["exports"]] == ["plan_UNCALIBRATED.dxf", "plan_UNCALIBRATED.svg"]
    assert client.get("/api/source.png").status_code == 200
    assert client.get("/api/overlay.png").status_code == 200
    assert client.get("/").status_code == 200
    page = client.get("/").get_data(as_text=True)
    assert "http://" not in page and "https://" not in page  # nothing loaded from the internet
    assert client.get("/static/vendor/three.module.js").status_code == 200


def test_add_move_remove_and_undo_wall(client):
    before = len(_active(client.get("/api/project").get_json(), "walls"))
    data = client.post(
        "/api/entities", json={"kind": "wall", "start": {"x": 300, "y": 120}, "end": {"x": 300, "y": 580}}
    ).get_json()
    walls = _active(data, "walls")
    assert len(walls) == before + 1
    new = next(w for w in walls if w["source"] == "user")
    assert new["confidence"] == "user"

    data = client.patch(f"/api/entities/{new['id']}", json={"end": {"x": 300, "y": 400}}).get_json()
    moved = next(w for w in data["walls"] if w["id"] == new["id"])
    assert moved["end"] == {"x": 300, "y": 400}
    assert moved["length_px"] == pytest.approx(280)

    data = client.delete(f"/api/entities/{new['id']}").get_json()
    assert len(_active(data, "walls")) == before
    data = client.post("/api/undo-remove").get_json()
    assert len(_active(data, "walls")) == before + 1

    actions = [e["action"] for e in load_project(client.project_dir).edits]
    assert actions == ["add", "update", "remove", "restore"]


def test_openings_and_rooms_are_editable(client):
    data = client.get("/api/project").get_json()
    opening = _active(data, "openings")[0]
    assert opening["entity_type"] == "opening"
    data = client.patch(f"/api/entities/{opening['id']}", json={"kind": "door"}).get_json()
    assert _active(data, "openings")[0]["entity_type"] == "door"

    room = _active(data, "rooms")[0]
    data = client.patch(f"/api/entities/{room['id']}", json={"label": "Bedroom"}).get_json()
    assert any(r["label"] == "Bedroom" for r in data["rooms"])

    # Removing the door and recomputing merges the two rooms into one
    client.delete(f"/api/entities/{opening['id']}")
    data = client.post("/api/rooms/recompute").get_json()
    assert len(_active(data, "rooms")) == 1


def test_bad_edit_requests_are_rejected(client):
    assert client.post("/api/entities", json={"kind": "sofa", "start": {"x": 0, "y": 0}, "end": {"x": 9, "y": 9}}).status_code == 400
    assert client.post("/api/entities", json={"kind": "wall", "start": {"x": 5, "y": 5}, "end": {"x": 5, "y": 5}}).status_code == 400
    assert client.post("/api/entities", json={"kind": "wall", "start": {"x": "a"}, "end": {"x": 1, "y": 1}}).status_code == 400
    assert client.delete("/api/entities/does-not-exist").status_code == 404
    assert client.post("/api/wall-height", json={"wall_height_mm": -5}).status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {"length": 0, "unit": "m"},
        {"length": -3, "unit": "m"},
        {"length": "abc", "unit": "m"},
        {"length": 1e999, "unit": "m"},
        {"length": 3, "unit": "feet"},
        {"length": 3, "unit": "m", "method": "guess"},
        {"unit": "m"},
    ],
)
def test_invalid_calibration_is_rejected_and_state_unchanged(client, body):
    body = {"start": {"x": 110, "y": 110}, "end": {"x": 890, "y": 110}, **body}
    res = client.post("/api/calibrate", json=body)
    assert res.status_code == 400 and res.get_json()["error"]
    assert client.get("/api/project").get_json()["scale_state"] == "UNCALIBRATED"


def test_calibration_needs_two_distinct_endpoints(client):
    res = client.post("/api/calibrate", json={"length": 3, "unit": "m", "start": {"x": 110, "y": 110}})
    assert res.status_code == 400
    res = client.post(
        "/api/calibrate",
        json={"length": 3, "unit": "m", "start": {"x": 110, "y": 110}, "end": {"x": 111, "y": 110}},
    )
    assert res.status_code == 400


def test_calibrate_with_one_measured_wall_then_export_and_3d(client):
    res = client.post(
        "/api/calibrate",
        json={"length": 8, "unit": "m", "start": {"x": 110, "y": 110}, "end": {"x": 890, "y": 110}},
    )
    data = res.get_json()
    assert res.status_code == 200 and data["scale_state"] == "calibrated"
    assert data["calibration"]["measured_mm"] == 8000
    assert data["calibration"]["scale_mm_per_px"] == pytest.approx(8000 / 780)
    longest = max(w["length_m"] for w in data["walls"])
    assert longest == pytest.approx(8.0, abs=0.05)
    assert all(r["area_m2"] > 0 for r in _active(data, "rooms"))
    assert [e["name"] for e in data["exports"]] == ["plan_calibrated.dxf", "plan_calibrated.svg"]
    assert client.get(data["exports"][0]["url"]).status_code == 200

    scene = client.get("/api/scene").get_json()
    assert scene["calibrated"] and scene["units"] == "metres"
    assert scene["wall_height"] == pytest.approx(2.7)
    xs = [c for w in scene["walls"] for c in (w["a"][0], w["b"][0])]
    assert max(xs) - min(xs) == pytest.approx(8.0, abs=0.05)  # same geometry as the 2D plan
    assert len(scene["walls"]) == len(_active(data, "walls"))

    data = client.post("/api/wall-height", json={"wall_height_mm": 2550}).get_json()
    assert client.get("/api/scene").get_json()["wall_height"] == pytest.approx(2.55)

    data = client.post("/api/calibration/clear").get_json()
    assert data["scale_state"] == "UNCALIBRATED"


def test_units_cm_and_mm_and_printed_method(client):
    seg = {"start": {"x": 110, "y": 110}, "end": {"x": 890, "y": 110}}
    data = client.post("/api/calibrate", json={"length": 800, "unit": "cm", "method": "printed", **seg}).get_json()
    assert data["scale_state"] == "PROVISIONAL"
    assert data["calibration"]["measured_mm"] == 8000
    assert [e["name"] for e in data["exports"]] == ["plan_PROVISIONAL.dxf", "plan_PROVISIONAL.svg"]
    data = client.post("/api/calibrate", json={"length": 8000, "unit": "mm", **seg}).get_json()
    assert data["scale_state"] == "calibrated"


def test_uncalibrated_scene_is_flagged_not_metres(client):
    scene = client.get("/api/scene").get_json()
    assert not scene["calibrated"]
    assert scene["scale_state"] == "UNCALIBRATED"
    assert "not metres" in scene["units"]


def test_reprocessing_does_not_silently_discard_reviewed_work(client):
    client.post("/api/entities", json={"kind": "wall", "start": {"x": 300, "y": 120}, "end": {"x": 300, "y": 580}})
    with pytest.raises(ProjectExistsError, match="--force"):
        process_input(client.workspace, run_ocr=False, rotate=0)
    project, _ = process_input(client.workspace, run_ocr=False, rotate=0, force=True)
    assert project.edits == []
