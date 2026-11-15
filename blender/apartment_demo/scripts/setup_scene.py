"""
Setup apartment demo scene in Blender.

Run from the blender/apartment_demo folder:

  blender --background --python scripts/setup_scene.py

Or in Blender: Scripting workspace → Open this file → Run Script
"""
from __future__ import annotations

from pathlib import Path
import bpy

def _script_file() -> Path:
    """Works both with `blender --python` and when run from Blender's Text Editor."""
    here = Path(__file__)
    if here.is_file():
        return here.resolve()
    for text in bpy.data.texts:
        if text.filepath:
            candidate = Path(bpy.path.abspath(text.filepath))
            if candidate.name == "setup_scene.py" and candidate.is_file():
                return candidate.resolve()
    raise RuntimeError("Open scripts/setup_scene.py from disk (Text > Open) before running it.")


ROOT = _script_file().parents[1]
ASSETS = ROOT / "assets"
SCENE_DIR = ROOT / "scene"
SCENE_DIR.mkdir(parents=True, exist_ok=True)
BLEND_PATH = SCENE_DIR / "apartment_demo.blend"

SCALE_NOTE = "PROVISIONAL scale from a dimension printed on the plan: 4.775 m over 510.5 px (1300,433)-(1300,944) px = 9.3536 mm/px. Not verified - measure a real wall to confirm."
CALIBRATED = True
SCALE_STATE = "PROVISIONAL"
UNDERLAY_CENTER = (3.9846, 2.7125)
UNDERLAY_SIZE = 21.8500
PLAN_EXTENT = (0.1964, 0.1730, 13.0155, 8.0160)  # min x, min y, max x, max y (m)


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
        # Our OBJ files are Z-up (Blender's own convention), not the OBJ default Y-up
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    else:
        bpy.ops.import_scene.obj(filepath=str(path), axis_forward="Y", axis_up="Z")
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
    bpy.ops.object.empty_add(type="IMAGE", location=(UNDERLAY_CENTER[0], UNDERLAY_CENTER[1], -0.02))
    empty = bpy.context.active_object
    empty.name = "PlanUnderlay"
    try:
        img = bpy.data.images.load(str(underlay))
        empty.data = img
        empty.empty_display_size = UNDERLAY_SIZE  # scan drawn at plan scale, under the walls
    except Exception:
        pass
    link_to_collection(empty, col)


def add_lights_camera(floor_obj) -> None:
    col = ensure_collection("SceneSetup")
    x0, y0, x1, y1 = PLAN_EXTENT
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    span = max(x1 - x0, y1 - y0, 1.0)

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(cx, cy, 0.0))
    target = bpy.context.active_object
    target.name = "PlanCentre"
    link_to_collection(target, col)

    bpy.ops.object.light_add(type="AREA", location=(cx, cy, 6.0))
    light = bpy.context.active_object
    light.name = "KeyLight"
    light.data.energy = 60.0 * span * span
    light.data.size = span
    link_to_collection(light, col)

    bpy.ops.object.light_add(type="SUN", location=(cx, cy, 10.0), rotation=(0.6, 0.2, 0.8))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 2.0
    link_to_collection(sun, col)

    # Three-quarter view from the south-east, always aimed at the plan centre
    bpy.ops.object.camera_add(location=(cx + 0.35 * span, cy - 0.95 * span, 0.9 * span))
    cam = bpy.context.active_object
    cam.name = "OverviewCamera"
    track = cam.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    link_to_collection(cam, col)
    bpy.context.scene.camera = cam


def add_scale_warning() -> None:
    col = ensure_collection("Notes")
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 3.2))
    empty = bpy.context.active_object
    empty.name = "SCALE_NOTE"
    empty["scale_note"] = SCALE_NOTE
    empty["calibrated"] = CALIBRATED
    empty["scale_state"] = SCALE_STATE
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
    print(f"Saved Blender project: {BLEND_PATH}")
    print(f"Scale: {SCALE_NOTE}")


if __name__ == "__main__":
    main()
