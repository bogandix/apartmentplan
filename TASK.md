# Apartment Plan Digitizer — Technical Task

## Goal

Build a local, open-source tool that turns a scanned 2D apartment plan into a
correctable, real-scale editable floor plan and a basic 3D preview. The result
will be a foundation for a personal interior-design companion: documenting the
apartment, trying furniture layouts, and eventually creating a navigable 3D
tour.

The tool must not claim that a scan has been accurately measured or understood
until the user has checked the trace and supplied a real-world measurement.

## User workflow

1. Put one plan file in `input/`. Accept PDF documents and common raster images
   (PNG, JPG/JPEG, TIFF).
2. Run the local processing command.
3. Review the generated automatic draft and correct walls, openings, and room
   boundaries.
4. Enter a known wall length in metric units to calibrate the plan.
5. Export an editable 2D drawing and inspect the basic 3D preview.

Scanned plans without printed dimensions are supported. In that case, scale is
unknown until the user enters a measured wall length. Clearly label uncalibrated
outputs so they cannot be mistaken for real-scale drawings.

## MVP scope

- Process one input plan at a time from `input/`.
- Convert PDF pages to images and normalize image inputs for processing.
- Correct rotation and perspective where practical; retain the original input
  unchanged.
- Create an automatic draft of visible plan geometry (at minimum, wall-like
  lines and room outlines) and extract readable text/dimensions when possible.
- Provide a simple local correction/review step. The user must be able to
  adjust the scale and edit or remove detected geometry before export.
- Export:
  - **DXF** as the primary editable CAD interchange format.
  - **SVG** as a convenient 2D preview and secondary editable format.
  - A basic browser-based 3D preview generated from the corrected geometry.
- Use metric units (millimetres for drawing coordinates; metres for displayed
  dimensions and 3D preview).
- Keep processing local; do not upload plans or extracted data to a service.

## Suggested open-source implementation

- **Python CLI and image processing:** Python, OpenCV, and PyMuPDF for image
  cleanup and PDF page rendering.
- **Text extraction:** Tesseract OCR, with OCR results treated as suggestions
  that the user can correct. Preserve the source image for visual comparison.
- **Editable CAD output:** `ezdxf` for DXF generation; generate SVG directly
  from the normalized vector geometry.
- **3D preview:** a small local web UI using Three.js. Convert the reviewed
  floor outline and wall segments into simple wall meshes with a configurable
  default height. The preview is illustrative until dimensions, wall height,
  openings, and geometry are verified.
- Keep components behind clear interfaces so the 2D processing pipeline can be
  used independently of the 3D preview. Avoid requiring proprietary software
  or paid APIs.

These are suggested tools, not a mandate to adopt every component at once.
Confirm current platform support and license compatibility when selecting
specific versions.

## Data and coordinate model

- Use a single 2D world coordinate system for all detected and corrected
  geometry. Keep image/pixel coordinates separate from world coordinates.
- Store geometry in an explicit, versioned project file so a user can reopen
  and continue editing without reprocessing the original scan.
- Track the source image/PDF page, pixel-to-world transform, calibration
  measurement, units, and any user edits.
- Represent walls as editable segments or polylines. Keep room boundaries,
  doors, windows, text labels, and furniture as distinct entity types when
  available.
- Do not infer exact wall thickness, door swing, room purpose, or dimensions
  solely from OCR or image detection. Mark uncertain detections for review.

## Validation and error handling

- Reject unsupported files and report actionable errors (including the
  supported file types).
- Never silently treat pixels as millimetres or metres.
- Validate the calibration measurement as a positive finite length and identify
  the endpoints/segment to which it applies.
- Preserve the original source and write generated outputs to a separate
  project/output location.
- Show the detected draft overlaid on the source scan so alignment errors are
  visible before export.
- Warn when the source image is blurry, clipped, skewed, or lacks enough
  geometry for a reliable automatic draft.
- Ensure DXF/SVG exports use the calibrated coordinate system and that opening
  the DXF in a common CAD viewer preserves the intended dimensions.

## Acceptance criteria

1. A user can process a PDF or a PNG/JPG scan placed in `input/` using
   documented local commands.
2. The tool creates a reviewable draft with the original scan visible beneath
   or alongside detected geometry.
3. A user can correct the draft and calibrate it using one measured wall.
4. The calibrated drawing exports to DXF and SVG with metric dimensions.
5. The same reviewed plan produces a basic Three.js 3D preview with walls
   derived from the corrected geometry.
6. Without calibration, the UI and exports clearly communicate that the plan
   is not yet verified at real scale.
7. Tests cover PDF/image input handling, scale calibration, coordinate
   conversion, and export dimensions.
8. The workflow runs locally and does not transmit the plan to external
   services.

## Out of scope for the first version

- Fully automatic, survey-grade conversion from arbitrary scans.
- Automatic guarantee of room names, measurements, wall thicknesses, or
  structural details.
- Photorealistic rendering, furniture recommendations, cost estimates, or
  product search.
- Full-featured CAD editing or a production-ready 3D walkthrough.

These can follow once the 2D geometry and scale workflow are reliable. Future
work may add editable furniture assets, saved layout alternatives, Blender
interchange, and a more complete Three.js walkthrough.
