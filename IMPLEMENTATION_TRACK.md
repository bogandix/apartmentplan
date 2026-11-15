# Implementation Track

Append-only status log for the Apartment Plan Digitizer (see `TASK.md`).
Newest entries go at the bottom. Each entry records what was done, what was
verified, and what is still open.

---

## 2026-11-15 11:13 — `54f734c` Initial demo

- Python package `apartment_plan` with CLI (`process`, `review`, `calibrate`,
  `export`), PDF/image ingest (PyMuPDF/OpenCV), Hough-based wall draft,
  optional Tesseract OCR, DXF (ezdxf) and SVG export, Flask review UI with a
  Three.js preview, versioned `project.json`.
- Tests: ingest rejection, calibration maths, export smoke test.

## 2026-11-15 11:17 — `ee131a8` Demo project outputs

- Committed `projects/5dea7491-…/` (source, overlay, project.json, uncalibrated
  DXF/SVG) produced from `input/IMG_20261115_0002.pdf`.

## 2026-11-15 11:22 — `5e4ad5d` Blender export

- `apartment-plan blender-export`: OBJ walls/floor, setup script, import guide.

---

## 2026-11-15 — Audit against `TASK.md` (before this round of work)

Input checked: `input/IMG_20261115_0002.pdf` — one page, a 300 dpi flatbed scan
(2550×3504 px) of a three-room apartment plan. The sheet is scanned sideways
(text reads bottom-to-top), has a small key plan and a notary stamp in one
corner, a title block, and printed dimensions in centimetres (815, 400, 295,
444, …) plus room areas (e.g. `LIVING S=19.04 mp`).

Result of the existing pipeline on that file (80 "walls", 1 "room", 0 texts):

| Area | Finding |
|------|---------|
| Wall draft | Hough lines traced both edges of thick walls, furniture, the page edge, the key plan and the stamp. Not usable as a draft. |
| Rotation | Sheet left sideways; no orientation correction. OCR returned nothing. |
| Rooms | One contour, not a room. |
| Openings | Never detected, not editable in the UI. |
| Review UI | Add/remove wall and calibrate only; no moving endpoints, no zoom, no room/opening editing; calibration in mm only. |
| 3D preview | Three.js loaded from a CDN (needs internet); fixed wall thickness. |
| Uncalibrated export | Labelled, but the DXF still declared millimetre units. |
| Project file | No log of user edits; project folder named by random UUID. |
| Tests | No coordinate round-trip, no DXF dimension read-back, no review API test. |

Plan for this round: orientation + plan-region isolation, filled-wall detector,
opening and room suggestions, richer review UI, honest scale states in exports,
broader tests, then process the real input and commit each stable step.

---

## 2026-11-15 — v0.2.0 code: pipeline, review page and tests rebuilt

Status: **done, tests green (66 passed)**.

Input handling
- One plan at a time: more than one file in `input/` is an error that names the
  files. Unsupported type, damaged image/PDF, password-protected PDF and
  out-of-range page each give an actionable message listing supported types.
- The original is only read; its SHA-256 is stored in `project.json`.
- Project folder is named after the input file (`projects/<stem>/`).
  Reprocessing a project that has edits or a scale needs `--force`.

Normalization
- Sheet orientation: OCR is run at 0/90/180/270° and the turn with clearly the
  most readable words wins (`--rotate` overrides). Tesseract's own OSD was
  tried first and rejected: confidence 1.2 on this scan.
- Residual skew measured on long lines and removed; strong skew warns.
- Not done: perspective correction for photographed plans (flatbed scans only).

Automatic draft (`detect.py`)
- Filled/hatched ink mask → largest cluster = the plan; key plan, stamp, title
  block and page edge are ignored (and reported as a warning).
- Each ink pixel goes to the direction of its longer straight run, giving
  horizontal and vertical bands; each band becomes a centre-line with a pixel
  thickness. Bands too thick to be a wall (filled furniture) are dropped.
