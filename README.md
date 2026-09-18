# World Athletics ranking "what-if" tool

Model how a hypothetical performance would change an athlete's World Athletics ranking
score and rank position. **Scope: all middle-distance events — 800m, 1500m, 5000m, 10000m,
3000m SC, men & women — for the World Ranking and "Road to Beijing 27" (2027 World
Championships: entry standard + world-ranking qualification).**

A ranking score is the **floored mean of an athlete's best N performance scores** over a
rolling window. Each performance score = **result score** (time → points, World Athletics
Scoring Tables) **+ placing score** (points for finishing position, by meet category), with
an optional age-decay deduction. N, the main-event minimum, and the window vary by event:

| Event | N | Min main | Window | Beijing 27 target field | Entry standard (M / W) |
|---|---|---|---|---|---|
| 800m  | 5 | 3 | 12 mo | 56 | 1:43.00 / 1:57.50 |
| 1500m | 5 | 3 | 12 mo | 56 | 3:30.00 / 3:58.00 |
| 5000m | 3 | 2 | 12 mo | 42 | 12:50.00 / 14:36.00 |
| 10000m | 2 | 1 | **18 mo** | 27 | 26:48.00 / 30:40.00 |
| 3000m SC | 3 | 2 | 12 mo | 36 | 8:08.00 / 9:06.50 |

(Men's 3000m SC scoring works, but its ranking *list* isn't fetchable — see Known limitations.)

## Install

```bash
pip install -r requirements.txt   # requests, python-dateutil, pytest
```

Python 3.11+ (uses `X | Y` typing).

## Quick start

```bash
python -m wa_ranking.cli events                 # list the 8 events
python -m wa_ranking.cli champs                 # world | road_to_beijing (+ archived)

# Run a scenario (fetches + caches live data on first use):
python -m wa_ranking.cli whatif --event 1500m_men   --athlete "Wightman" --time 3:28.80 --place 1
python -m wa_ranking.cli whatif --event 5000m_women --athlete "Battocletti" --time 14:30 --qualify
python -m wa_ranking.cli whatif --event 10000m_men  --athlete "..." --time 26:40 --championship world

python -m wa_ranking.cli list  --event 800m_women   # show a ranking list
python -m wa_ranking.cli fetch --event 5000m_men --force
python -m wa_ranking.cli whatif --event ... --json  # structured output (frontend-ready)
```

Defaults: `--event 1500m_men`, `--championship road_to_beijing`.

As a library:

```python
from datetime import date
from wa_ranking import what_if

result = what_if(
    "5000m_women", athlete="Battocletti", new_time="14:30.00",
    category="GW", place=1, championship="road_to_beijing",
    as_of=date(2026, 9, 18), qualify=True,
)
q = result["qualification"]
print(result["new_score"], result["new_rank"], q["route_new"], q["entry_standard"]["note"])
```

`what_if(...)` returns a structured dict (and prints an assumptions + result report unless
`verbose=False`). The dict is the contract for the web UI / Claude Design frontend.

## Web UI (online)

A **fully static site** (GitHub Pages) exposes the tool to people online. The Python engine
runs at *build* time — a weekly GitHub Action scrapes World Athletics, regenerates the data
bundle and deploys — and a line-for-line **JS port of the engine** (`web/src/engine/`) runs
the what-if math in the visitor's browser over that bundle. A golden-vector parity gate
(568 scenarios generated from the Python engine) must pass before any deploy, so the two
engines cannot drift. The two live features — name search and unranked-athlete profiles —
call World Athletics' GraphQL API directly from the browser (the endpoint is CORS-open).

```bash
# 1. Generate the static data bundle + parity vectors (reads the cache/seed; no server)
pip install -r requirements.txt
python -m scripts.build_static

# 2. Front-end
cd web && npm install && npm run dev           # http://localhost:5173
```

The old FastAPI wrapper (`wa_ranking/api.py`) still works for local use
(`uvicorn wa_ranking.api:app --reload`) and its response shapes remain the contract the
static bundle and JS engine reproduce — see **`web/CONTRACT.md`**.

**Deploy**: `.github/workflows/deploy-pages.yml` — weekly cron (Wed 06:00 UTC, after WA's
~Tuesday ranking update) re-scrapes and commits `data/cache_seed/`, and every push to `main`
rebuilds the site from the committed seed. Both paths run the Python tests + the JS/Python
parity gate, then publish `web/dist` to GitHub Pages. No server, no cost.

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
  fixed period (Road to Beijing 27: 23 Aug 2026 – 22 Aug 2027) instead of WA's rolling one;
  protected championships survive the filter. Recomputed scores then deliberately diverge
  from WA's rolling-window numbers.

## Two kinds of question: general ranking vs qualifying

- **General ranking** (default) — "what's my ranking score / rank position?" No champion, no
  caps. Use `--championship world`.
- **Qualifying for a championship** (`--qualify` / `qualify=True`) — "do I make Beijing?"
  Adds the qualification rules from `qualify.py`:
  - **Quota** — the target field (`quota` in `championships.json`; for Beijing overlaid from
    WA's own "Road to" feed).
  - **Wildcards** — the defending World Champion, the 2026 Ultimate Championship winner (and,
    from Sep 2027, the 2027 Diamond League winner) take the first slots, are **exempt from
    the country cap**, and each **consumes one place**.
  - **Entry standard** — athletes WA lists as having achieved the standard are in next,
    whatever their ranking (they still count toward the country cap). A what-if says whether
    the hypothetical mark meets the standard — main event or a listed mile/road alternative,
    never indoor, inside the window, Category C meet or above — and by how much.
  - **Per-country cap** — max **3** non-wildcard qualifiers per country across the standard
    and ranking routes. With the USA running 8-deep in the 1500m this is decisive: an
    athlete can be **blocked despite a score above the cutoff**, and improves their odds
    mainly by displacing a *compatriot*.
  - **World-ranking fill** — whatever is left of the quota, in score order.

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

- `road_to_beijing` — the **2027 World Athletics Championships** (Beijing, 10–19 Sep 2027).
  Shares the world list (`data_source: world`); qualification = entry standard + world
  rankings, 3 per country, wildcards for the defending champions and Ultimate/DL winners.
  Quota, standard, window, byes and who has the standard are overlaid weekly from WA's own
  "Road to Beijing 27" feed (`feed.py`, snapshots in `data/cache_seed/feed__*.json`).
- `world` — the **global** world ranking (all nations); pure world-ranking what-ifs (no
  quota / qualification).
- `road_to_birmingham` (2026 European Championships) and `road_to_ultimate` (2026 Ultimate
  Championship) are **archived**: still loadable for the engine and tests, hidden from the
  site and the weekly refresh.

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
  tables). **Quotas, entry standards, windows + wildcards:** World Athletics "Qualification
  System and Entry Standards – Beijing 2027" (May 2026), Tokyo 2025 and Budapest 2026
  (Ultimate) results, overlaid by WA's "Road to Beijing 27" feed (`getChampionshipQualifications`,
  competition 7216591).
- Live ranking lists + `RankingScoreCalculation` endpoint (per-athlete breakdown).
