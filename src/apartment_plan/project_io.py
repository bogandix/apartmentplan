"""Persist and load versioned project JSON + related artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Project, project_from_dict, project_to_dict


def default_project_dir(root: Path, project_id: str | None = None) -> Path:
    base = Path(root) / "projects"
    if project_id:
        return base / project_id
    return base


def save_project(project: Project, project_dir: Path) -> Path:
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / "project.json"
    path.write_text(json.dumps(project_to_dict(project), indent=2), encoding="utf-8")
    return path


def load_project(project_dir: Path) -> Project:
    path = Path(project_dir) / "project.json"
    if not path.is_file():
        raise FileNotFoundError(f"No project.json in {project_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return project_from_dict(data)


def latest_project_dir(root: Path) -> Path | None:
    base = Path(root) / "projects"
    if not base.is_dir():
        return None
    dirs = [p for p in base.iterdir() if p.is_dir() and (p / "project.json").is_file()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0]
