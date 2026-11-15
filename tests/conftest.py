from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest


def draw_synthetic_plan() -> np.ndarray:
    """
    1000x700 white sheet with a two-room plan drawn as filled wall bands:

      outer box  x 100..900, y 100..600, walls 20 px thick
      partition  at x = 500 (10 px thick) with a door gap y 300..380
      a filled furniture blob that must not become a wall
      a small separate "key plan" that must be ignored
    """
    img = np.full((700, 1000, 3), 255, np.uint8)
    ink = (60, 60, 60)
    cv2.rectangle(img, (100, 100), (900, 120), ink, -1)  # top
    cv2.rectangle(img, (100, 580), (900, 600), ink, -1)  # bottom
    cv2.rectangle(img, (100, 100), (120, 600), ink, -1)  # left
    cv2.rectangle(img, (880, 100), (900, 600), ink, -1)  # right
    cv2.rectangle(img, (495, 120), (505, 300), ink, -1)  # partition above door
    cv2.rectangle(img, (495, 380), (505, 580), ink, -1)  # partition below door
    cv2.rectangle(img, (200, 250), (330, 400), (150, 150, 150), -1)  # furniture
    cv2.rectangle(img, (930, 630), (980, 680), ink, 6)  # key plan
    return img


@pytest.fixture
def synthetic_plan() -> np.ndarray:
    return draw_synthetic_plan()


@pytest.fixture
def workspace(tmp_path: Path, synthetic_plan: np.ndarray) -> Path:
    """A project root with input/plan.png ready to process."""
    (tmp_path / "input").mkdir()
    cv2.imwrite(str(tmp_path / "input" / "plan.png"), synthetic_plan)
    return tmp_path
