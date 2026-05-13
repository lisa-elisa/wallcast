# Wallcast

Stick paper to a wall. Point a webcam at it. Watch physics happen.

Two camera-driven wall projections sharing the same Python-to-browser pipeline — one
bounces yellow balls off red paper sheets, the other shoots glowing particles from your
hand. Webcam or phone (over WiFi), projector, and a browser is all you need.

[![tests](https://github.com/lisa-elisa/wallcast/actions/workflows/test.yml/badge.svg)](https://github.com/lisa-elisa/wallcast/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!--
  Hero media: drop two short clips (≤ 5 s, ≤ 1 MB each) into docs/media/
  and uncomment the block below. WebM/MP4 work via <video>; GIFs render
  inline on github.com.

  <p align="center">
    <video src="docs/media/falling-balls.webm" autoplay muted loop playsinline width="48%"></video>
    <video src="docs/media/hand-sparks.webm"   autoplay muted loop playsinline width="48%"></video>
  </p>
-->


## The two modes

| Mode | Detects | Visualisation |
|------|---------|---------------|
| **[Falling Balls](falling_balls/)** | red paper sheets (OpenCV HSV) | yellow balls fall under gravity (Matter.js) and bounce off the papers; a bowl-shape collects them |
| **[Spells](spells/)** | hand landmarks (MediaPipe) | open palm shoots streaks along the fingers; palm facing the camera releases a burst of glowing particles |

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
pip install -r spells/requirements.txt   # optional; pulls ~200 MB MediaPipe wheel,
                                              # plus an 8 MB model fetched on first run

# Run the HTTP host (one terminal)
python shared/serve.py

# Run the backend for the mode you want (second terminal)
python falling_balls/server.py
# or:  python spells/server.py
# or:  double-click spells/start.bat
```

Open <http://localhost:8000/> in the browser, pick a mode. The landing page tells you if
the backend for that mode is running. Only one mode at a time — both bind WebSocket port
`8765`.

Phone camera: any phone on the same WiFi can stream as the camera by visiting
`http://<your-pc-ip>:8000/shared/phone_camera.html`.

## Security notes

By default both backends bind WebSocket port `8766` (phone camera) on `0.0.0.0`, so any
device on the same LAN can stream frames. That is intentional — the phone-camera flow
relies on it. On untrusted networks pass `--localhost-only` to either `server.py` to
restrict every bind to `127.0.0.1`.

## Repo layout

```
.
├── index.html              # landing page (mode picker)
├── shared/                 # HTTP server, phone-camera page, wallcast_core/, JSON-schema
├── falling_balls/          # OpenCV color detection + Matter.js physics
├── spells/            # MediaPipe hand tracking + particles
├── docs/media/             # hero clips (added separately, see CONTRIBUTING)
└── .github/workflows/      # pytest + ruff CI on Ubuntu / macOS / Windows
```

## Requirements

- **Windows 10 / 11** (the launcher scripts are PowerShell / .bat — Linux/macOS untested)
- Python 3.10+
- A webcam, or an Android phone on the same WiFi (optionally USB + ADB for lower latency)
- A projector or a second 1920×1080 monitor

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and PR workflow, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the community standards.

## License

[MIT](LICENSE) — see [CHANGELOG.md](CHANGELOG.md) for release notes.
