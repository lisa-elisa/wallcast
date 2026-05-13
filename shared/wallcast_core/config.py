"""Shared screen/camera/network constants for both Wallcast modes."""

import numpy as np

SCREEN_W, SCREEN_H = 1920, 1080
CAM_W, CAM_H = 1280, 720
WS_PORT = 8765
PHONE_CAM_PORT = 8766
TARGET_FPS = 30
DISP_W, DISP_H = 960, 540  # debug window size

SCREEN_CORNERS = np.array(
    [
        [0, 0],
        [SCREEN_W - 1, 0],
        [SCREEN_W - 1, SCREEN_H - 1],
        [0, SCREEN_H - 1],
    ],
    dtype=np.float32,
)
