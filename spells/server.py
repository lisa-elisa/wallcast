"""
WebSocket server: one camera thread → shared frame → N browser clients.

Usage:
    python server.py [--camera 0] [--port 8765] [--debug]

Debug window keys:
    drag  — grab any corner dot and reposition it
    [a]   — auto mode (corners follow detection)
    [r]   — reset corners to last auto-detected position
    [s]   — save current corners as calibration file
    [q]   — quit debug window
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import websockets  # noqa: E402
import websockets.exceptions  # noqa: E402
from detector import HandTracker, detect_screen_corners  # noqa: E402

from shared.wallcast_core.config import (  # noqa: E402
    CAM_H,
    CAM_W,
    DISP_H,
    DISP_W,
    PHONE_CAM_PORT,
    SCREEN_CORNERS,
    SCREEN_H,
    SCREEN_W,
    TARGET_FPS,
    WS_PORT,
)
from shared.wallcast_core.homography import (  # noqa: E402
    linear_fallback,
    load_homography_file,
    transform_point,
)
from shared.wallcast_core.netutil import get_local_ip  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────

CALIBRATION_FILE = Path(__file__).parent / "calibration" / "calibration_data.json"


try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass  # stdout не текстовый (CREATE_NO_WINDOW), или уже сконфигурирован

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
)
log = logging.getLogger(__name__)

CORNER_COLORS = [(220, 100, 50), (50, 150, 255), (255, 100, 50), (180, 50, 255)]
CORNER_NAMES = ["TL", "TR", "BR", "BL"]

# ── Shared state ──────────────────────────────────────────────────────────────
# Written by camera thread, read by WS handlers + debug thread.
# TODO(PR 4 follow-up): wrap _sh in a CameraSnapshot dataclass to remove
# implicit aliasing. shared.wallcast_core.snapshot.CameraSnapshot is ready.

_sh = {
    "frame": None,
    "M": None,
    "corners": None,
    "found": False,
    "manual": None,
    "hand": None,  # HandState from detector
}
_sh_lock = threading.Lock()
_cam_ready = threading.Event()
_shutdown = threading.Event()
_threads: list[threading.Thread] = []

# ── Calibration ───────────────────────────────────────────────────────────────


def load_homography() -> np.ndarray:
    M = load_homography_file(CALIBRATION_FILE)
    if M is not None:
        log.info("Calibration loaded from %s", CALIBRATION_FILE)
        return M
    log.warning(
        "No calibration file - linear scale %dx%d -> %dx%d", CAM_W, CAM_H, SCREEN_W, SCREEN_H
    )
    return linear_fallback()


# ── Coordinate transform ──────────────────────────────────────────────────────


def _xform_pt(M, x, y):
    """Backward-compatible alias for transform_point — kept for tests/external callers."""
    return transform_point(M, x, y)


# ── Camera thread ─────────────────────────────────────────────────────────────


def camera_thread(
    camera_idx: int, fallback_M: np.ndarray, debug: bool, debug_q: "queue.Queue | None"
):
    cap = cv2.VideoCapture(camera_idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        log.warning("CAP_DSHOW failed, trying default backend")
        cap = cv2.VideoCapture(camera_idx)
    if not cap.isOpened():
        log.error("Cannot open camera %d", camera_idx)
        _cam_ready.set()
        return

    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        log.info(
            "Camera %d opened: %dx%d",
            camera_idx,
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

        hand_tracker = HandTracker()
        last_corners = [None]

        while not _shutdown.is_set():
            ret, frame = cap.read()
            if not ret:
                continue
            _process_frame(
                frame, hand_tracker, fallback_M, debug_q if debug else None, last_corners
            )
    finally:
        cap.release()
        log.info("Camera released")


# ── Debug window thread — drag-to-adjust corners ──────────────────────────────


def debug_window_thread(q: queue.Queue):
    WIN = "Spells - Debug  [drag corners | a=auto | s=save | r=reset | q=quit]"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, DISP_W, DISP_H)

    sx = CAM_W / DISP_W
    sy = CAM_H / DISP_H

    def to_disp(pt):
        return (int(pt[0] / sx), int(pt[1] / sy))

    def to_cam(dx, dy):
        return [dx * sx, dy * sy]

    edit_pts = None
    drag_idx = None
    auto_mode = True
    HIT_R_CAM = 40.0

    def on_mouse(event, dx, dy, flags, param):
        nonlocal drag_idx, edit_pts, auto_mode
        cx, cy = to_cam(dx, dy)
        if event == cv2.EVENT_LBUTTONDOWN and edit_pts is not None:
            dists = [((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 for p in edit_pts]
            i = int(np.argmin(dists))
            if dists[i] < HIT_R_CAM:
                drag_idx = i
                auto_mode = False
        elif event == cv2.EVENT_MOUSEMOVE and drag_idx is not None and edit_pts is not None:
            edit_pts[drag_idx] = [cx, cy]
            with _sh_lock:
                _sh["manual"] = np.array(edit_pts, dtype=np.float32)
        elif event == cv2.EVENT_LBUTTONUP:
            drag_idx = None

    cv2.setMouseCallback(WIN, on_mouse)

    while not _shutdown.is_set():
        try:
            frame, auto_corners, hand_state = q.get(timeout=1.0)
        except queue.Empty:
            cv2.waitKey(1)
            continue
        if frame is None:
            break

        if auto_mode and auto_corners is not None:
            edit_pts = [list(p) for p in auto_corners]
        if edit_pts is None and auto_corners is not None:
            edit_pts = [list(p) for p in auto_corners]

        display = cv2.resize(frame, (DISP_W, DISP_H))

        if edit_pts is not None:
            pts_d = [to_disp(p) for p in edit_pts]
            for i in range(4):
                cv2.line(display, pts_d[i], pts_d[(i + 1) % 4], (200, 200, 200), 1)
            for i, (pd, color) in enumerate(zip(pts_d, CORNER_COLORS, strict=False)):
                is_dragged = i == drag_idx
                radius = 14 if is_dragged else 10
                cv2.circle(display, pd, radius + 3, (255, 255, 255), -1)
                cv2.circle(display, pd, radius, color, -1)
                cv2.putText(
                    display,
                    f"{i + 1} {CORNER_NAMES[i]}",
                    (pd[0] + 14, pd[1] + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    color,
                    1,
                )

        mode_label = "AUTO" if auto_mode else "MANUAL"
        mode_color = (220, 180, 50) if auto_mode else (50, 160, 255)
        bar_y = DISP_H - 52
        cv2.rectangle(display, (0, bar_y), (DISP_W, DISP_H), (20, 20, 20), -1)
        cv2.putText(
            display,
            f"Mode: {mode_label}   [a] auto   [r] reset   [s] save calibration   [q] quit",
            (10, bar_y + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            mode_color,
            1,
        )
        cv2.putText(
            display,
            "Drag numbered dots to adjust screen corners. Homography updates live.",
            (10, bar_y + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (160, 160, 160),
            1,
        )

        cv2.imshow(WIN, display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        if key == ord("a"):
            auto_mode = True
            with _sh_lock:
                _sh["manual"] = None
            log.info("Debug: auto mode")
        elif key == ord("r") and auto_corners is not None:
            edit_pts = [list(p) for p in auto_corners]
            auto_mode = True
            with _sh_lock:
                _sh["manual"] = None
            log.info("Debug: reset to auto-detected corners")
        elif key == ord("s") and edit_pts is not None:
            CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "camera_points": [[round(float(v), 2) for v in p] for p in edit_pts],
                "screen_points": SCREEN_CORNERS.tolist(),
            }
            CALIBRATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log.info("Calibration saved -> %s", CALIBRATION_FILE)
            with _sh_lock:
                _sh["manual"] = np.array(edit_pts, dtype=np.float32)

    cv2.destroyAllWindows()


# ── Phone camera receiver ─────────────────────────────────────────────────────


def _process_frame(
    frame: np.ndarray,
    hand_tracker: HandTracker,
    fallback_M: np.ndarray,
    debug_q: "queue.Queue | None",
    last_corners_ref: list,
):
    """
    Shared frame-processing logic.
    Updates _sh in-place.
    """
    with _sh_lock:
        manual = _sh["manual"]

    if manual is not None:
        corners = manual
        M = cv2.getPerspectiveTransform(corners, SCREEN_CORNERS)
        found = True
    else:
        corners = detect_screen_corners(frame)
        if corners is not None:
            M = cv2.getPerspectiveTransform(corners, SCREEN_CORNERS)
            last_corners_ref[0] = corners
            found = True
        elif last_corners_ref[0] is not None:
            corners = last_corners_ref[0]
            M = cv2.getPerspectiveTransform(corners, SCREEN_CORNERS)
            found = True
        else:
            M = fallback_M
            found = False

    # Run hand detection once per frame
    hand_state = hand_tracker.detect(frame, M if found else None)

    if hand_state.detected and log.isEnabledFor(logging.DEBUG):
        log.debug(
            "Hand detected: palm=%s  gesture=%s  orient=%s  spell=%s",
            hand_state.palm_center,
            hand_state.gesture,
            hand_state.orientation,
            hand_state.spell is not None,
        )

    with _sh_lock:
        _sh["frame"] = frame
        _sh["M"] = M
        _sh["corners"] = corners
        _sh["found"] = found
        _sh["hand"] = hand_state
    _cam_ready.set()

    if debug_q is not None:
        try:
            debug_q.put_nowait((frame, corners, hand_state))
        except queue.Full:
            pass


_ROTATE_CODES = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


async def phone_camera_handler(
    websocket, fallback_M: np.ndarray, debug_q: "queue.Queue | None", rotate: int = 0
):
    addr = websocket.remote_address
    log.info("Phone camera connected: %s  rotate=%d°", addr, rotate)
    hand_tracker = HandTracker()
    last_corners = [None]
    rotate_code = _ROTATE_CODES.get(rotate)

    try:
        async for message in websocket:
            if not isinstance(message, bytes):
                continue
            arr = np.frombuffer(message, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                log.warning("Phone camera: failed to decode JPEG (%d bytes)", len(arr))
                continue
            if rotate_code is not None:
                frame = cv2.rotate(frame, rotate_code)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _process_frame, frame, hand_tracker, fallback_M, debug_q, last_corners
            )
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log.error("Phone camera handler crashed: %s: %s", type(e).__name__, e, exc_info=True)
    finally:
        log.info("Phone camera disconnected: %s", addr)


# ── WebSocket handler ─────────────────────────────────────────────────────────


async def ws_handler(websocket, fallback_M: np.ndarray):
    addr = websocket.remote_address
    log.info("Client connected: %s", addr)
    interval = 1.0 / TARGET_FPS

    await asyncio.get_running_loop().run_in_executor(None, _cam_ready.wait, 10.0)

    try:
        while True:
            with _sh_lock:
                hand = _sh.get("hand")
                found = _sh["found"]

            payload: dict = {
                "type": "hand",
                "screen": "screen_ok" if found else "screen_lost",
            }

            if hand is not None and hand.detected:
                payload["hand"] = {
                    "palm_center": hand.palm_center,
                    "fingertips": hand.fingertips,
                    "hand_dir": hand.hand_dir,
                    "orientation": hand.orientation,
                    "gesture": hand.gesture,
                    "velocity": hand.velocity,
                }
                if hand.spell is not None:
                    payload["spell"] = hand.spell
            else:
                payload["hand"] = None

            try:
                await websocket.send(json.dumps(payload))
            except websockets.exceptions.ConnectionClosed:
                break

            await asyncio.sleep(interval)
    finally:
        log.info("Client disconnected: %s", addr)


# ── Main ──────────────────────────────────────────────────────────────────────


async def main(
    camera_idx: int,
    port: int,
    debug: bool,
    phone: bool,
    rotate: int = 0,
    localhost_only: bool = False,
):
    local_ip = get_local_ip()
    fallback_M = load_homography()

    debug_q = None
    if debug:
        debug_q = queue.Queue(maxsize=2)
        t = threading.Thread(target=debug_window_thread, args=(debug_q,), daemon=True)
        t.start()
        _threads.append(t)

    if not phone:
        t = threading.Thread(
            target=camera_thread,
            args=(camera_idx, fallback_M, debug, debug_q),
            daemon=True,
        )
        t.start()
        _threads.append(t)

    async def obs_handler(ws):
        await ws_handler(ws, fallback_M)

    async def cam_handler(ws):
        await phone_camera_handler(ws, fallback_M, debug_q, rotate)

    # Hand stream → browser (always localhost — small JSON payloads)
    # The handle is kept so the server is not garbage-collected.
    obs_server = await websockets.serve(  # noqa: F841 — handle pins lifetime
        obs_handler,
        "localhost",
        port,
        max_size=10_000,
    )

    # Phone camera input — bind depends on --localhost-only flag
    bind_host = "localhost" if localhost_only else "0.0.0.0"
    if not localhost_only:
        log.warning("=" * 60)
        log.warning("WS bound on 0.0.0.0 - any host on LAN can stream frames.")
        log.warning("Pass --localhost-only to restrict.")
        log.warning("=" * 60)
    log.info("Phone cam WS bind: %s:%d", bind_host, PHONE_CAM_PORT)

    cam_server = await websockets.serve(  # noqa: F841 — handle pins lifetime
        cam_handler,
        bind_host,
        PHONE_CAM_PORT,
        max_size=2_000_000,  # 2 MB hard cap on JPEG frames
    )

    log.info("Obstacle WS  : ws://localhost:%d", port)
    log.info("Phone cam WS : ws://%s:%d", local_ip, PHONE_CAM_PORT)
    log.info("Phone page   : http://%s:8000/phone_camera.html", local_ip)
    if phone:
        log.info("Mode: phone camera (local camera disabled)")
    else:
        log.info("Mode: local camera + phone camera accepted simultaneously")
    log.info("Browser      : http://localhost:8000")

    await asyncio.Future()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--camera", type=int, default=0, help="Local camera index")
    p.add_argument("--port", type=int, default=WS_PORT)
    p.add_argument("--debug", action="store_true", help="Show debug window")
    p.add_argument(
        "--phone", action="store_true", help="Use phone camera only (disables local camera)"
    )
    p.add_argument(
        "--rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270],
        help="Rotate phone camera frame before processing (default: 0)",
    )
    p.add_argument(
        "--localhost-only",
        action="store_true",
        help="Bind every WebSocket on 127.0.0.1 (disables phone camera)",
    )
    args = p.parse_args()
    try:
        asyncio.run(
            main(args.camera, args.port, args.debug, args.phone, args.rotate, args.localhost_only)
        )
    except KeyboardInterrupt:
        _shutdown.set()
        for t in _threads:
            t.join(timeout=2.0)
        log.info("Stopped.")
