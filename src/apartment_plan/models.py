"""Versioned project data model for apartment plan digitization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


PROJECT_SCHEMA_VERSION = 1


class EntityType(str, Enum):
    WALL = "wall"
    ROOM = "room"
    DOOR = "door"
    WINDOW = "window"
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
    note: str = "UNCALIBRATED — not real scale until a measured wall length is set"


@dataclass
class SourceInfo:
    original_path: str
    page_index: int = 0
    image_width: int = 0
    image_height: int = 0
    rendered_path: str | None = None
    warnings: list[str] = field(default_factory=list)


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


def _point_from(d: dict[str, Any] | None) -> Point2D | None:
    if d is None:
        return None
    return Point2D(float(d["x"]), float(d["y"]))


def project_to_dict(project: Project) -> dict[str, Any]:
    return asdict(project)


def project_from_dict(data: dict[str, Any]) -> Project:
    source = SourceInfo(**data["source"])
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
        )

    return Project(
        id=data["id"],
        schema_version=int(data.get("schema_version", PROJECT_SCHEMA_VERSION)),
        source=source,
        calibration=calibration,
        walls=[seg(w) for w in data.get("walls", [])],
        rooms=[poly(r) for r in data.get("rooms", [])],
        openings=[seg(o) for o in data.get("openings", [])],
        texts=[txt(t) for t in data.get("texts", [])],
        wall_height_mm=float(data.get("wall_height_mm", 2700.0)),
        units_display=data.get("units_display", "m"),
        drawing_units=data.get("drawing_units", "mm"),
    )
