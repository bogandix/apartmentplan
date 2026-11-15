"""Versioned project data model for apartment plan digitization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


PROJECT_SCHEMA_VERSION = 2


class EntityType(str, Enum):
    WALL = "wall"
    ROOM = "room"
    DOOR = "door"
    WINDOW = "window"
    OPENING = "opening"  # gap in a wall; door/window not yet decided
    TEXT = "text"
    FURNITURE = "furniture"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    USER = "user"


@dataclass
class Point2D:
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Segment:
    id: str
    entity_type: EntityType
    start: Point2D
    end: Point2D
    confidence: Confidence = Confidence.MEDIUM
    thickness_mm: float | None = None
    # Thickness measured on the scan (pixels). An estimate for review, not a survey value.
    thickness_px: float | None = None
    label: str | None = None
    source: str = "auto"  # auto | user
    removed: bool = False

    def length_world(self) -> float:
        dx = self.end.x - self.start.x
        dy = self.end.y - self.start.y
        return (dx * dx + dy * dy) ** 0.5


@dataclass
class Polyline:
    id: str
    entity_type: EntityType
    points: list[Point2D]
    closed: bool = True
    confidence: Confidence = Confidence.MEDIUM
    label: str | None = None
    source: str = "auto"
    removed: bool = False


@dataclass
class TextLabel:
    id: str
    text: str
    position: Point2D
    confidence: Confidence = Confidence.LOW
    source: str = "ocr"
    removed: bool = False
    width: float = 0.0
    height: float = 0.0
    # "dimension" when the text looks like a printed length, else "label"
    kind: str = "label"


@dataclass
class Calibration:
    """Maps pixel coordinates to world millimetres via one measured segment."""

    segment_id: str | None = None
    pixel_start: Point2D | None = None
    pixel_end: Point2D | None = None
    measured_mm: float | None = None
    # world_mm = pixel * scale + offset; y is flipped so CAD Y grows upward
    scale_mm_per_px: float | None = None
    origin_px: Point2D = field(default_factory=lambda: Point2D(0.0, 0.0))
    flip_y: bool = True
    calibrated: bool = False
    # "measured"  — the user measured a real wall (trusted scale)
    # "printed"   — taken from a dimension printed on the plan (provisional)
    method: str | None = None
    note: str = "UNCALIBRATED — not real scale until a measured wall length is set"


@dataclass
class SourceInfo:
    original_path: str
    page_index: int = 0
    image_width: int = 0
    image_height: int = 0
    rendered_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    # How the normalized image was derived from the original (which is never modified)
    rotation_deg: int = 0
    skew_deg: float = 0.0
    dpi: int | None = None
    # Plan region inside the normalized image: [x0, y0, x1, y1] in pixels
    plan_bbox: list[float] | None = None
    original_sha256: str | None = None


@dataclass
class Project:
    id: str
    schema_version: int
    source: SourceInfo
    calibration: Calibration
    walls: list[Segment] = field(default_factory=list)
    rooms: list[Polyline] = field(default_factory=list)
    openings: list[Segment] = field(default_factory=list)
    texts: list[TextLabel] = field(default_factory=list)
    wall_height_mm: float = 2700.0
    units_display: str = "m"
    drawing_units: str = "mm"
    # Chronological log of user edits (action, entity id, timestamp)
    edits: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def new(source: SourceInfo) -> "Project":
        return Project(
            id=str(uuid4()),
            schema_version=PROJECT_SCHEMA_VERSION,
            source=source,
            calibration=Calibration(),
        )

    def active_walls(self) -> list[Segment]:
        return [w for w in self.walls if not w.removed]

    def active_rooms(self) -> list[Polyline]:
        return [r for r in self.rooms if not r.removed]

    def active_openings(self) -> list[Segment]:
        return [o for o in self.openings if not o.removed]

    def active_texts(self) -> list[TextLabel]:
        return [t for t in self.texts if not t.removed]

    def is_calibrated(self) -> bool:
        return bool(self.calibration.calibrated and self.calibration.scale_mm_per_px)

    def is_verified_scale(self) -> bool:
        """True only when the scale comes from a wall the user measured."""
        return self.is_calibrated() and self.calibration.method == "measured"

    def scale_state(self) -> str:
        if not self.is_calibrated():
            return "UNCALIBRATED"
        return "calibrated" if self.is_verified_scale() else "PROVISIONAL"

    def log_edit(self, action: str, **details: Any) -> None:
        from datetime import datetime, timezone

        self.edits.append(
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action, **details}
        )


def _point_from(d: dict[str, Any] | None) -> Point2D | None:
    if d is None:
        return None
    return Point2D(float(d["x"]), float(d["y"]))


def project_to_dict(project: Project) -> dict[str, Any]:
    return asdict(project)


def project_from_dict(data: dict[str, Any]) -> Project:
    known = set(SourceInfo.__dataclass_fields__)
    source = SourceInfo(**{k: v for k, v in data["source"].items() if k in known})
    cal_raw = data["calibration"]
    calibration = Calibration(
        segment_id=cal_raw.get("segment_id"),
        pixel_start=_point_from(cal_raw.get("pixel_start")),
        pixel_end=_point_from(cal_raw.get("pixel_end")),
        measured_mm=cal_raw.get("measured_mm"),
        scale_mm_per_px=cal_raw.get("scale_mm_per_px"),
        origin_px=_point_from(cal_raw.get("origin_px")) or Point2D(0.0, 0.0),
        flip_y=bool(cal_raw.get("flip_y", True)),
        calibrated=bool(cal_raw.get("calibrated", False)),
        # v1 projects could only be calibrated from a user-entered length
        method=cal_raw.get("method") or ("measured" if cal_raw.get("calibrated") else None),
        note=cal_raw.get("note", ""),
    )

    def seg(d: dict[str, Any]) -> Segment:
        return Segment(
            id=d["id"],
            entity_type=EntityType(d["entity_type"]),
            start=Point2D(**d["start"]),
            end=Point2D(**d["end"]),
            confidence=Confidence(d.get("confidence", "medium")),
            thickness_mm=d.get("thickness_mm"),
            thickness_px=d.get("thickness_px"),
            label=d.get("label"),
            source=d.get("source", "auto"),
            removed=bool(d.get("removed", False)),
        )

    def poly(d: dict[str, Any]) -> Polyline:
        return Polyline(
            id=d["id"],
            entity_type=EntityType(d["entity_type"]),
            points=[Point2D(**p) for p in d["points"]],
            closed=bool(d.get("closed", True)),
            confidence=Confidence(d.get("confidence", "medium")),
            label=d.get("label"),
            source=d.get("source", "auto"),
            removed=bool(d.get("removed", False)),
        )

    def txt(d: dict[str, Any]) -> TextLabel:
        return TextLabel(
            id=d["id"],
            text=d["text"],
            position=Point2D(**d["position"]),
            confidence=Confidence(d.get("confidence", "low")),
            source=d.get("source", "ocr"),
            removed=bool(d.get("removed", False)),
            width=float(d.get("width", 0.0)),
            height=float(d.get("height", 0.0)),
            kind=d.get("kind", "label"),
        )

    return Project(
        id=data["id"],
        schema_version=PROJECT_SCHEMA_VERSION,  # older files are upgraded on load
        source=source,
        calibration=calibration,
        walls=[seg(w) for w in data.get("walls", [])],
        rooms=[poly(r) for r in data.get("rooms", [])],
        openings=[seg(o) for o in data.get("openings", [])],
        texts=[txt(t) for t in data.get("texts", [])],
        wall_height_mm=float(data.get("wall_height_mm", 2700.0)),
        units_display=data.get("units_display", "m"),
        drawing_units=data.get("drawing_units", "mm"),
        edits=list(data.get("edits", [])),
    )
