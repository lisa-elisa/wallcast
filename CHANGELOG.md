# Changelog

All notable changes to **Wallplay** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `pyproject.toml` with `ruff` configuration; `ruff` added to `requirements-dev.txt`.
- Pre-commit hooks (`.pre-commit-config.yaml`): `ruff`, `ruff-format`, basic file hygiene.
- CI workflow now runs on a Linux × macOS × Windows matrix (Python 3.10 / 3.11 / 3.12)
  plus a separate `lint` job (`ruff check` + `ruff format --check`).
- `.github/dependabot.yml` — weekly checks for pip and GitHub Actions.
- Issue templates (`bug.yml`, `feature.yml`) and a pull-request template.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).

### Changed
- `falling_balls/requirements.txt` and `spells/requirements.txt` now use upper
  bounds on `opencv-python`, `websockets`, and `numpy` to keep CI predictable.
- `mediapipe` pinned to `==0.10.33` in `spells/requirements.txt`.

## [0.1.0] — 2026-05-11

### Added
- Initial public release of Wallplay.
- **Falling Balls** mode: OpenCV HSV detection of red paper sheets; Matter.js
  physics simulation of yellow balls bouncing off detected obstacles. Auto-detects
  the projected screen via a bright-pixel convex hull; supports manual 4-point
  calibration through `calibrate.py` and a draggable debug window.
- **Spells** mode: MediaPipe HandLandmarker (21 landmarks); gesture and palm
  orientation detection drive "spell" particle effects on the projector canvas.
  Open palm shoots streaks along the fingers; palm facing the camera releases a
  particle burst.
- Shared HTTP host (`shared/serve.py`) and a landing page (`/index.html`) that
  probes both backends and tells the user which one to launch.
- Phone-camera streaming over WebSocket from any device on the local network
  (`shared/phone_camera.html`); ADB reverse-port forwarding for USB-tethered
  phones via `spells/start.py` (Windows).
- pytest suite (28 tests; 15 for `falling_balls`, 13 for `spells` with
  MediaPipe mocked through `__new__`).
- GitHub Actions CI on Windows × Python 3.10 / 3.11 / 3.12.
- MIT License.

[Unreleased]: https://github.com/lisa-elisa/wallplay/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lisa-elisa/wallplay/releases/tag/v0.1.0
