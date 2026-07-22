// Port of wa_ranking/ranking.py — best-N selection, hypothetical insertion, rank position.
// Dates are ISO strings throughout (lexicographic compare == date compare).
// The WA-returned set is already the counting set; baseline score = floor(mean). See the
// Python module docstring for why we never re-window the baseline.

function toDate(value) {
  if (value == null) return null;
  const s = String(value).slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
}

const score = (p) => p.performance_score || 0;

// Window-exempt (e.g. previous continental championship) — but still displaceable on score.
function isProtected(perf, patterns) {
  const comp = (perf.competition || "").toLowerCase();
  return patterns.some((pat) => comp.includes(pat));
}

// relativedelta(months=n) subtraction with end-of-month clamping.
function subMonths(iso, months) {
  const [y, m, d] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) - months;
  const ny = Math.floor(total / 12);
  const nm = ((total % 12) + 12) % 12; // 0-11
  const last = new Date(Date.UTC(ny, nm + 1, 0)).getUTCDate();
  const pad = (n) => String(n).padStart(2, "0");
  return `${String(ny).padStart(4, "0")}-${pad(nm + 1)}-${pad(Math.min(d, last))}`;
}

export function resolveWindow(windowMonths, asOf, { windowStart = null, windowEnd = null } = {}) {
  const end = windowEnd || asOf;
  const start = windowStart || subMonths(end, windowMonths);
  return [start, end];
}

export function selectCounting(candidates, bestN, {
  mainEventCodes = [],
  mainEventMin = 0,
  alwaysIncludeCompetitions = [],
  windowStart = null,
  windowEnd = null,
} = {}) {
  const patterns = alwaysIncludeCompetitions.map((s) => s.toLowerCase());
  const mainCodes = new Set(mainEventCodes);

  // 1. Optional fixed-window filter (protected performances survive regardless of date).
  const pool = [];
  for (const p of candidates) {
    if (isProtected(p, patterns)) {
      pool.push(p);
    } else if (windowStart === null && windowEnd === null) {
      pool.push(p);
    } else {
      const d = toDate(p.date);
      const start = windowStart || "0001-01-01";
      const end = windowEnd || "9999-12-31";
      if (d !== null && start < d && d <= end) pool.push(p);
    }
  }
  pool.sort((a, b) => score(b) - score(a)); // stable, like Python list.sort

  // 2. Satisfy the main-event minimum with the best available main events.
  let selected = [];
  if (mainCodes.size && mainEventMin > 0) {
    const mains = pool.filter((p) => mainCodes.has(p.discipline_code));
    selected = mains.slice(0, Math.min(mainEventMin, bestN));
  }

  // 3. Fill remaining slots by score (best of the rest; may add further main events).
  const selIds = new Set(selected);
  selected = selected.concat(
    pool.filter((p) => !selIds.has(p)).slice(0, bestN - selected.length));

  selected.sort((a, b) => score(b) - score(a));
  return selected.slice(0, bestN);
}

// Floored mean of the counting performances (null if there are none).
export function rankingScore(perfs, bestN, sel = {}) {
  const counting = selectCounting(perfs, bestN, sel);
  if (!counting.length) return null;
  return Math.floor(counting.reduce((s, p) => s + score(p), 0) / counting.length);
}

export function insertAndRecompute(perfs, newPerf, bestN, sel = {}) {
  const oldCounting = selectCounting(perfs, bestN, sel);
  const newCounting = selectCounting(perfs.concat([newPerf]), bestN, sel);
  const floored = (rows) =>
    rows.length ? Math.floor(rows.reduce((s, p) => s + score(p), 0) / rows.length) : null;
  const oldScore = floored(oldCounting);
  const newScore = floored(newCounting);
  return {
    old_score: oldScore,
    new_score: newScore,
    delta: oldScore === null || newScore === null ? null : newScore - oldScore,
    old_counting: oldCounting,
    new_counting: newCounting,
    new_perf_counts: newCounting.some((p) => p === newPerf),
  };
}

// 1-based position among allScores (ties: highest position).
export function rankPosition(allScores, newScore) {
  return 1 + allScores.filter((s) => s !== null && s !== undefined && s > newScore).length;
}
