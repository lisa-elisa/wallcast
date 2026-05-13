"""Homography helpers - load 4-point calibration, transform points in batch."""

import json
from pathlib import Path

import cv2
import numpy as np

from .config import CAM_H, CAM_W, SCREEN_H, SCREEN_W


def transform_points(M: np.ndarray, pts: np.ndarray | list) -> np.ndarray:
    """Apply a 3x3 perspective transform to an (N, 2) array (or list of [x, y]).

    Returns an (N, 2) float64 array.
    """
    arr = np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(arr, M)
    return out.reshape(-1, 2).astype(np.float64)


def transform_point(M: np.ndarray, x: float, y: float) -> tuple[float, float]:
    """Apply M to a single (x, y) - kept for callers that prefer scalar form."""
    out = transform_points(M, [[x, y]])[0]
    return float(out[0]), float(out[1])


def linear_fallback() -> np.ndarray:
    """Camera-to-screen linear scale used when no calibration file exists."""
    sx, sy = SCREEN_W / CAM_W, SCREEN_H / CAM_H
    return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=np.float64)


def load_homography_file(path: Path) -> np.ndarray | None:
    """Load a 4-point calibration JSON, return its 3x3 perspective matrix.

    Returns None if the file does not exist or is malformed.
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    src = np.array(data["camera_points"], dtype=np.float32)
    dst = np.array(data["screen_points"], dtype=np.float32)
    return cv2.getPerspectiveTransform(src, dst)
