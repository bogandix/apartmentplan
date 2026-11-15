# Import DXF into Blender (manual)

Blender does not enable the DXF importer by default.

1. Edit → Preferences → Add-ons  
2. Search **DXF** → enable **Import-Export: AutoCAD DXF**  
   (In Blender 4.2+ some add-ons are on [extensions.blender.org](https://extensions.blender.org).)  
3. File → Import → AutoCAD DXF  
4. Choose `assets/plan_calibrated.dxf` (or `plan_UNCALIBRATED.dxf`)  
5. After import, select curves/meshes → Object → Convert → Mesh  
6. Extrude in Edit Mode along Z by wall height (e.g. 2.7 m)

**Prefer `walls.obj` + `setup_scene.py`** — walls are already extruded and metric.
