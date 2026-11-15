from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from apartment_plan.export_blender import build_wall_mesh, export_from_project_dir
from apartment_plan.pipeline import process_input


def test_build_wall_mesh_box():
    mesh = build_wall_mesh([((0.0, 0.0), (2.0, 0.0))], height_m=2.7, thickness_m=0.1)
    assert len(mesh["vertices"]) == 8
    assert len(mesh["faces"]) == 6
    zs = [v[2] for v in mesh["vertices"]]
    assert min(zs) == 0.0
    assert max(zs) == 2.7


def test_blender_export_package(tmp_path: Path):
    img = np.full((400, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (40, 40), (560, 360), (0, 0, 0), 6)
    inp = tmp_path / "input" / "box.png"
    inp.parent.mkdir()
    cv2.imwrite(str(inp), img)
    _, project_dir = process_input(tmp_path, input_path=inp, run_ocr=False)

    out = export_from_project_dir(project_dir, output_dir=tmp_path / "blender_demo")
    assert (out / "assets" / "walls.obj").is_file()
    assert (out / "assets" / "floor.obj").is_file()
    assert (out / "scripts" / "setup_scene.py").is_file()
    assert (out / "README.md").is_file()
    assert "v " in (out / "assets" / "walls.obj").read_text()
