# Spells

Camera tracks your hand. Open palm releases beams of light along the fingers; turn the
palm to face the camera and the spell bursts into a cloud of glowing particles.

## Architecture

```
[ webcam or phone ]
        │
        ▼  MediaPipe HandLandmarker (21 landmarks)
[ detector.py ]
        │  gesture (fist/open) + orientation + spell charge
        ▼
[ server.py ] ── WS :8765 (hand data) ── ▶ [ browser / js/app.js ]
                 ▲                              │
                 │ WS :8766 (JPEG frames)       ▼
                 └── phone_camera.html      Canvas particles
```

| Port  | Service                         | Bind          |
|-------|---------------------------------|---------------|
| 8000  | HTTP host (`shared/serve.py`)   | `0.0.0.0`     |
| 8765  | WS — hand pose to browser       | `localhost`   |
| 8766  | WS — JPEG frames from phone     | `0.0.0.0`     |

## Quick start

```powershell
pip install -r requirements.txt
```

Then double-click **`start.bat`** — it runs the HTTP host (`shared/serve.py`), spawns the
WS backend (`server.py --phone --debug`), and opens the browser automatically. Close the
console window to stop everything.

For a rotated phone frame:

```powershell
python start.py --rotate 180
```

Manual run (two terminals):

```powershell
# Terminal 1
python ..\shared\serve.py --open /spells/index.html

# Terminal 2 — pick one
python server.py --debug                       # local webcam + debug window
python server.py --phone --debug               # phone-only
python server.py --phone --debug --rotate 180  # phone with rotated frame
```

The MediaPipe model `hand_landmarker.task` (~8 MB) downloads automatically on first run.
If your network blocks Google Storage, grab it manually and put it next to `detector.py`:

```
https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

## Phone as a camera

### Over WiFi
On the phone, open `http://<pc-ip>:8000/shared/phone_camera.html`. The PC's IP is printed
by `shared/serve.py` on startup.

### Over USB (lower latency, requires Android + ADB)
```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb reverse tcp:8000 tcp:8000
& $adb reverse tcp:8766 tcp:8766
```

`start.bat` does this automatically every 10 seconds when ADB is present.

Then on the phone open `http://localhost:8000/shared/phone_camera.html` — `localhost` is
tunneled to the PC via ADB. Status on the page should turn green ("Подключено — стриминг").

## Screen calibration

`calibration/calibration_data.json` stores four homography points (projector corners → screen
corners). Use the debug window (`--debug`):

| Key | Action |
|-----|--------|
| drag | move a corner manually |
| `a` | auto-detect via bright contour |
| `s` | save current corners to file |
| `r` | reset to auto-detected corners |
| `q` | close the window |

## Diagnostics

```powershell
# Ports listening?
netstat -ano | findstr "8765 8766 8000"

# ADB reverse rules
& $adb reverse --list

# Available cameras
python -c "import cv2; [print(f'Cam {i}: {int(cv2.VideoCapture(i, cv2.CAP_DSHOW).get(3))}x{int(cv2.VideoCapture(i, cv2.CAP_DSHOW).get(4))}') for i in range(5) if cv2.VideoCapture(i, cv2.CAP_DSHOW).isOpened()]"
```

## Tests

```powershell
pip install pytest
pytest tests/ -v
```

MediaPipe is mocked, so tests run without the 8 MB model.

## Known quirks

- **Camera 0 opens at 640×480** even when 1280×720 is requested — DSHOW warning is normal.
- **ADB reverse resets** when the cable is reconnected; the watchdog in `start.py` re-runs
  it every 10 s.
- **Port 8765 busy** on re-launch → `taskkill /PID <pid> /F` or close the previous console.
