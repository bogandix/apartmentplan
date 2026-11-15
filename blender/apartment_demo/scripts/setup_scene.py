"""
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

SCALE_NOTE = "PROVISIONAL scale from a dimension printed on the plan: 4.775 m over 510.5 px (1300,433)-(1300,944) px = 9.3536 mm/px. Not verified - measure a real wall to confirm."
CALIBRATED = True


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
    print(f"Saved Blender project: {BLEND_PATH}")
    print(f"Scale: {SCALE_NOTE}")


if __name__ == "__main__":
    main()
