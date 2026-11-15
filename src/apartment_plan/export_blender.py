"""Build a Blender-ready project folder from a digitized plan."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from .models import Project
from .project_io import load_project
from .transform import pixel_to_world


DEFAULT_WALL_THICKNESS_M = 0.12
DEFAULT_PROVISIONAL_MM_PER_PX = 9.0  # rough scan estimate; marked UNCALIBRATED


def export_blender_project(
    project: Project,
    project_dir: Path,
    output_dir: Path,
    *,
    wall_thickness_m: float = DEFAULT_WALL_THICKNESS_M,
    provisional_mm_per_px: float | None = None,
) -> Path:
    """
    Create a Blender project package:

      output_dir/
        README.md
        assets/          # meshes, dxf, svg, underlay
        scripts/         # Blender Python setup
        references/      # overlay / notes
        scene/           # .blend written when setup script is run
    """
    project_dir = Path(project_dir)
    output_dir = Path(output_dir)
    assets = output_dir / "assets"
    scripts = output_dir / "scripts"
    refs = output_dir / "references"
    scene = output_dir / "scene"
    for d in (assets, scripts, refs, scene):
        d.mkdir(parents=True, exist_ok=True)

    working = project
    scale_note = "calibrated"
    if not project.is_calibrated():
        scale = provisional_mm_per_px or DEFAULT_PROVISIONAL_MM_PER_PX
        working = _with_provisional_scale(project, scale)
        scale_note = (
            f"UNCALIBRATED provisional scale {scale:.4f} mm/px — "
            "re-export after apartment-plan calibrate for real dimensions"
        )

    walls_m = _wall_segments_metres(working)
    height_m = working.wall_height_mm / 1000.0
    mesh = build_wall_mesh(walls_m, height_m=height_m, thickness_m=wall_thickness_m)
    floor = build_floor_mesh(walls_m)

    write_obj(assets / "walls.obj", mesh, object_name="Walls", mtl_name="walls.mtl", material="WallPaint")
    write_mtl(assets / "walls.mtl", "WallPaint", Kd=(0.82, 0.78, 0.70))
    write_obj(assets / "floor.obj", floor, object_name="Floor", mtl_name="floor.mtl", material="FloorConcrete")
    write_mtl(assets / "floor.mtl", "FloorConcrete", Kd=(0.55, 0.55, 0.52))

    # Copy CAD + references
    exports = project_dir / "exports"
    for name in ("plan_UNCALIBRATED.dxf", "plan_calibrated.dxf", "plan_UNCALIBRATED.svg", "plan_calibrated.svg"):
        src = exports / name
        if src.is_file():
            shutil.copy2(src, assets / name)

    for name in ("source.png", "overlay.png", "project.json"):
        src = project_dir / name
        if src.is_file():
            dest = refs / name if name.endswith(".png") else assets / name
            if name == "source.png":
                shutil.copy2(src, assets / "underlay.png")
            shutil.copy2(src, dest if name.endswith(".png") else assets / name)

    meta = {
        "project_id": working.id,
        "calibrated": working.is_calibrated(),
        "scale_note": scale_note,
        "wall_height_m": height_m,
        "wall_thickness_m": wall_thickness_m,
        "wall_count": len(walls_m),
        "units": "metres",
        "assets": {
            "walls_obj": "assets/walls.obj",
            "floor_obj": "assets/floor.obj",
            "underlay": "assets/underlay.png",
        },
    }
    (output_dir / "project_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (assets / "project.json").write_text(
        Path(project_dir / "project.json").read_text(encoding="utf-8")
        if (project_dir / "project.json").is_file()
        else "{}",
        encoding="utf-8",
    )

    write_blender_setup_script(scripts / "setup_scene.py", meta)
    write_blender_readme(output_dir / "README.md", meta)
    write_import_guide(output_dir / "IMPORT_DXF.md")

    return output_dir


def export_from_project_dir(
    project_dir: Path,
    output_dir: Path | None = None,
    **kwargs,
) -> Path:
    project_dir = Path(project_dir)
    project = load_project(project_dir)
    if output_dir is None:
        output_dir = project_dir / "blender" / "apartment_demo"
    return export_blender_project(project, project_dir, Path(output_dir), **kwargs)


def _with_provisional_scale(project: Project, mm_per_px: float) -> Project:
    # Shallow copy calibration for export only
    project.calibration.scale_mm_per_px = float(mm_per_px)
    project.calibration.calibrated = False
    project.calibration.note = (
        f"UNCALIBRATED provisional export scale {mm_per_px:.4f} mm/px"
    )
    return project


def _wall_segments_metres(project: Project) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    h = project.source.image_height
    out = []
    for wall in project.active_walls():
        a = pixel_to_world(wall.start, project.calibration, h)
        b = pixel_to_world(wall.end, project.calibration, h)
        out.append(((a.x / 1000.0, a.y / 1000.0), (b.x / 1000.0, b.y / 1000.0)))
    return out


def build_wall_mesh(
    walls: list[tuple[tuple[float, float], tuple[float, float]]],
    *,
    height_m: float,
    thickness_m: float,
) -> dict:
    """Return {vertices: [(x,y,z)], faces: [(i,j,k,l)]} for vertical wall boxes."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    half = thickness_m / 2.0

    for (x1, y1), (x2, y2) in walls:
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-4:
            continue
        ux, uy = dx / length, dy / length
        px, py = -uy, ux  # perpendicular in XY (Blender: Z up)

        # Bottom rectangle corners
        c0 = (x1 + px * half, y1 + py * half, 0.0)
        c1 = (x1 - px * half, y1 - py * half, 0.0)
        c2 = (x2 - px * half, y2 - py * half, 0.0)
        c3 = (x2 + px * half, y2 + py * half, 0.0)
        # Top
        t0 = (c0[0], c0[1], height_m)
        t1 = (c1[0], c1[1], height_m)
        t2 = (c2[0], c2[1], height_m)
        t3 = (c3[0], c3[1], height_m)

        base = len(vertices)
        vertices.extend([c0, c1, c2, c3, t0, t1, t2, t3])
        # faces as quads (OBJ 1-based later)
        faces.extend(
            [
                (base, base + 1, base + 2, base + 3),  # bottom
                (base + 4, base + 7, base + 6, base + 5),  # top
                (base, base + 3, base + 7, base + 4),  # +perp
                (base + 1, base + 5, base + 6, base + 2),  # -perp
                (base, base + 4, base + 5, base + 1),  # start cap
                (base + 3, base + 2, base + 6, base + 7),  # end cap
            ]
        )
    return {"vertices": vertices, "faces": faces}


