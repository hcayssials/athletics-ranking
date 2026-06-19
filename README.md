# World Athletics ranking "what-if" tool

Model how a hypothetical performance would change an athlete's World Athletics ranking
score and rank position. **Scope: all middle-distance events — 800m, 1500m, 5000m, 10000m,
men & women — for the World Ranking and "Road to Birmingham" (2026 European Champs).**

A ranking score is the **floored mean of an athlete's best N performance scores** over a
rolling window. Each performance score = **result score** (time → points, World Athletics
Scoring Tables) **+ placing score** (points for finishing position, by meet category), with
an optional age-decay deduction. N, the main-event minimum, and the window vary by event:

| Event | N | Min main | Window | Quota (Birmingham) |
|---|---|---|---|---|
| 800m  | 5 | 3 | 12 mo | 32 |
| 1500m | 5 | 3 | 12 mo | 30 |
| 5000m | 3 | 2 | 12 mo | 25 |
| 10000m | 2 | 1 | **18 mo** | 27 |
| 3000m SC | 3 | 2 | 12 mo | 34 |

(Men's 3000m SC scoring works, but its ranking *list* isn't fetchable — see Known limitations.)

## Install

```bash
pip install -r requirements.txt   # requests, python-dateutil, pytest
```

Python 3.11+ (uses `X | Y` typing).

## Quick start

```bash
python -m wa_ranking.cli events                 # list the 8 events
python -m wa_ranking.cli champs                 # world | road_to_birmingham

# Run a scenario (fetches + caches live data on first use):
python -m wa_ranking.cli whatif --event 1500m_men   --athlete "Wightman" --time 3:28.80 --place 1
python -m wa_ranking.cli whatif --event 5000m_women --athlete "Battocletti" --time 14:30 --qualify
python -m wa_ranking.cli whatif --event 10000m_men  --athlete "..." --time 26:40 --championship world

python -m wa_ranking.cli list  --event 800m_women   # show a ranking list
python -m wa_ranking.cli fetch --event 5000m_men --force
python -m wa_ranking.cli whatif --event ... --json  # structured output (frontend-ready)
```

Defaults: `--event 1500m_men`, `--championship road_to_birmingham`.

As a library:

```python
from datetime import date
from wa_ranking import what_if

result = what_if(
    "5000m_women", athlete="Battocletti", new_time="14:30.00",
    category="GW", place=1, championship="road_to_birmingham",
    as_of=date(2026, 6, 16), qualify=True,
)
print(result["new_score"], result["new_rank"], result["qualification"]["status_new"])
```

`what_if(...)` returns a structured dict (and prints an assumptions + result report unless
`verbose=False`). The dict is the contract for the web UI / Claude Design frontend.

## Web UI (online)

A hosted web app exposes the tool to people online. Architecture: a thin **FastAPI** wrapper
(`wa_ranking/api.py`) reusing `what_if()` / `fetch_championship()` / `fetch_profile()`, and a
**React** front-end (designed in **Claude Design**) that calls it. (Claude *Artifacts* are
sandboxed — no external fetch — so the UI must be a normally-hosted site, not an artifact.)

```bash
# 1. Backend (reuses the cache; first call per event is slow, then weekly)
pip install -r requirements.txt
uvicorn wa_ranking.api:app --reload            # http://localhost:8000/api/...

# 2. Front-end (minimal working starter; restyle in Claude Design)
cd web && npm install && npm run dev           # http://localhost:5173 (proxies /api)
```

Endpoints: `GET /api/meta`, `GET /api/rankings`, `GET /api/athlete`, `POST /api/whatif`
(errors as `{"error": ...}`). **`web/CONTRACT.md`** has the exact shapes + a ready-to-paste
**Claude Design prompt** — generate the polished UI there, drop the components into `web/src`,
`npm run build`, and FastAPI serves `web/dist`.

**Deploy** (single service): the `Dockerfile` builds the React app and serves it alongside
`/api` from one container — push to Render/Fly/Railway, set optional `WA_API_KEY`, share the
URL. Note: hosts with ephemeral disk re-fetch (per the 7-day cache) on redeploy.

## How it works

### Data layer (`fetch.py`, `cache.py`) — scrape, no API key
1. The ranking list page (`/world-rankings/1500m/men`) is **server-rendered HTML**; each row
   carries a `data-id`, the athlete, nation, DOB, rank and ranking score.
2. `/WorldRanking/RankingScoreCalculation?competitorId=<data-id>` returns JSON with that
   athlete's **counting performances**, each already including `resultScore`, `placingScore`
   and `performanceScore`.
3. Everything is normalised and cached to `data/cache/*.json` (1-day TTL) so we don't hammer
   the backend. Per-athlete calls are spaced out slightly.

Because the per-performance scores come straight from World Athletics, existing performances
are **read, not recomputed** — and recomputing each athlete's ranking score from them
reproduces the official number exactly (verified for the whole top of the list).

### Scoring engine (`scoring.py`) — all numbers live in data files
- `result_score(event, time)` — looks up the event's table in `data/scoring_tables/`
  (`<event>.csv`, e.g. `5000m_women.csv`). Rule (validated against live data): a time scores
  the points of the **fastest tabulated threshold it still meets** (e.g. `3:30.11 → 1243`).
