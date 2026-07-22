// Port of wa_ranking/scoring.py — time -> result score, placing score, age decay.
// Pure functions over explicit data (no fetch): a result table is [[mark_seconds, score], ...]
// ascending; placingScores/decay come from data/engine.json. Parity with the Python engine is
// enforced by parity.test.mjs against generated golden vectors — keep the logic in lockstep.

// Python round() (banker's rounding, half to even) for the rare exact-half doubles.
export function pyRound(x, nd = 0) {
  const m = Math.pow(10, nd);
  const y = x * m;
  const f = Math.floor(y);
  if (y - f === 0.5) return (f % 2 === 0 ? f : f + 1) / m;
  return Math.round(y) / m;
}

function bisectLeft(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1; else hi = mid;
  }
  return lo;
}

export function parseTime(value) {
  if (typeof value === "number") return value;
  const s = String(value).trim();
  if (!s.includes(":")) {
    const v = parseFloat(s);
    if (Number.isNaN(v)) throw new Error(`could not convert string to float: '${s}'`);
    return v;
  }
  let seconds = 0;
  for (const p of s.split(":")) {
    const v = parseFloat(p);
    if (Number.isNaN(v)) throw new Error(`could not convert string to float: '${p}'`);
    seconds = seconds * 60 + v;
  }
  return pyRound(seconds, 3);
}

// A time scores the points of the fastest tabulated threshold it still meets:
// the smallest tabulated mark >= T.
export function resultScore(table, time) {
  const seconds = parseTime(time);
  const idx = bisectLeft(table.map((r) => r[0]), seconds);
  if (idx >= table.length) return 0; // slower than the slowest tabulated mark
  return table[idx][1];
}

export function formatSeconds(seconds) {
  if (seconds < 60) return seconds.toFixed(2);
  const r = pyRound(seconds, 2);
  const m = Math.floor(r / 60);
  return `${m}:${(r - m * 60).toFixed(2).padStart(5, "0")}`;
}

// The (slowest) time that scores at least targetScore, formatted; null if off-table.
export function timeForResultScore(table, targetScore) {
  let best = null;
  for (const [seconds, score] of table) {
    if (score >= targetScore) best = seconds; // keep the slowest qualifying mark
  }
  return best !== null ? formatSeconds(best) : null;
}

export function placingScore(placingScores, category, place, eventGroup = "standard") {
  if (!(eventGroup in placingScores)) {
    throw new Error(`Unknown placing event_group '${eventGroup}'.`);
  }
  const cat = category.toUpperCase();
  if (!(cat in placingScores[eventGroup])) {
    const known = Object.keys(placingScores[eventGroup]).filter((k) => !k.startsWith("_")).sort();
    throw new Error(`Unknown category '${category}'. Known: ${JSON.stringify(known)}`);
  }
  return Number(placingScores[eventGroup][cat][String(place)] ?? 0);
}

// Whole calendar months old, from ISO date strings.
export function monthAge(perfDate, asOf) {
  const [py, pm, pd] = perfDate.split("-").map(Number);
  const [ay, am, ad] = asOf.split("-").map(Number);
  let months = (ay - py) * 12 + (am - pm);
  if (ad < pd) months -= 1;
  return Math.max(0, months);
}

export function decayDeduction(decay, monthsOld) {
  return Number(decay[String(monthsOld)] ?? 0);
}

export function performanceScore(result, placing, decay = 0) {
  return Math.max(0, result + placing + decay);
}

// Fully score a (hypothetical) performance. `table` is the result table to score on
// (the main event's, or a similar event's).
export function scorePerformance(ctx, table, time, category, place,
                                 { perfDate = null, asOf = null, eventGroup = "standard" } = {}) {
  const rscore = resultScore(table, time);
  const pscore = placingScore(ctx.placingScores, category, place, eventGroup);
  const months = perfDate && asOf ? monthAge(perfDate, asOf) : 0;
  const decay = decayDeduction(ctx.decay, months);
  return {
    time: String(time),
    seconds: parseTime(time),
    category: category.toUpperCase(),
    place,
    result_score: rscore,
    placing_score: pscore,
    months_old: months,
    decay,
    performance_score: performanceScore(rscore, pscore, decay),
  };
}
