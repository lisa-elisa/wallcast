"""
Interactive calibration tool: maps 4 camera points to the 4 screen corners.

Steps:
  1. Open calibration.html on the projector screen (F11 for fullscreen)
  2. Run:  python calibrate.py
  3. Click the 4 green markers in order: TL → TR → BR → BL
  4. Press 'c' to save, 'r' to reset, ESC to abort

Output: calibration/calibration_data.json
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

SCREEN_W, SCREEN_H = 1920, 1080
OUTPUT_FILE = Path(__file__).parent / "calibration" / "calibration_data.json"

# Screen corners in screen space (TL, TR, BR, BL)
SCREEN_CORNERS = np.array(
    [
        [0, 0],
        [SCREEN_W - 1, 0],
        [SCREEN_W - 1, SCREEN_H - 1],
        [0, SCREEN_H - 1],
    ],
    dtype=np.float32,
)

CORNER_LABELS = ["1 — Top-Left", "2 — Top-Right", "3 — Bottom-Right", "4 — Bottom-Left"]
CORNER_COLORS = [(0, 255, 0), (0, 200, 255), (255, 100, 0), (200, 0, 255)]

clicked: list[list[int]] = []


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN and len(clicked) < 4:
        clicked.append([x, y])
        print(f"  Point {len(clicked)}: ({x}, {y})  [{CORNER_LABELS[len(clicked) - 1]}]")


def main():
    parser_args = sys.argv[1:]
    cam_idx = int(parser_args[0]) if parser_args else 0

    cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera {cam_idx}")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    WIN = "Wallplay Calibration — click 4 corners TL>TR>BR>BL"
    cv2.namedWindow(WIN)
    cv2.setMouseCallback(WIN, on_mouse)

    print("\nCalibration started.")
    print("Make sure calibration.html is open fullscreen on the projector.\n")
    print("Click the 4 green markers in order:")
    for label in CORNER_LABELS:
        print(f"  {label}")
    print("\nKeys: [c] save  [r] reset  [ESC] quit\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        display = frame.copy()

        # Draw already-clicked points
        for i, pt in enumerate(clicked):
            cv2.circle(display, tuple(pt), 10, CORNER_COLORS[i], -1)
            cv2.putText(
                display,
                str(i + 1),
                (pt[0] + 12, pt[1] - 8),
                cv2.FONT_HERSHEY_DUPLEX,
                0.8,
                CORNER_COLORS[i],
                2,
            )

        # Instruction overlay
        if len(clicked) < 4:
            next_lbl = CORNER_LABELS[len(clicked)]
            text = f"Click: {next_lbl}"
            color = CORNER_COLORS[len(clicked)]
        else:
            text = "All 4 points set.  Press [c] to save, [r] to reset"
            color = (255, 255, 255)

        cv2.rectangle(display, (0, 0), (display.shape[1], 50), (0, 0, 0), -1)
        cv2.putText(display, text, (15, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        # Preview the picked quadrilateral when all 4 points are set
        if len(clicked) == 4:
            pts = np.array(clicked, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(display, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

        cv2.imshow(WIN, display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("c") and len(clicked) == 4:
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "camera_points": clicked,
                "screen_points": SCREEN_CORNERS.tolist(),
            }
            OUTPUT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"\nCalibration saved → {OUTPUT_FILE}")
            print("Restart server.py to apply.")
            break

        if key == ord("r"):
            clicked.clear()
            print("Reset — click 4 corners again.\n")

        elif key == 27:  # ESC
            print("Aborted.")
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
