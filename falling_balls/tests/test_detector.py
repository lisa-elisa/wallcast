"""
Offline detector tests — no camera required.
Generates synthetic frames and verifies detection.
"""
import numpy as np
import pytest

from detector import Ball, Detector, MIN_PAPER_AREA, Obstacle

RED  = (0, 0, 220)
BLUE = (200, 0, 0)


# ── Dataclass serialization ───────────────────────────────────────────────────

def test_obstacle_to_dict_fields_and_rounding():
    o = Obstacle(id="paper_0", cx=100.456, cy=200.789, w=50.111, h=25.999,
                 angle=15.444, vertices=[[1.234, 2.345], [3.456, 4.567]])
    d = o.to_dict()

    assert d["id"] == "paper_0"
    assert d["cx"] == 100.5
    assert d["cy"] == 200.8
    assert d["w"] == 50.1
    assert d["h"] == 26.0
    assert d["angle"] == 15.44
    assert d["vertices"] == [[1.2, 2.3], [3.5, 4.6]]


def test_ball_to_dict_rounds_to_int():
    b = Ball(id="ball_0", x=10.4, y=20.6, r=5.5)
    d = b.to_dict()
    assert d == {"id": "ball_0", "x": 10, "y": 21, "r": 6}


# ── Corner sorting ────────────────────────────────────────────────────────────

def test_sort_corners_returns_tl_tr_br_bl():
    # Random order of a 100×100 square's corners
    pts = np.array([
        [100, 100],   # BR
        [0,   0  ],   # TL
        [100, 0  ],   # TR
        [0,   100],   # BL
    ], dtype=np.float32)
    sorted_pts = Detector._sort_corners(pts)
    assert sorted_pts.tolist() == [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_sort_corners_handles_tilted_quad():
    # Diamond rotated 45°
    pts = np.array([[50, 0], [100, 50], [50, 100], [0, 50]], dtype=np.float32)
    sorted_pts = Detector._sort_corners(pts)
    # After arctan2 sort: angles roughly -90°, 0°, 90°, 180°
    # → top, right, bottom, left
    assert sorted_pts[0].tolist() == [50, 0]
    assert sorted_pts[1].tolist() == [100, 50]
    assert sorted_pts[2].tolist() == [50, 100]
    assert sorted_pts[3].tolist() == [0, 50]


# ── HSV mask sanity ───────────────────────────────────────────────────────────

def test_build_hsv_mask_removes_small_noise(detector):
    import cv2
    # Frame with one large red square and one tiny red speck
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 240
    cv2.rectangle(frame, (200, 200), (600, 500), RED, -1)
    cv2.rectangle(frame, (1000, 100), (1003, 103), RED, -1)  # 3×3 speck

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = detector._build_hsv_mask(
        hsv,
        np.array([0,   100, 100], dtype=np.uint8),
        np.array([10,  255, 255], dtype=np.uint8),
        np.array([160, 100, 100], dtype=np.uint8),
        np.array([180, 255, 255], dtype=np.uint8),
    )

    # Big rectangle: ~120000 px; tiny speck filtered by MORPH_OPEN with 7×7 kernel
    n_contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assert len(n_contours) == 1


# ── End-to-end paper detection ────────────────────────────────────────────────

def test_single_horizontal_paper(detector, red_horizontal_paper):
    obs = detector.detect_red_papers(red_horizontal_paper)
    assert len(obs) == 1
    o = obs[0]
    assert 420 < o.cx < 480
    assert 320 < o.cy < 360
    assert o.w > o.h


def test_two_separate_papers(detector, make_frame):
    frame = make_frame(
        ([[100, 200], [300, 200], [300, 270], [100, 270]], RED),
        ([[500, 200], [700, 200], [700, 270], [500, 270]], RED),
    )
    obs = detector.detect_red_papers(frame)
    assert len(obs) == 2


def test_v_shaped_merged_papers_split(detector, make_frame):
    # Two skewed rectangles sharing a bottom corner — concave merged contour
    pts1 = [[80,  80], [180, 80], [220, 300], [120, 300]]
    pts2 = [[220, 80], [320, 80], [260, 300], [160, 300]]
    frame = make_frame((pts1, RED), (pts2, RED))
    obs = detector.detect_red_papers(frame)
    assert len(obs) == 2

    centers_y = [o.cy for o in obs]
    assert all(150 < cy < 250 for cy in centers_y)

    centers_x = sorted(o.cx for o in obs)
    assert centers_x[1] - centers_x[0] > 50


def test_non_red_object_ignored(detector, make_frame):
    frame = make_frame(([[200, 200], [600, 200], [600, 350], [200, 350]], BLUE))
    assert detector.detect_red_papers(frame) == []


def test_tiny_blob_below_min_area_filtered(detector, make_frame):
    # 40×20 = 800 px², below MIN_PAPER_AREA (2000)
    frame = make_frame(([[300, 300], [340, 300], [340, 320], [300, 320]], RED))
    obs = detector.detect_red_papers(frame)
    assert obs == []
    assert MIN_PAPER_AREA > 800


def test_tilted_paper_45_degrees(detector, make_frame):
    cx, cy, half_w, half_h = 640, 360, 150, 30
    angle_rad = np.deg2rad(45)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    corners = []
    for sx, sy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
        rx = half_w * sx * cos_a - half_h * sy * sin_a + cx
        ry = half_w * sx * sin_a + half_h * sy * cos_a + cy
        corners.append([int(rx), int(ry)])
    frame = make_frame((corners, RED))

    obs = detector.detect_red_papers(frame)
    assert len(obs) == 1
    o = obs[0]
    assert abs(o.cx - 640) < 20
    assert abs(o.cy - 360) < 20
    assert abs(o.angle % 90 - 45) < 10


def test_draw_debug_overlay_does_not_crash(detector, red_horizontal_paper):
    obs = detector.detect_red_papers(red_horizontal_paper)
    out = detector.draw_debug_overlay(red_horizontal_paper, obs)
    assert out.shape == red_horizontal_paper.shape
