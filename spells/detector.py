"""
Hand detector using MediaPipe Hands Tasks API (mediapipe >= 0.10.14).
Model file hand_landmarker.task (~8 MB) is downloaded automatically on first run.
"""

import logging
import math
import os
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent / "hand_landmarker.task"
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
_MODEL_DOWNLOAD_TIMEOUT = 30  # seconds — fail fast on stalled corporate proxies


def _ensure_model() -> None:
    """Download hand_landmarker.task on first run.

    Atomic: stream to a temp file in the same directory, then os.replace.
    Partial download will not leave a corrupt model on disk.
    """
    if _MODEL_PATH.exists():
        return

    log.info("Downloading hand_landmarker.task (~8 MB) ...")
    tmp_path = _MODEL_PATH.with_suffix(_MODEL_PATH.suffix + ".part")
    try:
        with urllib.request.urlopen(_MODEL_URL, timeout=_MODEL_DOWNLOAD_TIMEOUT) as resp, \
             open(tmp_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        os.replace(tmp_path, _MODEL_PATH)
        log.info("Saved -> %s", _MODEL_PATH)
    except Exception:
        # Clean up partial file so next run retries cleanly
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def detect_screen_corners(frame: np.ndarray) -> np.ndarray | None:
    """Find the bright white border on the projected screen."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, open_k)
    ys, xs = np.where(bright > 0)
    if len(xs) < 100:
        return None
    pts_xy = np.column_stack([xs, ys]).reshape(-1, 1, 2).astype(np.int32)
    hull = cv2.convexHull(pts_xy)
    peri = cv2.arcLength(hull, True)
    approx = cv2.approxPolyDP(hull, 0.03 * peri, True)
    if len(approx) != 4:
        approx = cv2.approxPolyDP(hull, 0.05 * peri, True)
    if len(approx) != 4:
        return None
    corners = np.array([p[0] for p in approx], dtype=np.float32)
    pts = corners.reshape(4, 2)
    # Sort by y (primary), so pts[:2] = top pair, pts[2:] = bottom pair.
    pts = pts[np.lexsort((pts[:, 0], pts[:, 1]))]
    top_pair = pts[:2][np.argsort(pts[:2, 0])]   # left→right within top row
    bot_pair = pts[2:][np.argsort(pts[2:, 0])]   # left→right within bottom row
    tl, tr = top_pair          # top-left, top-right
    bl, br = bot_pair          # bottom-left, bottom-right
    return np.array([tl, tr, br, bl], dtype=np.float32)


@dataclass
class HandState:
    detected: bool
    palm_center: tuple[float, float] | None      # screen coords
    fingertips: tuple[float, float] | None       # screen coords
    palm_center_cam: tuple[float, float] | None  # raw camera coords (for debug window)
    hand_dir: tuple[float, float] | None         # normalised wrist→fingers in screen space
    orientation: str | None                      # "facing_camera" | "parallel_to_floor"
    gesture: str | None                          # "fist" | "open"
    velocity: tuple[float, float] | None         # px/frame
    spell: dict | None = None


_SCREEN_W, _SCREEN_H = 1920, 1080


class HandTracker:
    def __init__(self, history_size: int = 8, move_threshold: float = 5.0):
        self.history: list[tuple[float, float, float]] = []  # (x, y, time)
        self.history_size = history_size
        self.prev_gesture: str | None = None
        self.move_threshold = move_threshold
        self._mono_origin: int | None = None

        # Orientation confirmation & spell casting
        self.raw_orientation: str | None = None
        self.confirm_counter: int = 0
        self.REQUIRED_CONFIRMS: int = 2
        self.spell_orientation: str | None = None
        self.spell_charge: float = 0.0
        self.CHARGE_RATE: float = 0.22   # ~5 frames to full at 30 FPS
        self.FADE_RATE: float = 0.14     # ~7 frames to fade

        _ensure_model()

        import mediapipe as mp
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision

        self._mp = mp
        base_options = mp_tasks.BaseOptions(model_asset_path=str(_MODEL_PATH))
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
            min_hand_detection_confidence=0.4,
            min_hand_presence_confidence=0.3,
            min_tracking_confidence=0.3,
            running_mode=vision.RunningMode.VIDEO,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    # ------------------------------------------------------------------
    def _gesture(self, lm) -> str:
        # Rotation-invariant 3D: tip farther from wrist than pip → finger extended.
        # Using z-coordinate helps when hand is parallel to floor (foreshortened in 2D).
        wx, wy, wz = lm[0].x, lm[0].y, lm[0].z
        fingers = [(8, 6), (12, 10), (16, 14), (20, 18)]
        extended = 0
        for tip_i, pip_i in fingers:
            tip_d = math.sqrt((lm[tip_i].x-wx)**2 + (lm[tip_i].y-wy)**2 + (lm[tip_i].z-wz)**2)
            pip_d = math.sqrt((lm[pip_i].x-wx)**2 + (lm[pip_i].y-wy)**2 + (lm[pip_i].z-wz)**2)
            if tip_d > pip_d * 0.85:  # lenient: tip must be at least 85% as far as pip
                extended += 1
        return "open" if extended >= 2 else "fist"  # lower threshold: 2 of 4 fingers

    def _orientation(self, lm, w: int, h: int) -> str:
        """
        Determine palm orientation using z-depth (primary) and 2D spread (fallback).
        z is depth relative to wrist; smaller = closer to camera.
        Facing camera  → hand is flat in z (small z variation).
        Parallel floor → hand extends in z (large z variation).
        """
        # ── Primary: normalized z-depth range ──
        all_z = [lm[i].z for i in range(21)]
        z_range = max(all_z) - min(all_z)
        hand_size = math.hypot(lm[12].x - lm[0].x, lm[12].y - lm[0].y)
        if hand_size > 0.01 and (z_range / hand_size) > 0.35:
            return "parallel_to_floor"

        # ── Fallback: 2D spread in hand-centered frame ──
        wx, wy = lm[0].x, lm[0].y
        ax = lm[9].x - wx
        ay = lm[9].y - wy
        mag = math.hypot(ax, ay)
        if mag < 0.005:
            return "facing_camera"
        ux, uy = ax / mag, ay / mag
        px, py = -uy, ux

        tips = [8, 12, 16, 20]
        lateral = [(lm[i].x - wx) * px + (lm[i].y - wy) * py for i in tips]
        longit  = [(lm[i].x - wx) * ux + (lm[i].y - wy) * uy for i in tips]
        spread_lat  = max(lateral) - min(lateral)
        spread_long = max(longit)  - min(longit)

        if spread_lat > spread_long * 0.55:
            return "facing_camera"
        return "parallel_to_floor"

    def _fingertips_center(self, lm, w: int, h: int) -> tuple[float, float]:
        tips = [8, 12, 16, 20]
        cx = sum(lm[i].x for i in tips) / len(tips) * w
        cy = sum(lm[i].y for i in tips) / len(tips) * h
        return cx, cy

    # ------------------------------------------------------------------
    def detect(self, frame: np.ndarray, M: np.ndarray | None) -> HandState:
        h, w = frame.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        # VIDEO mode requires strictly monotonic timestamps in milliseconds.
        now_mono_ms = int(time.monotonic() * 1000)
        if self._mono_origin is None:
            self._mono_origin = now_mono_ms - 1
        ts_ms = now_mono_ms - self._mono_origin  # always >= 1

        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(mp_image, ts_ms)

        if not result.hand_landmarks:
            self.history.clear()
            self.prev_gesture = None
            return HandState(detected=False, palm_center=None, fingertips=None,
                             palm_center_cam=None, hand_dir=None, orientation=None,
                             gesture=None, velocity=None)

        lm = result.hand_landmarks[0]

        palm_cam    = (lm[9].x * w, lm[9].y * h)
        gesture     = self._gesture(lm)
        raw_orient  = self._orientation(lm, w, h)
        tips_cam    = self._fingertips_center(lm, w, h)

        # ── Orientation confirmation (fast, minimal delay) ──
        if raw_orient == self.raw_orientation and raw_orient is not None:
            self.confirm_counter += 1
        else:
            self.confirm_counter = 0
            self.raw_orientation = raw_orient

        confirmed_orientation = raw_orient if self.confirm_counter >= self.REQUIRED_CONFIRMS else None

        # ── Movement tracking ──
        now = time.time()
        self.history.append((*palm_cam, now))
        if len(self.history) > self.history_size:
            self.history.pop(0)

        velocity = (0.0, 0.0)
        if len(self.history) >= 2:
            dx = self.history[-1][0] - self.history[-2][0]
            dy = self.history[-1][1] - self.history[-2][1]
            velocity = (dx, dy)

        # ── Spell state machine ──
        if gesture == "fist":
            # Fist immediately cancels any spell
            self.spell_orientation = None
            self.spell_charge = 0.0
        elif confirmed_orientation is not None:
            if self.spell_orientation is None:
                # Start new spell
                self.spell_orientation = confirmed_orientation
                self.spell_charge = min(1.0, self.spell_charge + self.CHARGE_RATE)
            elif self.spell_orientation == confirmed_orientation:
                # Continue charging same spell
                self.spell_charge = min(1.0, self.spell_charge + self.CHARGE_RATE)
            else:
                # Different orientation without fist — fade out, NO new spell
                self.spell_charge = max(0.0, self.spell_charge - self.FADE_RATE)
                if self.spell_charge <= 0:
                    self.spell_orientation = None
        else:
            # No confirmed orientation — fade out
            self.spell_charge = max(0.0, self.spell_charge - self.FADE_RATE)
            if self.spell_charge <= 0:
                self.spell_orientation = None

        self.prev_gesture = gesture

        # ── Map camera coords → screen coords via homography ──
        def _linear(x, y):
            return x / w * _SCREEN_W, y / h * _SCREEN_H

        def _xform(x, y):
            pt  = np.array([[[x, y]]], dtype=np.float32)
            out = cv2.perspectiveTransform(pt, M)
            sx, sy = float(out[0][0][0]), float(out[0][0][1])
            # If homography produces wildly out-of-range values (bad calibration),
            # fall back to simple linear scaling.
            if abs(sx) > 3 * _SCREEN_W or abs(sy) > 3 * _SCREEN_H:
                return _linear(x, y)
            return sx, sy

        # Wrist and middle-MCP camera coords for hand direction
        wrist_cam = (lm[0].x * w, lm[0].y * h)
        mcp_cam   = (lm[9].x * w, lm[9].y * h)

        if M is not None:
            palm_screen  = _xform(*palm_cam)
            tips_screen  = _xform(*tips_cam)
            wrist_screen = _xform(*wrist_cam)
            mcp_screen   = _xform(*mcp_cam)
        else:
            palm_screen  = _linear(*palm_cam)
            tips_screen  = _linear(*tips_cam)
            wrist_screen = _linear(*wrist_cam)
            mcp_screen   = _linear(*mcp_cam)

        # Normalised hand direction in screen space (wrist → middle MCP)
        hdx = mcp_screen[0] - wrist_screen[0]
        hdy = mcp_screen[1] - wrist_screen[1]
        hmag = math.hypot(hdx, hdy)
        hand_dir = (hdx / hmag, hdy / hmag) if hmag > 1 else (0.0, -1.0)

        # Build spell payload if charge > 0
        spell = None
        if self.spell_charge > 0 and self.spell_orientation is not None:
            if self.spell_orientation == "facing_camera":
                origin = palm_screen
            else:
                # Offset from fingertips along hand direction (away from wrist)
                off = 30
                origin = (tips_screen[0] + hand_dir[0] * off,
                          tips_screen[1] + hand_dir[1] * off)

            speed = math.hypot(*velocity)
            if speed > 1.0:
                direction = (velocity[0] / speed, velocity[1] / speed)
            else:
                direction = (0.0, -1.0)

            spell = {
                "orientation": self.spell_orientation,
                "charge": round(self.spell_charge, 3),
                "origin": [round(origin[0], 1), round(origin[1], 1)],
                "direction": [round(direction[0], 3), round(direction[1], 3)],
            }

        return HandState(
            detected=True,
            palm_center=palm_screen,
            fingertips=tips_screen,
            palm_center_cam=palm_cam,
            hand_dir=hand_dir,
            orientation=self.spell_orientation,
            gesture=gesture,
            velocity=velocity,
            spell=spell,
        )

    def draw_debug(self, frame: np.ndarray, state: HandState) -> np.ndarray:
        return frame
