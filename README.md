# Apartment Plan Digitizer

Local open-source tool that turns a scanned 2D apartment plan (PDF or image)
into a correctable, real-scale editable floor plan (DXF/SVG) and a basic 3D
preview. Designed as a foundation for interior layout work in Blender, SketchUp,
or other CAD tools.

**Nothing is treated as real scale until you calibrate with one measured wall.**

## Quick start

```bash
cd /Users/bogdan/aprtmentplan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# Put your plan in input/
apartment-plan process

# Review / correct / calibrate / 3D preview
apartment-plan review
# → http://127.0.0.1:8765
```

Optional system dependency for OCR suggestions: [Tesseract](https://github.com/tesseract-ocr/tesseract)
(`brew install tesseract` on macOS). OCR is best-effort and never trusted as ground truth.

## Workflow

1. Place one PDF or PNG/JPG/TIFF in `input/`.
2. Run `apartment-plan process` — creates `projects/<id>/` with:
   - `source.png` — normalized scan
   - `overlay.png` — detection draft on top of the scan
   - `project.json` — versioned editable geometry
   - `exports/plan_UNCALIBRATED.dxf` / `.svg`
3. Open `apartment-plan review`:
   - Check walls overlaid on the scan
   - Remove bad walls or draw missing ones
   - Click two ends of a known wall, enter length in **mm**, Calibrate
4. Import the calibrated DXF into LibreCAD, AutoCAD, SketchUp, Blender (via DXF/SVG), etc.

## CLI

| Command | Purpose |
|--------|---------|
| `apartment-plan process` | Detect draft from `input/` |
| `apartment-plan review` | Local correction UI + Three.js preview |
| `apartment-plan calibrate --mm 3500 --x1 … --y1 … --x2 … --y2 …` | CLI scale set |
| `apartment-plan export` | Re-write DXF/SVG |

## Units

- Drawing coordinates: **millimetres** after calibration
- 3D preview: **metres**
- Uncalibrated exports are clearly labelled `UNCALIBRATED` so they cannot be mistaken for survey drawings

## Stack

- Python, OpenCV, PyMuPDF — ingest & geometry draft
- Tesseract / pytesseract — optional text suggestions
- ezdxf — DXF export
- Flask + Three.js — local review & 3D wall preview

All processing stays on your machine.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

## Out of scope (v0.1)

Photoreal furniture catalogs, automatic cost estimates, and production walkthroughs.
Those can build on a calibrated DXF once the 2D geometry is trustworthy.