def build_floor_mesh(
    walls: list[tuple[tuple[float, float], tuple[float, float]]],
    pad: float = 0.3,
) -> dict:
    if not walls:
        verts = [(0, 0, 0), (5, 0, 0), (5, 5, 0), (0, 5, 0)]
        return {"vertices": verts, "faces": [(0, 1, 2, 3)]}
    xs, ys = [], []
    for a, b in walls:
        xs.extend([a[0], b[0]])
        ys.extend([a[1], b[1]])
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    z = -0.01
    verts = [
        (min_x, min_y, z),
        (max_x, min_y, z),
        (max_x, max_y, z),
        (min_x, max_y, z),
    ]
    return {"vertices": verts, "faces": [(0, 1, 2, 3)]}


def write_obj(
    path: Path,
    mesh: dict,
    *,
    object_name: str,
    mtl_name: str,
    material: str,
) -> None:
    path = Path(path)
    lines = [
        f"# Apartment plan digitizer — {object_name}",
        f"mtllib {mtl_name}",
        f"o {object_name}",
        f"usemtl {material}",
    ]
    for x, y, z in mesh["vertices"]:
        # Blender: X right, Y depth, Z up — our world already XY floor
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for face in mesh["faces"]:
        # OBJ is 1-based
        idx = " ".join(str(i + 1) for i in face)
        lines.append(f"f {idx}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mtl(path: Path, name: str, Kd: tuple[float, float, float]) -> None:
    path.write_text(
        "\n".join(
            [
                f"newmtl {name}",
                "Ns 8.000",
                "Ka 1.000 1.000 1.000",
                f"Kd {Kd[0]:.3f} {Kd[1]:.3f} {Kd[2]:.3f}",
                "Ks 0.050 0.050 0.050",
                "d 1.000",
                "illum 2",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_blender_setup_script(path: Path, meta: dict) -> None:
    """Blender 3.x/4.x Python: import assets, set units, save .blend."""
    calibrated = bool(meta["calibrated"])
    note = meta["scale_note"].replace("\\", "\\\\").replace('"', '\\"')
    script = f'''"""
Setup apartment demo scene in Blender.

Run from the blender/apartment_demo folder:

  blender --background --python scripts/setup_scene.py

Or in Blender: Scripting workspace → Open this file → Run Script
"""
from __future__ import annotations

from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SCENE_DIR = ROOT / "scene"
SCENE_DIR.mkdir(parents=True, exist_ok=True)
BLEND_PATH = SCENE_DIR / "apartment_demo.blend"

SCALE_NOTE = "{note}"
CALIBRATED = {str(calibrated)}


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


def ensure_collection(name: str):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def link_to_collection(obj, col) -> None:
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


def set_metric_units() -> None:
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"
    scene.render.engine = "CYCLES" if "CYCLES" in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys() else scene.render.engine


def import_obj(path: Path, collection_name: str):
    col = ensure_collection(collection_name)
    before = set(bpy.data.objects)
    # Blender 4.x uses wm.obj_import; 3.x uses import_scene.obj
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        bpy.ops.import_scene.obj(filepath=str(path))
    imported = [o for o in bpy.data.objects if o not in before]
    for obj in imported:
        link_to_collection(obj, col)
        obj.name = path.stem.capitalize()
    return imported


def add_underlay() -> None:
    underlay = ASSETS / "underlay.png"
    if not underlay.is_file():
        return
    col = ensure_collection("References")
    # Large empty image empty as reference in ortho top view
    bpy.ops.object.empty_add(type="IMAGE", location=(0, 0, -0.02))
    empty = bpy.context.active_object
    empty.name = "PlanUnderlay"
    try:
        img = bpy.data.images.load(str(underlay))
        empty.data = img
        empty.empty_display_size = 10.0
    except Exception:
        pass
    link_to_collection(empty, col)


def add_lights_camera(floor_obj) -> None:
    col = ensure_collection("SceneSetup")
    bpy.ops.object.light_add(type="AREA", location=(2.0, -2.0, 4.0))
    light = bpy.context.active_object
    light.name = "KeyLight"
    light.data.energy = 250.0
    light.data.size = 3.0
    link_to_collection(light, col)

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 6))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 2.0
    link_to_collection(sun, col)

    bpy.ops.object.camera_add(location=(6.0, -8.0, 5.5), rotation=(1.1, 0.0, 0.6))
    cam = bpy.context.active_object
    cam.name = "OverviewCamera"
    link_to_collection(cam, col)
    bpy.context.scene.camera = cam


def add_scale_warning() -> None:
    col = ensure_collection("Notes")
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 3.2))
    empty = bpy.context.active_object
    empty.name = "SCALE_NOTE"
    empty["scale_note"] = SCALE_NOTE
    empty["calibrated"] = CALIBRATED
    link_to_collection(empty, col)


def main() -> None:
    clear_scene()
    set_metric_units()
    ensure_collection("Walls")
    ensure_collection("Floor")
    ensure_collection("Furniture")
    ensure_collection("References")
    ensure_collection("Notes")
    ensure_collection("SceneSetup")

    walls = import_obj(ASSETS / "walls.obj", "Walls")
    floor = import_obj(ASSETS / "floor.obj", "Floor")
    add_underlay()
    add_lights_camera(floor[0] if floor else None)
    add_scale_warning()

    # Frame view
    for obj in bpy.data.objects:
        obj.select_set(True)
    if hasattr(bpy.ops.view3d, "camera_to_view_selected"):
        pass

    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    print(f"Saved Blender project: {{BLEND_PATH}}")
    print(f"Scale: {{SCALE_NOTE}}")


if __name__ == "__main__":
    main()
'''
    path.write_text(script, encoding="utf-8")


def write_blender_readme(path: Path, meta: dict) -> None:
    path.write_text(
        f"""# Apartment demo — Blender project

Ready-to-import 3D structure generated from the digitized floor plan.

- Units: **metres**
- Walls: `{meta['wall_count']}` extruded segments @ {meta['wall_height_m']} m high
- Scale: **{meta['scale_note']}**

## Fastest path (recommended)

1. Install [Blender](https://www.blender.org/download/) 3.6+ or 4.x.
2. From this folder run:

```bash
cd "$(dirname "$0")"
# macOS example:
/Applications/Blender.app/Contents/MacOS/Blender --background --python scripts/setup_scene.py
```

3. Open `scene/apartment_demo.blend`.

Or inside Blender: **Scripting** → Open `scripts/setup_scene.py` → **Run Script**.

## Manual import (no script)

1. File → New → General  
2. Scene Properties → Units → Metric, Unit Scale `1.0`, Length `Meters`  
3. File → Import → Wavefront (.obj) → `assets/walls.obj`  
4. File → Import → Wavefront (.obj) → `assets/floor.obj`  
5. Optional: import `assets/plan_*.dxf` via the DXF importer addon (see `IMPORT_DXF.md`)

## Folder layout

```
apartment_demo/
  assets/           walls.obj, floor.obj, underlay.png, DXF/SVG, project.json
  scripts/          setup_scene.py  (creates scene/apartment_demo.blend)
  references/       overlay.png, source.png
  scene/            apartment_demo.blend (after running the script)
  project_meta.json
  IMPORT_DXF.md
```

## Collections created by the setup script

| Collection   | Purpose                          |
|-------------|-----------------------------------|
| Walls       | Extruded wall meshes              |
| Floor       | Ground plane from wall bounds     |
| Furniture   | Empty — drop IKEA/kitbash assets  |
| References  | Plan underlay image               |
| Notes       | Scale calibration warning         |
| SceneSetup  | Camera + lights                   |

## Real scale

This export is only trustworthy after calibration:

```bash
apartment-plan review
# click two ends of a known wall (Living 400 on this plan = 4000 mm)
apartment-plan blender-export
```

Then re-run `scripts/setup_scene.py`.
""",
        encoding="utf-8",
    )


def write_import_guide(path: Path) -> None:
    path.write_text(
        """# Import DXF into Blender (manual)

Blender does not enable the DXF importer by default.

1. Edit → Preferences → Add-ons  
2. Search **DXF** → enable **Import-Export: AutoCAD DXF**  
   (In Blender 4.2+ some add-ons are on [extensions.blender.org](https://extensions.blender.org).)  
3. File → Import → AutoCAD DXF  
4. Choose `assets/plan_calibrated.dxf` (or `plan_UNCALIBRATED.dxf`)  
5. After import, select curves/meshes → Object → Convert → Mesh  
6. Extrude in Edit Mode along Z by wall height (e.g. 2.7 m)

**Prefer `walls.obj` + `setup_scene.py`** — walls are already extruded and metric.
""",
        encoding="utf-8",
    )
