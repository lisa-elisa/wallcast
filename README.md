# Wallplay

Two interactive AR projection installations sharing the same camera-to-browser pipeline.
Point a webcam (or a phone over WiFi) at a wall, run the Python backend, and project the
browser canvas onto the wall.

![tests](https://github.com/lisa-elisa/wallplay/actions/workflows/test.yml/badge.svg)

## The two modes

| Mode | Detects | Visualisation |
|------|---------|---------------|
| **[Falling Balls](falling_balls/)** | red paper sheets (OpenCV HSV) | yellow balls fall under gravity (Matter.js) and bounce off the papers; a bowl-shape collects them |
| **[Spells](spells/)** | hand landmarks (MediaPipe) | open palm releases beams of light; palm facing camera bursts glowing particles |

## Architecture

```
[ webcam / phone-over-WiFi ]
            │
            ▼  OpenCV / MediaPipe
   [ <mode>/server.py ]
            │  WebSocket ws://localhost:8765
            ▼
   [ browser canvas — projected on the wall ]
```

`shared/serve.py` is a thin HTTP server that hosts everything on `http://localhost:8000/`.
Open the root URL and pick a mode from the landing page.

## Quick start

```powershell
# Install dependencies for whichever mode you want
pip install -r falling_balls/requirements.txt
pip install -r spells/requirements.txt   # optional, downloads ~200 MB mediapipe

# Run the HTTP host (one terminal)
python shared/serve.py

# Run the backend for the mode you want (second terminal)
python falling_balls/server.py
# or:  python spells/server.py
# or:  double-click spells/start.bat
```

Open <http://localhost:8000/> in the browser, pick a mode. The landing page tells you if
the backend for that mode is running.

Phone camera: any phone on the same WiFi can stream as the camera by visiting
`http://<your-pc-ip>:8000/shared/phone_camera.html`.

## Repo layout

```
.
├── index.html              # landing page (mode picker)
├── shared/                 # HTTP server + phone-camera page + firewall helper
├── falling_balls/          # OpenCV color detection + Matter.js physics
├── spells/            # MediaPipe hand tracking + particles
└── .github/workflows/      # pytest CI on Windows
```

## Requirements

- **Windows 10 / 11** (the launcher scripts are PowerShell / .bat — Linux/macOS untested)
- Python 3.10+
- A webcam, or an Android phone on the same WiFi (optionally USB + ADB for lower latency)
- A projector or a second 1920×1080 monitor

## License

[MIT](LICENSE)