- `placing_score(category, place, group)` — `data/placing_scores.json`; `group` selects the
  table (`standard` for 800/1500, `5000m`, `10000m`). Anchors verified vs live (GW/1st = 140
  standard, 115 for 5000m, 100 for 10000m).
- `decay_deduction(months_old)` — `data/decay.json` (−20/−40/−60 at 9/10/11 months).

To support another event, drop in a new CSV and an `events.json` entry — no code changes.

### Ranking math (`ranking.py`) — the counting-set model
The `RankingScoreCalculation` endpoint returns **exactly the counting performances**: every
athlete has ≤ N of them, and `floor(mean(returned))` equals the official score for **every**
athlete on the list. So WA has *already applied* the 12-month window, the similar-events
inclusion, the ≥3-of-N main-event minimum, and the always-include-previous-championship rule.
The tool therefore **trusts the returned set** as the baseline (it does *not* re-window it —
doing so wrongly drops kept championship results) and uses `floor` of the mean (WA truncates;
plain rounding was off by 1 on ~25% of athletes).

Selection logic (`select_counting`) is used only to (a) decide what a **hypothetical** new
performance displaces, and (b) apply an optional **fixed** window. It honours:
- **Protected performances** — the previous continental championship (matched via
  `always_include_competitions`, e.g. `"European Athletics Championships"`) always counts,
  even years outside the window. WA *does* return these (e.g. Rome 2024 results), so this is
  fully data-backed — and verified to reproduce the official scores of the 8 athletes who
  carry one.
- **Main-event minimum** — at least `main_event_min` of the selection are the main event.
- **Fixed qualification window** — pass `--qual-window` to evaluate over a championship's
  fixed period (Road to Birmingham: 27 Jul 2025 – 26 Jul 2026) instead of WA's rolling one;
  protected championships survive the filter. Recomputed scores then deliberately diverge
  from WA's rolling-window numbers.

## Two kinds of question: general ranking vs qualifying

- **General ranking** (default) — "what's my ranking score / rank position?" No champion, no
  caps. Use `--championship world`.
