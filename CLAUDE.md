# CLAUDE.md

Guidance for working in this repo. Read this first; it captures the non-obvious bits.

## What this is
A World Athletics ranking **what-if** tool. Pick an athlete on a ranking list (or an unranked
one via their WA profile), enter a hypothetical performance, and see the new ranking score,
rank, and Birmingham qualification status. Also a **reverse solver**: the time needed to reach
the cutoff / #1.

- **Backend:** Python package `wa_ranking/` (FastAPI in `api.py`).
- **Frontend:** React + Vite in `web/` (single file `web/src/App.jsx`, inline CSS-in-JS).
- **Data:** scraped from World Athletics, cached in `data/cache/*.json`.

## Run / test / build
```bash
# Backend (instant boot against cached data):
PREWARM=off python3 -m uvicorn wa_ranking.api:app --port 8077
# Frontend dev (proxies /api to :8000 — adjust or run backend on 8000):
cd web && npm run dev
# Python tests (fast, no network):
python3 -m pytest -q
# Frontend build (always do this before committing FE changes):
cd web && npm run build
# Frontend logic tests (pure parts run first; live-data part needs a backend at :8077):
cd web && node src/parse.test.mjs
```
There is **no JS test runner** (vitest/jest). `parse.js` has the only JS tests, run via `node`.

## Deploy
Push to `main` → **Railway** auto-redeploys (single Docker image: FastAPI serves `/api/*` + the
built UI). `web/dist/` and `data/cache/*.json` are gitignored. `~/.local/bin` (gh, node) is NOT
on PATH — prefix shell commands with `export PATH="$HOME/.local/bin:$PATH"`. If `git push` errors
with "could not read Username", run `gh auth setup-git` once, then push.

## Cache & seed (why first load is fast)
The live cache is ephemeral. A committed warm snapshot in `data/cache_seed/` is baked into the
image; `cache.read()` falls back to it when the live cache is cold. `api.py:_prewarm()`
force-refreshes live data on boot. A weekly GitHub Action (`.github/workflows/refresh-seed.yml`)
regenerates the seed and pushes (also runnable manually: `python -m scripts.refresh_seed`).

## Landmines (read before changing these)
- **Discipline codes must match WA's real data.** `data/events.json` `main_event_codes` /
  `similar_event_codes` must equal the `disciplineCode` values WA returns. Steeple uses
  `3KSC`/`2KSC` (NOT `3000mSC`). A mismatch silently breaks the main-event-minimum rule.
- **Continental-championship results are window-exempt, not undisplaceable.** In
  `ranking.py:select_counting`, a previous European/area result survives the date window but a
  better score still displaces it. Don't reinstate force-keeping.
- **`fetch.py`, `profile.py`, `graphql.py` are network-only and the riskiest code.** Two
  production bugs came from refactoring them blind (a dropped `datetime` import; a wrong slug).
  They're now covered by **no-network mock tests** (`tests/test_fetch.py`,
  `tests/test_profile_fetch.py`) — keep/extend those when touching this layer.
- **The WA-returned set is already the counting set** (≤ best_n). Baseline `ranking_score` must
  equal WA's published score — verify with a recompute spot-check after selection changes.

## Conventions
- **Palette lives in `web/src/theme.js`** ("WA Editorial": white surfaces, cool ink, WA-red
  accent). Some incidental shades are still inline in `App.jsx` inside composite strings.
- **Responsive** via the `useIsNarrow` hook (CSS-in-JS can't use media queries).
- Shared UI: `PerfTable` (counting performances) and `TargetRows` (reverse-solver targets) are
  used by both the what-if result and the click-to-preview card (`AthletePreview`).
- **Claude cannot see the rendered UI.** Verify FE changes with `npm run build`, then ask the
  user to eyeball after the Railway redeploy.
- Keep changes small and commit per logical change; only push when asked (push = deploy).

## Map
`api.py` routes → `whatif.py` (`what_if`, `required_targets`) → `ranking.py` (best-N selection),
`scoring.py` (time↔score), `qualify.py` (quota + 3-per-country cap + champion bye),
`fetch.py`/`profile.py`/`graphql.py` (data), `config.py`/`cache.py` (loading). Frontend:
`App.jsx` (everything), `parse.js` (NL query + helpers), `api.js` (fetch), `theme.js` (palette).
