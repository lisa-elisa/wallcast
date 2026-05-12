"""Shared fixtures for falling_balls tests."""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Add parent dir to sys.path so `import detector` works from tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

W, H = 1280, 720
RED = (0, 0, 220)
BLUE = (200, 0, 0)


def _make_frame(*polys):
    """White frame with filled BGR polygons: [(pts, bgr_color), ...]"""
    frame = np.ones((H, W, 3), dtype=np.uint8) * 240
    for pts, color in polys:
        cv2.fillPoly(frame, [np.array(pts, dtype=np.int32)], color)
    return frame


@pytest.fixture
def make_frame():
    return _make_frame


@pytest.fixture
def red_horizontal_paper():
    return _make_frame(
        ([[200, 300], [700, 300], [700, 380], [200, 380]], RED),
    )


@pytest.fixture
def detector():
    from detector import Detector

    return Detector()