- **Qualifying for a championship** (`--qualify` / `qualify=True`) — "do I make Birmingham?"
  Adds the qualification rules from `qualify.py`:
  - **Quota** — fixed number of qualification places (`quota` in `championships.json`).
  - **Defending-champion bye** — the reigning champion takes slot #1, is **exempt from the
    country cap**, and **consumes one place** so only `quota − 1` remain for the ranking. For
    Birmingham this is Ingebrigtsen (Rome 2024) — who isn't even in the current ranking list,
    so the bye is the only way he appears.
  - **Per-country cap** — max **3** ranking qualifiers per country (champion exempt). With
    France running 7-deep, this is decisive: a French athlete can be **blocked despite a
    score above the cutoff**, and improves their odds mainly by displacing a *compatriot*.

  The report's `QUALIFICATION` block shows the quota, champion, cap, cutoff, and whether the
  athlete is *above the cutoff & auto-confirmed*, *above the cutoff but held off by
  higher-ranked compatriots* (federation's call — the cap is a max), or *below the cutoff*.

  ```bash
  python -m wa_ranking.cli whatif --athlete "Gilavert" --time 3:30.00 --place 2 --qualify
  ```

> **Quota is the *total* field, not ranking-only.** `quota=30` (men's 1500m) comes from the
> European Athletics *"Qualification System and Entry Standards"* document's per-event target
> table (`quota_source` in `championships.json`). That 30 is the whole field, filled in
> priority order by entry-standard achievers → finishing-position qualifiers → defending-
> champion wildcard → approved unqualified → **then** world rankings. This tool currently
> treats the field as ranking-only (champion bye + 3-per-country cap), which **over-counts**
> ranking places because it doesn't yet subtract entry-standard qualifiers (men's 1500m
> standard: 3:33.50). Modelling that is the natural next step.

## Assumptions (always printed)

- Ranking score = floored mean of best 5, 12-month window.
- A hypothetical result is dated `as_of`, so **no age-decay** is applied to it. Decay applies
  only when you deliberately backdate a hypothetical (`score_performance(perf_date=...)`).
- Other athletes are **held at their current ranking scores**; only the chosen athlete moves.
- Similar events count and the ≥3-of-N main-event minimum holds — WA pre-applies both in the
  returned counting set, and `select_counting` re-applies the minimum when inserting a
  hypothetical.

## Tests & verification

```bash
python -m pytest -q          # 49 unit tests (scoring, ranking, qualification, events, profile), no network
```

Integration check (network): `python -m wa_ranking.cli fetch --force` then run a `whatif` and
compare the new score/rank against the live ranking page.

## Championships (region-level; pick the event with `--event`)

- `road_to_birmingham` — Birmingham 2026 is the **European Athletics Championships**, so the
  list is the WA ranking **filtered to European nations** (`regionType=area&region=europe`);
  ranks are European-relative. Per-event quota + defending champion (Rome 2024 winners) live
  under `events` in `championships.json`. Non-European athletes don't appear here.
- `world` — the **global** world ranking (all nations); use for non-European athletes or
  pure world-ranking what-ifs (no quota / qualification).

The URL for each `(championship, event)` is built from a template + the event's discipline
and gender, so adding an event is a `events.json` entry, not code.

## Unranked athletes (profile fallback)

The ranking page only lists ranked athletes (~top 1000). For someone **not** on it — e.g.
returning from injury — pass their World Athletics profile slug and the tool falls back to
their **profile page**, whose `__NEXT_DATA__` embeds every result with `resultScore`,
`category` and `place`. It rebuilds their counting set (computing placing scores from our
tables) and reports a *would-be* ranking:

```bash
python -m wa_ranking.cli whatif --event 1500m_men --athlete "Jake Heyward" \
    --profile jake-heyward-14597392 --time 3:35.00 --category B --place 1 --qualify
```

> Example output: "UNRANKED (best ever #10) · 3 counting results → 4 with this race, still 1
> short of a full 5 · would average 1188 · would rank ~#42 raw · **above the cutoff (1183) but
> not auto-confirmed — 8 higher-ranked Brits for 3 places, so it's GBR's call**". It also
> reports the time the race would need (before placing points) to reach the cutoff.

The slug is the last path segment of their `worldathletics.org/athletes/...` URL. Results are
pulled **per calendar year across the whole window** via the WA GraphQL
`getSingleCompetitorResultsDiscipline` query (`graphql.py`), so a counting set spanning two
seasons is captured. That endpoint needs an `x-api-key` WA rotates; the client discovers a
working key automatically (env `WA_API_KEY` → cached → seed → scraped live from the site's JS
chunks). If no key can be obtained it falls back to the profile HTML (latest season only) and
flags `incomplete_window`.

### Qualification framing (the 3-per-country cap is a *maximum*)
A country sends **up to** 3 — not necessarily its 3 highest-ranked. So for an individual the
key question is **"are you above the cutoff?"** The report states the cutoff and classifies:
*above the cutoff & auto-confirmed* (your country isn't full ahead of you), *above the cutoff
but not auto-confirmed* (eligible on merit, but N higher-ranked compatriots hold the 3 places
— **selection is the federation's call**), or *below the cutoff*. The "would rank #N" line is
the **raw score-rank**, before the cap; the cap-adjusted picture is in the QUALIFICATION block.

## Staying current (rankings update weekly)

World Athletics republishes rankings ~weekly (Tuesdays). Each `(championship, event)` is
cached to `data/cache/` with a **7-day TTL** plus the `rank_date` (the WA edition) and the
`fetched` timestamp, so:
- normal use auto-refreshes anything older than a week — matched to WA's weekly cadence to
  minimise calls;
- `--force` on any command refetches immediately;
- `python -m wa_ranking.cli refresh` refetches **every** event (good for a weekly cron run
  just after WA updates; `--championship` to limit scope);
- the printed `live rank date` tells you which weekly edition a result is based on.

Tune the cadence via `cache.DEFAULT_TTL_SECONDS` (e.g. drop to weekly), or schedule `refresh`.

## Known limitations

- **Men's 3000m steeplechase has no fetchable ranking list.** It's the one event WA doesn't
  server-render in HTML, and the only GraphQL rankings feed the tool can reach is women-only.
  So men's steeplechase *scoring* works but list-based features (rank, qualification) raise a
  clear error. Women's steeplechase works fully (via the GraphQL list fallback in `fetch.py`).
- **Quota = total field, not ranking-only** — world rankings fill what remains after entry
  standards / wildcards (see the quota note above). Modelling entry-standard qualifiers is the
  next step (the standard times are in `events.json`).
- **Placing tables are finals-only.** WA scores heats/semis with separate (lower) tables, so a
  hypothetical is always treated as a final. *Existing* round performances are read directly
  from WA, so this doesn't affect baselines — only how a hypothetical heat would be scored
  (rare). Finals tables verified against live data.
- **One baseline outlier:** Keely Hodgkinson (800m W) reproduces as 1401 vs an official 1411
  — isolated to that reigning champion across 160 athletes checked; likely a WA adjustment.
- Re-deriving age-decay of *existing* performances at a future date (needs raw uncorrected
  scores); a fully faithful fixed qualification window (needs full performance history, not
  just the counting set — `--qual-window` is a flagged approximation); the frontend itself.

## Data sources

- **Result scores:** World Athletics Scoring Tables 2025 — 800/1500/5000 from exact tables
  (`nimarion/worldathletics-scoring`), 10000m from `jchen1/iaaf-scoring-tables`. All validated
  to match live `resultScore` values (e.g. 10000m 26:50.21 → 1242).
- **Placing scores:** WA World Ranking Rules — Track & Field 2026 (standard / 5000m / 10000m
  tables). **Quotas + champions:** European Athletics "Qualification System and Entry
  Standards" (Birmingham 2026) + Rome 2024 results.
- Live ranking lists + `RankingScoreCalculation` endpoint (per-athlete breakdown).
