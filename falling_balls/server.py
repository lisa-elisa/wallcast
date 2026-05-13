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
from detector import Detector  # noqa: E402

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
    transform_points,
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

CORNER_COLORS = [(50, 220, 50), (50, 200, 255), (255, 100, 50), (180, 50, 255)]
CORNER_NAMES = ["TL", "TR", "BR", "BL"]

# ── Shared state ──────────────────────────────────────────────────────────────
# Written by camera thread, read by WS handlers + debug thread.
# TODO(PR 4 follow-up): wrap _sh in a CameraSnapshot dataclass to remove
# implicit aliasing. shared.wallcast_core.snapshot.CameraSnapshot is ready.

_sh = {
    "frame": None,  # latest camera frame (np.ndarray)
    "M": None,  # current camera→screen homography
    "corners": None,  # latest detected screen corners (4×2 float32) or None
    "found": False,  # True when screen detected this frame
    # manual override — set by debug thread, read by camera thread
    "manual": None,  # None = auto-detect; np.ndarray = use these corners
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


def transform_obstacles(obstacles, M) -> list[dict]:
    result = []
    for obs in obstacles:
        # Batch transform: 1 center + N vertices in a single cv2 call
        batch = [[obs.cx, obs.cy], *obs.vertices]
        tpts = transform_points(M, batch)
        tx, ty = float(tpts[0, 0]), float(tpts[0, 1])
        tverts = tpts[1:].tolist()
        pts = np.array(tverts, dtype=np.float32)
        rect = cv2.minAreaRect(pts)
        (_, _), (w, h), angle = rect
        if w < h:
            w, h = h, w
            angle += 90
        d = obs.to_dict()
        d.update(
            cx=round(tx, 1),
            cy=round(ty, 1),
            w=round(float(w), 1),
            h=round(float(h), 1),
            angle=round(float(angle), 2),
            vertices=[[round(x, 1), round(y, 1)] for x, y in tverts],
        )
        result.append(d)
    return result


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

        detector = Detector()
        last_corners = [None]  # mutable ref

        while not _shutdown.is_set():
            ret, frame = cap.read()
            if not ret:
                continue
            _process_frame(frame, detector, fallback_M, debug_q if debug else None, last_corners)
    finally:
        cap.release()
        log.info("Camera released")


# ── Debug window thread — drag-to-adjust corners ──────────────────────────────


def debug_window_thread(q: queue.Queue):
    """
    Shows camera feed with draggable corner handles.
    Mouse-drag any numbered dot to reposition it.
    Homography updates live in the camera thread via _sh['manual'].
    """

    WIN = "Wallcast (Falling Balls) — Debug  [drag corners | a=auto | s=save | r=reset | q=quit]"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, DISP_W, DISP_H)

    # Scale factors: display ↔ camera space
    sx = CAM_W / DISP_W
    sy = CAM_H / DISP_H

    def to_disp(pt):
        return (int(pt[0] / sx), int(pt[1] / sy))

    def to_cam(dx, dy):
        return [dx * sx, dy * sy]

    # Drag state (all in camera-space coordinates)
    edit_pts = None  # list of 4 [x, y] in cam space — what's being edited
    drag_idx = None  # 0-3 while dragging
    auto_mode = True  # follow auto-detection; False = manual

    HIT_R_CAM = 40.0  # hit radius in camera pixels

    def on_mouse(event, dx, dy, flags, param):
        nonlocal drag_idx, edit_pts, auto_mode

        cx, cy = to_cam(dx, dy)

        if event == cv2.EVENT_LBUTTONDOWN and edit_pts is not None:
            dists = [((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 for p in edit_pts]
            i = int(np.argmin(dists))
            if dists[i] < HIT_R_CAM:
                drag_idx = i
                auto_mode = False  # entering manual mode on first drag

        elif event == cv2.EVENT_MOUSEMOVE and drag_idx is not None:
            edit_pts[drag_idx] = [cx, cy]
            # Push live update to camera thread
            with _sh_lock:
                _sh["manual"] = np.array(edit_pts, dtype=np.float32)

        elif event == cv2.EVENT_LBUTTONUP:
            drag_idx = None

    cv2.setMouseCallback(WIN, on_mouse)

    # ── Main display loop ─────────────────────────────────────────────────────
    while not _shutdown.is_set():
        # Get latest frame + detected corners from camera thread
        try:
            frame, auto_corners = q.get(timeout=1.0)
        except queue.Empty:
            cv2.waitKey(1)
            continue
        if frame is None:
            break

        # In auto mode, keep edit_pts in sync with detection
        if auto_mode and auto_corners is not None:
            edit_pts = [list(p) for p in auto_corners]

        # First frame: initialise edit_pts if still None
        if edit_pts is None and auto_corners is not None:
            edit_pts = [list(p) for p in auto_corners]

        # ── Draw ─────────────────────────────────────────────────────────────
        display = cv2.resize(frame, (DISP_W, DISP_H))

        # Red paper overlay (lightweight — just bboxes from the overlay drawn
        # by draw_debug_overlay in camera thread if we want it; skipped here
        # since we're drawing just the corner handles)

        if edit_pts is not None:
            pts_d = [to_disp(p) for p in edit_pts]

            # Quad outline
            for i in range(4):
                cv2.line(display, pts_d[i], pts_d[(i + 1) % 4], (200, 200, 200), 1)

            # Corner handles
            for i, (pd, color) in enumerate(zip(pts_d, CORNER_COLORS, strict=False)):
                is_dragged = i == drag_idx
                radius = 14 if is_dragged else 10
                cv2.circle(display, pd, radius + 3, (255, 255, 255), -1)  # white halo
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

        # Status bar
        mode_label = "AUTO" if auto_mode else "MANUAL"
        mode_color = (50, 200, 50) if auto_mode else (50, 160, 255)
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
            # Return to auto mode — clear manual override
            auto_mode = True
            with _sh_lock:
                _sh["manual"] = None
            log.info("Debug: auto mode")

        elif key == ord("r") and auto_corners is not None:
            # Reset edit_pts to last auto-detected position
            edit_pts = [list(p) for p in auto_corners]
            auto_mode = True
            with _sh_lock:
                _sh["manual"] = None
            log.info("Debug: reset to auto-detected corners")

        elif key == ord("s") and edit_pts is not None:
            # Save current corners as calibration file
            CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "camera_points": [[round(float(v), 2) for v in p] for p in edit_pts],
                "screen_points": SCREEN_CORNERS.tolist(),
            }
            CALIBRATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log.info("Calibration saved -> %s", CALIBRATION_FILE)
            # Keep manual corners active so server keeps using them
            with _sh_lock:
                _sh["manual"] = np.array(edit_pts, dtype=np.float32)

    cv2.destroyAllWindows()


# ── Phone camera receiver ─────────────────────────────────────────────────────


def _process_frame(
    frame: np.ndarray,
    detector: Detector,
    fallback_M: np.ndarray,
    debug_q: "queue.Queue | None",
    last_corners_ref: list,
):
    """
    Shared frame-processing logic used by both camera_thread and phone handler.
    Updates _sh in-place.
    """
    with _sh_lock:
        manual = _sh["manual"]

    if manual is not None:
        corners = manual
        M = cv2.getPerspectiveTransform(corners, SCREEN_CORNERS)
        found = True
    else:
        corners = detector.detect_screen_corners(frame)
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

    with _sh_lock:
        _sh["frame"] = frame
        _sh["M"] = M
        _sh["corners"] = corners
        _sh["found"] = found
    _cam_ready.set()

    if debug_q is not None:
        try:
            debug_q.put_nowait((frame, corners))
        except queue.Full:
            pass


async def phone_camera_handler(websocket, fallback_M: np.ndarray, debug_q: "queue.Queue | None"):
    """
    Receives JPEG frames (binary) from phone_camera.html via WebSocket.
    Decodes and processes them exactly like camera_thread does.
    """
    addr = websocket.remote_address
    log.info("Phone camera connected: %s", addr)
    detector = Detector()
    last_corners = [None]  # mutable ref for _process_frame

    try:
        async for message in websocket:
            if not isinstance(message, bytes):
                continue
            arr = np.frombuffer(message, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            # Run CPU-heavy work in executor to not block the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _process_frame, frame, detector, fallback_M, debug_q, last_corners
            )
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        log.info("Phone camera disconnected: %s", addr)


# ── WebSocket handler ─────────────────────────────────────────────────────────


async def ws_handler(websocket, fallback_M: np.ndarray):
    addr = websocket.remote_address
    log.info("Client connected: %s", addr)
    detector = Detector()
    interval = 1.0 / TARGET_FPS

    await asyncio.get_running_loop().run_in_executor(None, _cam_ready.wait, 10.0)

    try:
        while True:
            with _sh_lock:
                frame = _sh["frame"].copy() if _sh["frame"] is not None else None
                M = _sh["M"] if _sh["M"] is not None else fallback_M
                corners = _sh["corners"]
                found = _sh["found"]

            if frame is not None:
                roi_mask = (
                    detector.build_screen_mask(frame, corners) if corners is not None else None
                )
                obstacles = detector.detect_red_papers(frame, roi_mask)
                payload = transform_obstacles(obstacles, M)
                status = "screen_ok" if found else "screen_lost"
            else:
                payload = []
                status = "no_camera"

            try:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "obstacles",
                            "obstacles": payload,
                            "screen": status,
                        }
                    )
                )
            except websockets.exceptions.ConnectionClosed:
                break

            await asyncio.sleep(interval)
    finally:
        log.info("Client disconnected: %s", addr)


# ── Main ──────────────────────────────────────────────────────────────────────


async def main(camera_idx: int, port: int, debug: bool, phone: bool, localhost_only: bool = False):
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
        await phone_camera_handler(ws, fallback_M, debug_q)

    # Obstacle stream → browser (always localhost — small JSON payloads)
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
        "--localhost-only",
        action="store_true",
        help="Bind every WebSocket on 127.0.0.1 (disables phone camera)",
    )
    args = p.parse_args()
    try:
        asyncio.run(main(args.camera, args.port, args.debug, args.phone, args.localhost_only))
    except KeyboardInterrupt:
        _shutdown.set()
        for t in _threads:
            t.join(timeout=2.0)
        log.info("Stopped.")
