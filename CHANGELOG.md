# Changelog

All notable changes to **Wallcast** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [0.1.0] — 2026-05-11

First tagged release. The repository was already public for a few iterations
before this point; v0.1.0 captures the state after the initial polish pass
(PR 1–5).

### Added

**Modes:**
- **Falling Balls** — OpenCV HSV detection of red paper sheets; Matter.js
  physics simulates yellow balls bouncing off the detected obstacles. Auto-
  detects the projected screen via a bright-pixel convex hull; supports
  manual 4-point calibration through `calibrate.py` and a draggable debug
  window.
- **Spells** — MediaPipe HandLandmarker (21 landmarks); gesture
  (`fist`/`open`) plus palm orientation drive a "spell" particle system on the
  projector canvas. Open palm shoots streaks along the fingers; palm facing
  the camera releases a particle burst.

**Shared:**
- HTTP host (`shared/serve.py`) and a landing page (`/index.html`) that probes
  both backends and tells the user which one to launch.
- Phone-camera streaming over WebSocket from any device on the local network
  (`shared/phone_camera.html`); ADB reverse-port forwarding for USB-tethered
  phones via `spells/start.py` (Windows).
- `shared/wallcast_core/` package consolidates common code:
  `config.py` (screen/camera/port constants), `netutil.py` (`get_local_ip`),
  `homography.py` (batch-vectorised `transform_points`, `load_homography_file`,
  linear fallback), `snapshot.py` (frozen `CameraSnapshot` dataclass).
- `shared/protocol.schema.json` — JSON Schema (draft-07) documenting the
  obstacles / hand WebSocket payloads for external bridges and the future
  browser playground.

**Quality and security:**
- Graceful shutdown with `threading.Event` + `cap.release()` in both servers.
- `--localhost-only` CLI flag on both backends; phone-camera bind defaults
  to `0.0.0.0` with a startup warning (documented under README → Security
  notes).
- WebSocket size caps: 2 MB for incoming JPEG frames, 10 KB for outgoing
  JSON payloads.
- Atomic, timed download of the MediaPipe model into a `.part` file then
  `os.replace`.
- 28-test pytest suite (15 `falling_balls`, 13 `spells`); MediaPipe
  mocked via `__new__` so `spells` tests do not need the model.
- `ruff check` + `ruff format` clean across the tree; configured via
  `pyproject.toml` with a curated rule set and per-file ignores for tests.

**Infrastructure:**
- GitHub Actions CI: separate `lint` job (Ubuntu) plus a test matrix of
  Ubuntu × macOS × Windows × Python 3.10 / 3.11 / 3.12. `libgl1` installed
  on Linux for OpenCV; MediaPipe install is best-effort per matrix cell.
- Pre-commit config (`ruff`, `ruff-format`, `end-of-file-fixer`, file checks).
- Dependabot (weekly) for pip and GitHub Actions.
- Issue templates (`bug.yml`, `feature.yml`) and a pull-request template.
- `CONTRIBUTING.md`; `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- `docs/media/` placeholder for hero clips.

### Changed

- README hero rewritten in three short imperative sentences; promotional wording trimmed from
  public copy. MediaPipe sizing
  clarified (wheel vs model). `BALL_COUNT` and `BALL_SPAWN_X` table entries
  fixed; `RED_LOWER1/UPPER1` and `RED_LOWER2/UPPER2` documented as two HSV
  bands. `spells` "spell" wording tied to `spell_orientation` in
  `detector.py`.
- All public-facing text on three pages switched from `lang="ru"` to `lang="en"`;
  `phone_camera.html` and `spells/start.py` user-facing strings localised
  to English.
- Legacy product-name wording cleared from six title-bars and docstrings
  (the `BallCatcher` class name kept intentionally — see PR 1 notes).
- `falling_balls/js/app.js` now an ES module with `export class BallCatcher`,
  guarded by a `MAX_BALLS = 20` cap and a `document.hidden` spawn-skip.
- `logging.basicConfig` no longer reopens `sys.stdout.fileno()` — fixes
  `CREATE_NO_WINDOW` subprocess crashes on Windows and lets the test suite
  drop its monkeypatch workaround.
- `falling_balls/server.transform_obstacles` now uses a single batch
  `cv2.perspectiveTransform` per obstacle (centre + four vertices in one
  call), shaving ~1 ms per frame at typical paper counts.
- `requirements.txt` upper-bounds `opencv-python`, `websockets`, `numpy`;
  `mediapipe==0.10.33` pinned exactly.

### Fixed

- Removed the `_process_frame._saved` hack that wrote `debug_frame.jpg` to
  the repo on the first frame (`spells/server.py`).
- Per-frame `log.info("Hand detected: …")` demoted to `log.debug` and gated
  by `isEnabledFor`.
- Fake MediaPipe docstring in `falling_balls/detector.py` removed (no
  `import mediapipe` in this file).
- `asyncio.get_event_loop()` calls swapped for `get_running_loop()` (3 sites)
  to silence the Python 3.12 DeprecationWarning.

[Unreleased]: https://github.com/5theobytes/wallcast/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/5theobytes/wallcast/releases/tag/v0.1.0
