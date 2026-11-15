"""Automatic draft: walls, openings, rooms, orientation handling."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from apartment_plan.detect import detect_geometry, polygon_area_px, suggest_rooms
from apartment_plan.models import Confidence, EntityType, Point2D, Segment
from apartment_plan.pipeline import process_input
from apartment_plan.preprocess import estimate_skew_angle, preprocess, rotate_image


def _axis(seg):
    horizontal = abs(seg.end.y - seg.start.y) < abs(seg.end.x - seg.start.x)
    return horizontal, (seg.start.y if horizontal else seg.start.x)


def test_walls_are_centre_lines_of_filled_bands(synthetic_plan):
    det = detect_geometry(preprocess(synthetic_plan, rotate=0).fill_mask)
    horizontals = sorted(c for h, c in map(_axis, det.walls) if h)
    verticals = sorted(c for h, c in map(_axis, det.walls) if not h)
    # outer box centre-lines at 110 / 590 (y) and 110 / 890 (x); partition at x = 500
    assert [round(c / 5) * 5 for c in horizontals] == [110, 590]
    assert [round(c / 5) * 5 for c in verticals] == [110, 500, 500, 890]
    outer = [w for w in det.walls if w.thickness_px and w.thickness_px > 15]
    assert len(outer) == 4
    assert all(abs(w.thickness_px - 21) <= 3 for w in outer)
    # corners are joined: the top wall ends on the side walls' centre-lines
    top = min((w for w in det.walls if _axis(w)[0]), key=lambda w: w.start.y)
    assert abs(min(top.start.x, top.end.x) - 110) <= 3
    assert abs(max(top.start.x, top.end.x) - 890) <= 3


def test_furniture_blob_and_key_plan_are_not_walls(synthetic_plan):
    det = detect_geometry(preprocess(synthetic_plan, rotate=0).fill_mask)
    for wall in det.walls:
        for p in (wall.start, wall.end):
            assert not (190 < p.x < 340 and 240 < p.y < 410), "furniture traced as wall"
            assert not (p.x > 920 and p.y > 620), "key plan traced as wall"
    assert any("Ignored" in w for w in det.warnings)
    x0, y0, x1, y1 = det.plan_bbox
    assert (abs(x0 - 100), abs(y0 - 100), abs(x1 - 900), abs(y1 - 600)) <= (4, 4, 4, 4)


def test_door_gap_becomes_low_confidence_opening_and_rooms_close(synthetic_plan):
    det = detect_geometry(preprocess(synthetic_plan, rotate=0).fill_mask)
    assert len(det.openings) == 1
    opening = det.openings[0]
    assert opening.entity_type == EntityType.OPENING  # door vs window is not guessed
    assert opening.confidence == Confidence.LOW
    assert abs(opening.start.x - 500) <= 3
    assert abs(min(opening.start.y, opening.end.y) - 300) <= 4
    assert abs(max(opening.start.y, opening.end.y) - 380) <= 4
    assert len(det.rooms) == 2
    # inner faces: left room 120..495 x 120..580, right room 505..880
    areas = sorted(polygon_area_px(r) for r in det.rooms)
    assert all(abs(a - 375 * 460) / (375 * 460) < 0.05 for a in areas)
    assert all(r.confidence == Confidence.LOW for r in det.rooms)


def test_rooms_follow_user_edits():
    def wall(x1, y1, x2, y2):
        return Segment("w", EntityType.WALL, Point2D(x1, y1), Point2D(x2, y2), thickness_px=10)

    box = [wall(100, 100, 500, 100), wall(500, 100, 500, 400), wall(500, 400, 100, 400)]
    assert suggest_rooms(box, [], (500, 600)) == []  # open on the left
    box.append(wall(100, 400, 100, 100))
    rooms = suggest_rooms(box, [], (500, 600))
    assert len(rooms) == 1
    assert abs(polygon_area_px(rooms[0]) - 390 * 290) / (390 * 290) < 0.05


def test_blank_page_warns_instead_of_inventing_geometry():
    blank = np.full((600, 800, 3), 255, np.uint8)
    det = detect_geometry(preprocess(blank, rotate=0).fill_mask)
    assert det.walls == [] and det.rooms == []
    assert any("No wall-like" in w for w in det.warnings)


def test_plan_touching_the_scan_edge_warns_about_clipping(synthetic_plan):
    clipped = synthetic_plan[:, 105:]  # cut through the left wall
    det = detect_geometry(preprocess(clipped, rotate=0).fill_mask)
    assert any("clipped" in w for w in det.warnings)


def test_small_skew_is_measured_and_removed(synthetic_plan):
    skewed = rotate_image(synthetic_plan, -3.0)
    angle = estimate_skew_angle(cv2.cvtColor(skewed, cv2.COLOR_BGR2GRAY))
    assert abs(angle - (-3.0)) < 0.4 or abs(angle - 3.0) < 0.4
    prepared = preprocess(skewed, rotate=0)
    assert abs(estimate_skew_angle(prepared.gray)) < 0.4
    det = detect_geometry(prepared.fill_mask)
    assert len([w for w in det.walls if (w.thickness_px or 0) > 15]) == 4


def test_explicit_rotation_is_recorded(workspace: Path):
    project, project_dir = process_input(workspace, run_ocr=False, rotate=90)
    assert project.source.rotation_deg == 90
    assert (project.source.image_width, project.source.image_height) == (700, 1000)
    source = cv2.imread(str(project_dir / "source.png"))
    assert source.shape[:2] == (1000, 700)
