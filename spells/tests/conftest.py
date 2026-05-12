"""Shared fixtures for spells tests."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add parent dir to sys.path so `import detector` works from tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_landmark(x: float, y: float, z: float = 0.0):
    """Build a fake MediaPipe NormalizedLandmark with .x / .y / .z."""
    return SimpleNamespace(x=x, y=y, z=z)


@pytest.fixture
def make_landmark_factory():
    return make_landmark


@pytest.fixture
def tracker_no_init():
    """
    HandTracker instance created without running __init__ —
    avoids the mediapipe dependency. Pure methods (_gesture,
    _orientation, _fingertips_center) work without setup.
    """
    from detector import HandTracker

    return HandTracker.__new__(HandTracker)


def _fist_landmarks():
    """
    21 landmarks where finger tips (8, 12, 16, 20) sit close to the wrist (0) —
    tip-to-wrist distance ~= pip-to-wrist distance, so _gesture returns "fist".
    """
    wrist = (0.5, 0.5, 0.0)
    pip = (0.5, 0.45, 0.0)  # pip joint slightly above wrist
    tip = (0.5, 0.46, 0.0)  # tip just barely above pip (curled)
    others = (0.5, 0.45, 0.0)
    lms = []
    for i in range(21):
        if i == 0:
            lms.append(make_landmark(*wrist))
        elif i in (8, 12, 16, 20):  # finger tips — curled in
            lms.append(make_landmark(*tip))
        elif i in (6, 10, 14, 18):  # finger pips
            lms.append(make_landmark(*pip))
        else:
            lms.append(make_landmark(*others))
    return lms


def _open_landmarks():
    """
    21 landmarks where finger tips are far above the wrist —
    extended fingers (tip distance > pip distance × 0.85).
    """
    wrist = (0.5, 0.9, 0.0)
    lms = []
    for i in range(21):
        if i == 0:
            lms.append(make_landmark(*wrist))
        elif i in (8, 12, 16, 20):  # tips far from wrist
            lms.append(make_landmark(0.5, 0.1, 0.0))
        elif i in (6, 10, 14, 18):  # pips between wrist and tip
            lms.append(make_landmark(0.5, 0.5, 0.0))
        else:
            lms.append(make_landmark(0.5, 0.7, 0.0))
    return lms


@pytest.fixture
def fist_landmarks():
    return _fist_landmarks()


@pytest.fixture
def open_landmarks():
    return _open_landmarks()
