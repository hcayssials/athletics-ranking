# Web API contract + Claude Design brief

The front-end is a normal deployed website (designed in Claude Design) that calls this JSON
API. In production the API and the built UI are served from the **same origin** (FastAPI mounts
`web/dist` at `/`), so requests are just `fetch('/api/...')`. In local dev the API runs on
`http://localhost:8000`.

> Errors always come back as `{"error": "<message>"}` with an HTTP 4xx status. Show the message.

---

## Endpoints

### `GET /api/meta`
Selectors + reference data. Response:
```json
{
  "events": [
    {"key":"1500m_men","label":"Men's 1500m","gender":"men","best_n":5,
     "main_event_min":3,"window_months":12,"entry_standard":"3:33.50"}
  ],
  "championships": [
    {"key":"world","label":"World Ranking"},
    {"key":"road_to_birmingham","label":"Road to Birmingham (2026 European Athletics Championships)"}
  ],
  "categories": ["OW","DF","GW","GL","A","B","C","D","E","F"]
}
```
- `categories` populate the meet-category dropdown (OW=Olympics/Worlds … F=local). Default `GW`.
- 10 events. Note: `3000mSC_men` rankings are unavailable (see below) — keep it selectable for
  scoring but expect a 400 from `/api/rankings`.

### `GET /api/rankings?championship=&event=&limit=`
The ranking list (slim rows for the table + athlete picker). Response:
```json
{
  "championship":"road_to_birmingham","event":"1500m_men","rank_date":"2026-06-16",
  "quota":30,"defending_champion":{"name":"Jakob INGEBRIGTSEN","country":"NOR"},
  "athletes":[
    {"rank":1,"name":"Isaac NADER","country":"POR","ranking_score":1368.0,
     "competitor_id":"131203609","slug":"/athletes/portugal/isaac-nader-14756630"}
  ]
}
```
- `rank_date` = "last ranking update" for the assumptions panel.
- Use `name` values to populate the what-if athlete autocomplete.

### `GET /api/athlete?championship=&event=&name=`
One athlete incl. their counting `performances` (date, competition, category, place, mark,
result_score, placing_score, performance_score). For a detail/expand view.

### `POST /api/whatif`
Body (only `event`, `athlete`, `time` required):
```json
{"event":"1500m_men","athlete":"Wightman","time":"3:28.80","category":"GW","place":1,
 "championship":"road_to_birmingham","as_of":"2026-06-16","qualify":true,
 "qualification_window":false,"profile":null}
```
- `profile`: a WA profile slug (e.g. `"jake-heyward-14597392"`) for an **unranked** athlete not
  in the list. When used, the response includes a non-null `profile_summary`.
- Response (trimmed — `*_counting` arrays hold the counting performances; `assumptions.notes`
  is a string list to show as fine print):
```json
{
  "athlete":"Jake WIGHTMAN","country":"GBR","event":"1500m_men","rank_date":"2026-06-16",
  "assumptions":{"best_n":5,"window_months":12,"window_kind":"rolling",
    "category":"GW","place":1,"placing_edition":"2026","notes":["..."]},
  "hypothetical_performance":{"time":"3:28.80","result_score":1262,"placing_score":140,
    "decay":0,"performance_score":1402},
  "official_ranking_score":1320.0,"recomputed_old_score":1320,
  "new_score":1350,"score_delta":30,"new_perf_counts":true,
  "old_rank":4,"new_rank":4,"rank_delta":0,
  "old_counting":[{"performance_score":1417,"mark":"3:34.12","category":"OW","place":2,"date":"2025-09-17"}],
  "new_counting":[{"performance_score":1402,"mark":"3:28.80","category":"GW","place":1,"date":"2026-06-16","hypothetical":true}],
  "qualification":{"quota":30,"quota_is_total_field":true,"max_per_country":3,
    "defending_champion":{"name":"Jakob INGEBRIGTSEN","country":"NOR"},
    "is_defending_champion":false,"cutoff_score":1183.0,"above_cutoff":true,
    "status_new":"qualified","qual_position_new":5,"country_count":3,"country_ahead":0},
  "profile_summary":null
}
```
- `qualification` (present only when `qualify:true`): show `cutoff_score`, and the status —
  **above the cutoff & auto-confirmed** (`above_cutoff && status_new=="qualified"`), **above the
  cutoff but held off** (`above_cutoff && country_ahead>0` ⇒ "eligible on score; N higher-ranked
  compatriots for {max_per_country} places — the federation's call"), or **below the cutoff**.
  `is_defending_champion` ⇒ "qualifies by bye."
- `profile_summary` (present only for unranked, via `profile`): `{ranked, best_rank,
  counting_now, counting_with_new, short_of_full_set, required_time, target_label,
  target_score, incomplete_window}` — render the "currently unranked (best ever #X) · N
  counting results, M short of a full set · would average {new_score} · would rank #{new_rank}
  raw · to reach the {target_label} ({target_score}) needs ~{required_time}" narrative.

---

## Claude Design prompt (paste this)

> Build a clean, single-page React app for a **World Athletics ranking "what-if" calculator**.
> It calls a JSON API at the same origin (`/api/...`); shapes are in this contract. Layout:
>
> 1. **Top bar / controls:** dropdowns for Championship (`/api/meta` championships), Event
>    (events; show gender), and meet Category (categories, default GW). On change, fetch
>    `/api/rankings`.
> 2. **Assumptions panel** (small card): "Best {best_n} of {window_months} mo · Quota {quota}
>    · Defending champion {defending_champion.name} · Last ranking update {rank_date}."
> 3. **Rankings table** (left/main): sortable columns Rank, Athlete, Country, Score from
>    `/api/rankings`. Clicking a row fills the athlete in the what-if form.
> 4. **What-if panel** (right/side): athlete autocomplete (or a checkbox "athlete not ranked"
>    that reveals a WA profile-slug input → sends `profile`); inputs for Time (e.g. 3:28.80),
>    Place (number), Category; toggles "Resolve qualification" (`qualify`) and "Fixed
>    qualification window" (`qualification_window`). A **Run** button POSTs `/api/whatif`.
> 5. **Result card:** big "{official_ranking_score} → {new_score}" and "Rank {old_rank} →
>    {new_rank}"; a Qualification block using the `above_cutoff` / `country_ahead` /
>    `is_defending_champion` logic above and the cutoff; the hypothetical breakdown
>    (result + placing = performance score); and the **counting performances** list
>    (`new_counting`) with the `hypothetical:true` row highlighted. If `profile_summary` is
>    present, show the unranked narrative instead of old→new.
> 6. **Errors:** show `error` message inline (e.g. men's steeplechase list unavailable;
>    athlete not found).
>
> Keep it responsive, neutral/athletics-clean styling, no backend assumptions beyond the
> documented endpoints. Use only fetch (no extra services).

After Claude Design generates the components, copy them into `web/src/`, run `npm run build`,
and FastAPI will serve `web/dist`.
