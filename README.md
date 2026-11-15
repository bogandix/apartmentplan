# Apartment Plan Digitizer

Local, open-source tool that turns a scanned 2D apartment plan (PDF or image)
into a correctable, real-scale floor plan (DXF/SVG) and a basic 3D preview.
It is meant as the foundation for interior-layout work in CAD tools, Blender or
SketchUp.

**The tool never claims a scan is measured.** A plan is `UNCALIBRATED` until you
have checked the trace and entered one real wall length. Every output — the
review page, the overlay image, the DXF, the SVG, the 3D preview and the file
names — carries the current scale state.

| Scale state | Meaning | Export file |
|-------------|---------|-------------|
| `UNCALIBRATED` | Automatic draft in scan pixels. Not real scale. | `plan_UNCALIBRATED.dxf/.svg` (unitless) |
| `PROVISIONAL` | Scale taken from a dimension printed on the plan. Millimetres, but not verified. | `plan_PROVISIONAL.dxf/.svg` |
| `calibrated` | Scale from a wall you measured yourself. | `plan_calibrated.dxf/.svg` |

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional, for text suggestions and automatic sheet orientation:
[Tesseract](https://github.com/tesseract-ocr/tesseract) (`brew install tesseract`
on macOS, `apt install tesseract-ocr` on Debian/Ubuntu). Without it the tool
still works; pass `--rotate 90/180/270` if the sheet is sideways.

## Workflow

1. **Put one plan in `input/`** — PDF, PNG, JPG/JPEG or TIFF. The file is only
   read, never changed.
2. **Process it**

   ```bash
   apartment-plan process
   ```

   This writes `projects/<plan name>/`:

   | File | What it is |
   |------|-----------|
   | `source.png` | The scan, turned upright and deskewed |
   | `overlay.png` | The automatic draft drawn over the scan |
   | `project.json` | Versioned, editable geometry + scale + edit log |
   | `exports/plan_UNCALIBRATED.*` | Draft exports in pixel units |

3. **Review, correct, calibrate**

   ```bash
   apartment-plan review        # http://127.0.0.1:8765
   ```

   - The draft sits on top of the scan; scroll to zoom, drag to pan.
   - Green walls are confident, orange need a look, red are uncertain (often
     furniture). *Remove all uncertain walls* clears the red ones in one go.
   - Select a line to delete it or drag its endpoints. Draw missing walls,
     doors and windows with the tool buttons (Shift keeps lines straight).
   - *Recompute rooms* outlines every area enclosed by walls and openings.
   - **Set the scale:** choose *Measure*, click both ends of a wall, type its
     real length in m, cm or mm, and press *Set scale*. If you only have a
     number printed on the plan, tick "Read from a dimension printed on the
     plan" — the result is then marked `PROVISIONAL`.

4. **Export and inspect** — DXF and SVG are rewritten after every change and
   can be downloaded from the page; the 3D preview on the same page is built
   from the corrected geometry.

Reprocessing a plan that already has review work is refused unless you pass
`--force`.

## Commands

| Command | Purpose |
|---------|---------|
| `apartment-plan process [--input FILE] [--page N] [--dpi 200] [--rotate auto\|0\|90\|180\|270] [--no-ocr] [--force]` | Build the automatic draft |
| `apartment-plan review [--project DIR] [--port 8765]` | Local correction page + 3D preview |
| `apartment-plan calibrate --m 4.2 --x1 … --y1 … --x2 … --y2 … [--printed]` | Set the scale without the page (`--cm` / `--mm` also accepted; coordinates are pixels of `source.png`) |
| `apartment-plan export` | Rewrite DXF/SVG/overlay from `project.json` |
| `apartment-plan blender-export` | Build `blender/apartment_demo/` (OBJ walls/floor + setup script) |

## Outputs and units

- **DXF** (`ezdxf`, R2010): millimetres, `$INSUNITS = 4`, y up, origin at the
  bottom-left of the plan. Layers: `WALLS` (centre-lines — the geometry to
  edit), `WALL_THICKNESS_ESTIMATE` (outlines from the scan, unverified),
  `OPENINGS`, `ROOMS` (with area), `TEXT_OCR`, `CALIBRATION`, `NOTES`.
  An uncalibrated DXF is declared unitless and says so in `NOTES`.
- **SVG**: 1 user unit = 1 mm, `width`/`height` in mm, each wall carries
  `data-length-mm`. Uncalibrated SVGs are in px with a red banner.
- **3D preview**: metres once a scale exists; before that it shows proportions
  only and says so.
- Displayed lengths and areas are in metres / m².

## What is and is not inferred

The draft is a set of suggestions. Wall thickness is measured on the scan and
exported as an estimate; a gap between two walls is proposed as an "opening"
and you decide whether it is a door or a window; room names come from OCR and
are marked with `(?)` until you confirm them. Dimensions read by OCR are shown
as hints and never applied automatically.

Detection expects walls drawn as filled or hatched bands. Plans drawn with
thin single lines will need more manual drawing in the review step.
Perspective correction (photos taken at an angle) is not implemented; use a
flatbed scan.

## Privacy

Everything runs on your machine. The review page is served from `127.0.0.1`
and loads no external resources (Three.js is bundled in
`src/apartment_plan/web/vendor/`, MIT licence). No plan data leaves the
computer.

## Blender

```bash
apartment-plan blender-export
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python blender/apartment_demo/scripts/setup_scene.py
# then open blender/apartment_demo/scene/apartment_demo.blend
```

Without the terminal: open Blender → **Scripting** tab → **Text → Open** →
`blender/apartment_demo/scripts/setup_scene.py` → **Run Script** (▶).

Manual fallback: File → Import → Wavefront (.obj) →
`blender/apartment_demo/assets/walls.obj` with **Forward Axis = Y, Up Axis = Z**
(the meshes are Z-up). For DXF see `blender/apartment_demo/IMPORT_DXF.md`.

## Development

```bash
pytest
```

Tests cover PDF/image input handling, scale calibration, pixel↔world
conversion, DXF/SVG dimensions (read back from the files), the automatic
draft on a synthetic plan, and the review API. Progress notes live in
`IMPLEMENTATION_TRACK.md`.

## Stack and licences

Python · OpenCV (Apache-2.0) · PyMuPDF (AGPL-3.0) · ezdxf (MIT) ·
pytesseract/Tesseract (Apache-2.0) · Flask (BSD-3) · Three.js (MIT).
PyMuPDF's AGPL matters if you redistribute this tool; for personal local use
it imposes nothing.
