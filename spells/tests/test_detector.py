"""
Detector tests for spells. MediaPipe is NOT required — we instantiate
HandTracker via __new__ to bypass the heavy __init__ that loads the model,
and call only the pure landmark-processing methods.
"""

import cv2
import numpy as np
from detector import detect_screen_corners

# ── Gesture (fist vs open) ────────────────────────────────────────────────────


def test_gesture_fist(tracker_no_init, fist_landmarks):
    assert tracker_no_init._gesture(fist_landmarks) == "fist"


def test_gesture_open(tracker_no_init, open_landmarks):
    assert tracker_no_init._gesture(open_landmarks) == "open"


# ── Orientation ───────────────────────────────────────────────────────────────


def test_orientation_facing_camera_small_z_range(tracker_no_init, make_landmark_factory):
    """All landmarks at z≈0 → flat hand facing camera."""
    lms = []
    for i in range(21):
        if i == 0:
            lms.append(make_landmark_factory(0.5, 0.5, 0.0))  # wrist
        elif i == 9:
            lms.append(make_landmark_factory(0.5, 0.3, 0.0))  # mid MCP
        elif i in (8, 12, 16, 20):
            # Tips spread laterally — encourages "facing_camera" via 2D spread
            spread = {8: 0.30, 12: 0.40, 16: 0.50, 20: 0.60}[i]
            lms.append(make_landmark_factory(spread, 0.2, 0.0))
        else:
            lms.append(make_landmark_factory(0.5, 0.4, 0.0))
    assert tracker_no_init._orientation(lms, 1280, 720) == "facing_camera"


def test_orientation_parallel_to_floor_large_z_range(tracker_no_init, make_landmark_factory):
    """Big z-spread relative to hand size → palm parallel to floor."""
    lms = []
    for i in range(21):
        if i == 0:
            lms.append(make_landmark_factory(0.5, 0.5, 0.0))  # wrist at z=0
        elif i == 12:
            lms.append(make_landmark_factory(0.55, 0.45, 0.0))  # middle MCP, hand_size ~= 0.07
        elif i in (8, 16, 20):
            lms.append(make_landmark_factory(0.5, 0.4, 0.05))  # tips at high z
        else:
            lms.append(make_landmark_factory(0.5, 0.5, 0.0))
    # hand_size = hypot(0.05, 0.05) ≈ 0.07; z_range = 0.05; ratio = 0.05/0.07 ≈ 0.7 > 0.35 ✓
    assert tracker_no_init._orientation(lms, 1280, 720) == "parallel_to_floor"


# ── Fingertip centroid ────────────────────────────────────────────────────────


def test_fingertips_center_symmetric(tracker_no_init, make_landmark_factory):
    """Four symmetric tips around (0.5, 0.5) → centroid at (0.5×W, 0.5×H)."""
    lms = [make_landmark_factory(0.5, 0.5) for _ in range(21)]
    lms[8] = make_landmark_factory(0.4, 0.5)
    lms[12] = make_landmark_factory(0.5, 0.4)
    lms[16] = make_landmark_factory(0.6, 0.5)
    lms[20] = make_landmark_factory(0.5, 0.6)

    cx, cy = tracker_no_init._fingertips_center(lms, 1000, 800)
    assert abs(cx - 500.0) < 0.1
    assert abs(cy - 400.0) < 0.1


def test_fingertips_center_scales_to_frame_size(tracker_no_init, make_landmark_factory):
    lms = [make_landmark_factory(0.25, 0.75) for _ in range(21)]
    cx, cy = tracker_no_init._fingertips_center(lms, 800, 400)
    assert cx == 200.0  # 0.25 × 800
    assert cy == 300.0  # 0.75 × 400


# ── Projected screen corner detection ─────────────────────────────────────────


def test_detect_screen_corners_finds_white_rectangle():
    # Black frame with a bright white rectangle in the middle
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(frame, (100, 80), (700, 520), (255, 255, 255), -1)

    corners = detect_screen_corners(frame)
    assert corners is not None
    assert corners.shape == (4, 2)

    # Each detected corner should sit near one of the four ground-truth corners
    truth = [(100, 80), (700, 80), (700, 520), (100, 520)]
    for got in corners:
        nearest = min(truth, key=lambda t: (t[0] - got[0]) ** 2 + (t[1] - got[1]) ** 2)
        assert abs(nearest[0] - got[0]) < 15
        assert abs(nearest[1] - got[1]) < 15


def test_detect_screen_corners_returns_none_for_empty_frame():
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    assert detect_screen_corners(frame) is None


def test_detect_screen_corners_order_tl_tr_br_bl():
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(frame, (100, 80), (700, 520), (255, 255, 255), -1)

    corners = detect_screen_corners(frame)
    assert corners is not None
    tl, tr, br, bl = corners
    # TL has smallest x+y, BR has largest
    assert tl[0] + tl[1] < tr[0] + tr[1]
    assert tl[0] + tl[1] < br[0] + br[1]
    assert tl[0] + tl[1] < bl[0] + bl[1]
    # TL and BL share left x; TR and BR share right x
    assert tl[0] < tr[0]
    assert bl[0] < br[0]
    # TL and TR share top y; BL and BR share bottom y
    assert tl[1] < bl[1]
    assert tr[1] < br[1]
