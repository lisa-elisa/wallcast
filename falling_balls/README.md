# Falling Balls

Yellow balls fall under gravity and bounce off red paper sheets detected on a wall by a
webcam. Stick a few papers in a bowl shape and the balls collect inside.

## Architecture

```
[ webcam ]
    │
    ▼  OpenCV HSV — detects red rectangles + yellow balls
[ detector.py ]
    │
    ▼  perspective-transform to screen space
[ server.py ] ── WebSocket ws://localhost:8765
    │
    ▼
[ index.html + js/app.js ]
    │  Matter.js 0.19 — 1920×1080 canvas — yellow balls bouncing
    ▼
[ projector / second monitor ]
```

## Quick start

```powershell
pip install -r requirements.txt

# Terminal 1 — the HTTP host (run once for the whole repo)
python ..\shared\serve.py --open /falling_balls/index.html

# Terminal 2 — the detector / physics backend
python server.py
```

Move the projector window with `Win+Shift+→`, press **F11** for fullscreen, then stick red
A4 sheets on the wall.

## Calibration (optional)

Without calibration, `server.py` applies a linear camera→screen scale. That works well
enough if the webcam sits roughly head-on to the wall.

For a precise homography:

1. Open `http://localhost:8000/falling_balls/calibration.html` on the projector. You will
   see four green corner markers.
2. Run `python calibrate.py` and click the four markers in the order **TL → TR → BR → BL**.
3. Press **c** to save. The file `calibration/calibration_data.json` is written and used
   automatically on the next `server.py` start.

## Layout suggestions

```
straight shelf:   ─────────         bowl:    \         /
                                              \       /
                  one paper                     ─────
```

A bowl made from three papers (two angled sides + one flat bottom) catches the falling
balls. Add a "wall" on top to keep them in.

## Configuration

Ball physics — in `js/app.js`:

| Constant            | Default | Meaning                                       |
|---------------------|---------|-----------------------------------------------|
| `MAX_BALLS`         | 20      | Hard cap on concurrent balls (offscreen ones recycle) |
| `SPAWN_INTERVAL`    | 500 ms  | Time between spawns                           |
| `SPAWN_X`           | 1280 px | X coordinate of spawn point                   |
| `BALL_RADIUS`       | 20 px   | Visual radius                                 |
| `BALL_RESTITUTION`  | 0.62    | Bounciness (0 dead, 1 perfect)                |
| `BALL_DENSITY`      | 0.0005  | Matter.js density (light plastic)             |
| `BALL_FRICTION_AIR` | 0.008   | Air drag                                      |

Paper detection — in `detector.py`. Red wraps around 180° in HSV, so two bands are
needed (low + high):

| Constant       | Default     | Meaning                                              |
|----------------|-------------|------------------------------------------------------|
| `MIN_PAPER_AREA` | 2000 px²  | Minimum contour area to count as a paper             |
| `RED_LOWER1` / `RED_UPPER1` | H 0–10°    | Low-hue red band (HSV)                |
| `RED_LOWER2` / `RED_UPPER2` | H 160–180° | High-hue red band (HSV, wraps around) |

## Tests

```powershell
pip install pytest
pytest tests/ -v
```

## Troubleshooting

- **Browser says "backend not running"** — start `python server.py` and reload.
- **Papers not detected** — check lighting; enable debug window with `DEBUG_WINDOW = True`
  at the top of `server.py` to see the HSV mask live.
- **Coordinates feel off** — run `python calibrate.py` to compute a homography.
- **mediapipe install fails** — falling_balls does not need mediapipe; ignore.
