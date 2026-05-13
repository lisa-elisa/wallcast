# Contributing to Wallcast

Thanks for your interest. This is a small two-mode wall-projection project — bug
reports, polish, and new modes are all welcome.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

```bash
git clone https://github.com/5theobytes/wallcast.git
cd wallcast

# Install runtime deps for whichever mode you want
pip install -r falling_balls/requirements.txt
pip install -r spells/requirements.txt   # pulls MediaPipe wheel

# Install dev tooling (pytest, ruff)
pip install -r requirements-dev.txt

# Optional but recommended — enables ruff + file-hygiene checks on every commit
pre-commit install
```

## Running the project locally

Open one terminal for the HTTP host:

```bash
python shared/serve.py
```

Open a second terminal for the mode you are working on:

```bash
python falling_balls/server.py     # or spells/server.py
```

Then browse to <http://localhost:8000/>.

The landing page probes the WebSocket port and tells you whether the backend
is running.

## Tests

Run each subproject's tests separately — both define their own `detector` and
`server` modules, so pytest's module cache gets confused if you mix them in one
session:

```bash
pytest falling_balls/tests/ -v
pytest spells/tests/ -v
```

The `spells` tests mock MediaPipe via `__new__`, so they do not need the
8 MB model or network access.

## Lint and format

```bash
ruff check .
ruff format --check .
```

CI runs both on every PR.

## Pull-request workflow

1. Branch off `main`. Branch names are free-form; something like
   `fix/typo-in-readme` or `feat/audio-reactive` is fine.
2. Make focused commits — a single PR ideally addresses one concern.
3. Run `ruff check .`, `ruff format .`, and the relevant pytest suite before
   pushing.
4. Open a PR against `main`. CI will run lint + the test matrix
   (Ubuntu / macOS / Windows × Python 3.10–3.12).
5. PRs are usually squash-merged so commit history on `main` stays linear.

If the change is visible (UI, README), drop a screenshot or short GIF in the PR
description — a few seconds of video says more than a paragraph for this kind
of project.

## What's good to work on

- Anything labelled `good first issue` or `help wanted` on the issue tracker.
- Documentation polish — typos, clearer phrasing, missing notes about gotchas.
- Cross-platform fixes — the launcher scripts are Windows-flavoured today; a
  Linux/macOS path would land cleanly.
- New ideas — open a Discussion first if you want a sanity-check before
  building.

## What to expect from a maintainer

Reviews aim for within a week, but this is a side-project so depth varies. A
clear PR description, a working CI run, and a short test plan get you faster
feedback.
