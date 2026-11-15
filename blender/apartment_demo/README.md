# Apartment demo — Blender project

Ready-to-import 3D structure generated from the digitized floor plan.

- Units: **metres**
- Walls: `24` extruded segments @ 2.7 m high
- Scale: **PROVISIONAL scale from a dimension printed on the plan: 4.775 m over 510.5 px (1300,433)-(1300,944) px = 9.3536 mm/px. Not verified - measure a real wall to confirm.**

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
3. File → Import → Wavefront (.obj) → `assets/walls.obj`. In the import
   options on the right set **Forward Axis = Y** and **Up Axis = Z**
   (the files are Z-up; with Blender's default Y-up the walls lie on their side).
4. Same for `assets/floor.obj`.  
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
