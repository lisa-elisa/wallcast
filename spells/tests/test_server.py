"""Tests for spells/server.py coordinate transforms + calibration loader."""
import json

import cv2
import numpy as np


def test_xform_pt_identity_matrix():
    import server
    M = np.eye(3, dtype=np.float64)
    x, y = server._xform_pt(M, 100.0, 200.0)
    assert abs(x - 100.0) < 1e-3
    assert abs(y - 200.0) < 1e-3


def test_xform_pt_scale_matrix():
    import server
    M = np.array([[2.0, 0.0, 0.0],
                  [0.0, 2.0, 0.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    x, y = server._xform_pt(M, 100.0, 200.0)
    assert abs(x - 200.0) < 1e-3
    assert abs(y - 400.0) < 1e-3


def test_load_homography_returns_linear_fallback_when_file_missing(monkeypatch, tmp_path):
    import server
    missing = tmp_path / "nonexistent.json"
    monkeypatch.setattr(server, "CALIBRATION_FILE", missing)

    M = server.load_homography()
    # Expected linear scale: 1920/1280 = 1.5, 1080/720 = 1.5
    assert abs(M[0, 0] - 1.5) < 1e-6
    assert abs(M[1, 1] - 1.5) < 1e-6
    assert M[2, 2] == 1.0


def test_load_homography_parses_valid_json(monkeypatch, tmp_path):
    import server
    calib_file = tmp_path / "calibration_data.json"
    calib_file.write_text(json.dumps({
        "camera_points": [[0, 0], [1280, 0], [1280, 720], [0, 720]],
        "screen_points": [[0, 0], [1920, 0], [1920, 1080], [0, 1080]],
    }))
    monkeypatch.setattr(server, "CALIBRATION_FILE", calib_file)

    M = server.load_homography()
    # Same 4-corner mapping as the linear fallback → same 1.5× scale
    x = np.array([[[640.0, 360.0]]], dtype=np.float32)
    out = cv2.perspectiveTransform(x, M)[0][0]
    assert abs(out[0] - 960.0) < 0.1
    assert abs(out[1] - 540.0) < 0.1
