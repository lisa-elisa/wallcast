"""Tests for falling_balls/server.py coordinate transforms."""

import numpy as np
from detector import Obstacle
from server import _xform_pt, transform_obstacles


def test_xform_pt_identity_matrix_preserves_point():
    M = np.eye(3, dtype=np.float64)
    x, y = _xform_pt(M, 100.0, 200.0)
    assert abs(x - 100.0) < 1e-3
    assert abs(y - 200.0) < 1e-3


def test_xform_pt_scale_matrix_doubles_coordinates():
    # Affine 2× scale expressed as a 3×3 perspective matrix
    M = np.array([[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    x, y = _xform_pt(M, 100.0, 200.0)
    assert abs(x - 200.0) < 1e-3
    assert abs(y - 400.0) < 1e-3


def test_transform_obstacles_applies_scale():
    obs = Obstacle(
        id="paper_0",
        cx=100.0,
        cy=200.0,
        w=50.0,
        h=25.0,
        angle=0.0,
        vertices=[[75.0, 187.5], [125.0, 187.5], [125.0, 212.5], [75.0, 212.5]],
    )
    M = np.array([[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    result = transform_obstacles([obs], M)

    assert len(result) == 1
    d = result[0]
    assert d["cx"] == 200.0
    assert d["cy"] == 400.0
    # Each vertex doubled
    expected = [[150.0, 375.0], [250.0, 375.0], [250.0, 425.0], [150.0, 425.0]]
    for got_v, exp_v in zip(d["vertices"], expected, strict=True):
        assert abs(got_v[0] - exp_v[0]) < 0.1
        assert abs(got_v[1] - exp_v[1]) < 0.1
