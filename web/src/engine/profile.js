// Port of wa_ranking/profile.py for the browser — the unranked-athlete path.
// One deliberate difference from the Python: the profile HTML page (name, country,
// best-ever-rank) is CORS-blocked cross-origin, so we skip it — name comes from the slug,
// country from the search result that led here (null if a slug was pasted directly), and
// best-rank is unknown. Results still come per-year from the same GraphQL feed Python uses,
// so the counting set and scores are identical.
import { placingScore } from "./scoring.js";
import { gqlQuery, RESULTS_QUERY } from "./graphql.js";

// The profile feed leaves disciplineCode null, so main/similar events match by name.
const SIMILAR_NAMES = {
  "800m": ["600 Metres", "1000 Metres", "800 Metres Short Track",
           "600 Metres Short Track", "1000 Metres Short Track"],
  "1500m": ["Mile", "2000 Metres", "1500 Metres Short Track", "Mile Short Track",
            "2000 Metres Short Track", "Mile Road"],
  "5000m": ["3000 Metres", "2 Miles", "5000 Metres Short Track",
            "3000 Metres Short Track", "2 Miles Short Track", "5 Kilometres"],
  "10000m": ["10 Kilometres"],
  "3000msc": ["2000 Metres Steeplechase"],
};

// '1500m' -> '1500 Metres', '10000m' -> '10,000 Metres' (WA commas only >= 10000).
export function mainDisciplineName(discipline) {
  const num = parseInt(discipline.replace(/m$/i, ""), 10);
  return (num >= 10000 ? num.toLocaleString("en-US") : String(num)) + " Metres";
}

const MONTHS = { JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6,
                 JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12 };

// '07 JUN 2026' -> '2026-06-07' (also accepts full month names). Null if unparseable.
export function parseWaDate(raw) {
  const m = String(raw || "").trim().match(/^(\d{1,2}) ([A-Za-z]+) (\d{4})$/);
  if (!m) return null;
  const month = MONTHS[m[2].slice(0, 3).toUpperCase()];
  if (!month) return null;
  return `${m[3]}-${String(month).padStart(2, "0")}-${String(m[1]).padStart(2, "0")}`;
}

// 'P6' / '6' / 6 -> 6; null if there's no number.
export function parsePlace(raw) {
  const m = String(raw ?? "").match(/\d+/);
  return m ? parseInt(m[0], 10) : null;
}

export function normalizeRef(ref) {
  let s = ref.trim().replace(/\/+$/, "");
  if (s.includes("worldathletics.org") || s.includes("/athletes/")) {
    s = s.split("/athletes/").pop();
  }
  return s.split("/").pop();
}

const athleteId = (slug) => {
  const m = slug.match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : null;
};

const nameFromSlug = (slug) =>
  slug.replace(/-\d+$/, "").split("-")
      .map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");

function resultToPerf(placingScores, r, isMain, mainCode, group) {
  const rscore = r.resultScore || 0;
  const place = parsePlace(r.place);
  const cat = r.category ?? null;
  const pscore = cat && place ? placingScore(placingScores, cat, place, group) : 0;
  return {
    date: parseWaDate(r.date),
    competition: r.competition || r.venue || null,
    category: cat,
    discipline_code: isMain ? mainCode : "SIMILAR",
    place,
    mark: (r.mark || "").trim(),
    result_score: rscore,
    placing_score: pscore,
    performance_score: Math.max(0, rscore + pscore),
    is_main: isMain,
  };
}

// relativedelta-style month subtraction (day clamped to end of month).
function subMonths(iso, months) {
  const [y, m, d] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) - months;
  const ny = Math.floor(total / 12);
  const nm = ((total % 12) + 12) % 12;
  const last = new Date(Date.UTC(ny, nm + 1, 0)).getUTCDate();
  const pad = (n) => String(n).padStart(2, "0");
  return `${ny}-${pad(nm + 1)}-${pad(Math.min(d, last))}`;
}

// Window results for an unranked athlete, shaped like Python's fetch_profile result.
// `country` is a pass-through from the search candidate (null when a slug was pasted).
export async function fetchProfile(ctx, ref, event, asOf, windowMonths, { country = null } = {}) {
  const slug = normalizeRef(ref);
  const ev = ctx.events[event];
  if (!ev) throw new Error(`Unknown event '${event}'.`);
  const group = ev.placing_event_group ?? "standard";
  const mainCode0 = ev.main_event_codes[0];
  const mainName = ev.discipline_name || mainDisciplineName(ev.discipline);
  const similarNames = new Set(SIMILAR_NAMES[ev.discipline] || []);
  const windowStart = subMonths(asOf, windowMonths);

  const aid = athleteId(slug);
  if (!aid) throw new Error(`Couldn't read an athlete id from '${ref}' — paste the full profile link.`);

  const perfs = [];
  const startYear = parseInt(windowStart.slice(0, 4), 10);
  const endYear = parseInt(asOf.slice(0, 4), 10);
  for (let year = startYear; year <= endYear; year++) {
    const data = await gqlQuery(ctx.graphql, RESULTS_QUERY,
      { id: aid, resultsByYear: year, resultsByYearOrderBy: "discipline" });
    for (const blk of (data.getSingleCompetitorResultsDiscipline || {}).resultsByEvent || []) {
      const disc = (blk.discipline || "").trim();
      const isMain = disc === mainName;
      if (!(isMain || similarNames.has(disc))) continue;
      for (const r of blk.results || []) {
        perfs.push(resultToPerf(ctx.placingScores, r, isMain, mainCode0, group));
      }
    }
  }

  const inWindow = perfs.filter((p) => p.date && windowStart < p.date && p.date <= asOf);
  return {
    slug,
    name: nameFromSlug(slug),
    country,
    event,
    ranked: false,          // unknown without the (CORS-blocked) profile page; they're off the list
    best_rank: null,
    best_rank_weeks: null,
    performances: inWindow,
    incomplete_window: false,
  };
}