- Corners are joined; a gap between collinear walls becomes a low-confidence
  "opening" (door/window left for the user); enclosed areas become room
  outlines along the inner wall faces.
- Confidence: green = long and joined, orange = short, red = free-standing
  (often furniture). Warnings for blank page, too little geometry, clipped plan.

Scale
- Three states: `UNCALIBRATED`, `PROVISIONAL` (printed dimension), `calibrated`
  (measured wall). Calibration stores the two pixel endpoints, length, method.
- Length must be a positive finite number; endpoints must be finite and at
  least 5 px apart.

Exports
- DXF: mm + `$INSUNITS=4` when a scale exists, unitless + warning note when
  not. Layers for walls, thickness estimate, openings, rooms (+area), OCR text,
  calibration segment, notes. Origin at the plan's bottom-left, y up.
- SVG: real mm size, per-wall `data-length-mm`, scale-state banner.
- File name carries the state; files from an earlier state are deleted.

Review page
- Zoom/pan, select, drag endpoints (snap + Shift for straight), draw wall /
  door / window, delete + undo, "remove all uncertain walls", recompute rooms,
  rename rooms, layer toggles, OCR dimension hints.
- Scale entry in m/cm/mm with "measured" vs "printed dimension" choice.
- 3D preview from the same geometry (wall thickness from the scan, floors from
  rooms, door/window markers). Three.js r160 is bundled — no CDN.
- Every change is appended to `project.json → edits`.

Tests (`pytest`, 66)
- `test_ingest.py` PNG/JPG/TIFF/PDF loading, DPI, errors, one-file rule,
  original untouched, blur warning, real PDF (skipped if absent).
- `test_transform.py` length validation, calibration, round-trip, v1 file load.
- `test_detect.py` synthetic plan: wall centre-lines, thickness, furniture and
  key plan ignored, door gap, rooms, skew, clipping, blank page.
- `test_export.py` DXF/SVG read back: wall lengths in mm, units, labels,
  file names per state.
- `test_review_api.py` edit/undo, invalid calibration rejected, 3D scene in
  metres, no external URLs in the page, reprocess guard.

---

## 2026-11-15 — Run 1 on `input/IMG_20261115_0002.pdf`: automatic draft

Status: **draft only — UNCALIBRATED, not reviewed**. Output in
`projects/IMG_20261115_0002/` (replaces the old `projects/5dea7491-…` demo).

Command: `apartment-plan process`

- Sheet detected as sideways and rotated 90° clockwise; no skew.
- 5 smaller drawings/marks outside the plan ignored (key plan, stamp, …).
- 46 wall candidates, 5 opening suggestions, 1 room outline, 32 OCR texts
  (OCR read 815, 295, 400, 220, 355 among the printed dimensions).
- What the draft gets right: outer structural walls, balcony parapet, the
  dormitor/living, living/kitchen and kitchen/birou partitions.
- What it gets wrong (expected, left for review): about 20 red "uncertain"
  bands are furniture, door leaves and fixtures; door and window gaps are not
  closed, so only the balcony is outlined as a room; the top wall above the
  kitchen counter is cut short where the counter is drawn against it.
- Exports are `plan_UNCALIBRATED.dxf/.svg` in pixel units.

---

## 2026-11-15 — Run 2 on `input/IMG_20261115_0002.pdf`: reviewed trace, provisional scale

Status: **trace reviewed against the scan; scale PROVISIONAL (not yet measured
on site)**. Outputs: `projects/IMG_20261115_0002/` and `blender/apartment_demo/`.

Review (done through the review API, 43 logged edits in `project.json`)
- Removed 20 uncertain bands plus 8 more that were furniture, fixtures or door
  leaves; removed 3 false opening suggestions.
- Extended/trimmed 5 walls (top wall over the kitchen counter, bottom wall,
  both bathroom walls); added 6 short walls around the hall, bathrooms and the
  shaft next to the bedroom door.
- Marked 4 windows and 6 doors (entrance, dormitor, bucătărie, birou, baie 1,
  baie 2). Recomputed rooms: 7 enclosed areas, named from the printed labels.
- Result: 24 walls, 10 openings, 7 rooms. Living and hall are one open space
  on the plan, so they are one room outline.

Scale
- Nobody has measured a real wall yet, so the plan is **not** marked
  calibrated. The printed living-room depth (477.5 cm, between the inner wall
  faces) was used instead: 510.5 px → 9.3536 mm/px, method `printed`.
- Cross-check of that scale against other printed numbers:

  | Printed on plan | From the trace | Difference |
  |-----------------|----------------|------------|
  | Living width 400 cm | 398.9 cm | −0.3 % |
  | Birou width 295 cm | 295.1 cm | 0.0 % |
  | Bucătărie width 220 cm | 217.9 cm | −0.9 % |
  | Dormitor width 295 cm | 290.4 cm | −1.5 % |
  | Balcon length 815 cm | 817.5 cm | +0.3 % |
  | Living + hol 23.12 m² | 23.19 m² | +0.3 % |
  | Dormitor 13.10 m² | 12.99 m² | −0.8 % |
  | Birou 10.33 m² | 10.52 m² | +1.8 % |
  | Bucătărie 7.70 m² | 7.73 m² | +0.4 % |
  | Baie 1 5.06 m² | 4.64 m² | −8.3 % |
  | Baie 2 3.71 m² | 3.48 m² | −6.2 % |
  | Balcon 8.56 m² | 7.75 m² | −9.5 % |

  Lengths agree within 1.5 %. The two bathrooms and the balcony come out
  6–10 % small: their outlines follow the estimated wall thickness, which is
  too generous around the bathrooms, and the balcony is measured inside the
  parapet. Wall thickness stays an estimate until checked on site.

Exports checked
- `plan_PROVISIONAL.dxf`: `$INSUNITS = 4`, 24 wall centre-lines, extent
  12.82 × 7.84 m, ezdxf audit reports 0 errors, PROVISIONAL warning on the
  `NOTES` layer.
- `plan_PROVISIONAL.svg`: 14.36 × 10.11 m page in mm; rendered and inspected.
  Styling switched from a CSS block to inline attributes after one renderer
  ignored the CSS and drew the rooms solid black.
- Review page and 3D preview opened in Chrome: scan + trace, room areas,
  PROVISIONAL badge and the extruded walls all display; no console errors.
- Blender package regenerated at the same scale (24 walls).

Open items
- **Measure one real wall** and enter it in the review page to move from
  PROVISIONAL to calibrated. Until then treat every dimension as approximate.
- Balcony parapet is extruded to full wall height in 3D; openings are shown as
  markers, not cut out of the walls.
- Wall thickness near the bathrooms should be checked on site.
- Vertical dimension text (444, 350, 477.5) is not read by OCR.
- Perspective correction for photographed plans is not implemented.
- The live Blender `.blend` build was not run in this round (Blender was not
  invoked); only the OBJ/script package was regenerated.

---

## 2026-11-15 — Blender package fixes

Status: **fixed in code; not yet run inside Blender** (Blender is not installed
on this machine).

- OBJ import axes: the meshes are written Z-up, but Blender's OBJ importer
  defaults to Y-up, so walls would have imported lying on their side. The
  setup script now passes `forward_axis="Y", up_axis="Z"` (3.x:
  `axis_forward/axis_up`); manual-import instructions say the same.
- The scan underlay is now placed and sized at plan scale (21.85 m wide,
  centred at 3.98, 2.71 m) so it sits under the walls instead of a fixed 10 m
  square at the origin.
- Camera and lights are placed from the plan extent; the camera tracks the
  plan centre.
- The script also works when run from Blender's Text Editor, not only with
  `blender --python`.
- `project_meta.json` records the scale state (`PROVISIONAL` for this plan).
