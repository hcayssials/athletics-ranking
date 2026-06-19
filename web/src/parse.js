// Pure, framework-free helpers for the what-if console: time parsing, athlete matching,
// best-performance selection, and the natural-language query parser. Unit-tested in parse.test.mjs.

export const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export function parseTime(t) {
  const m = String(t).match(/(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?/);
  if (!m) return null;
  return +m[1] * 60 + +m[2] + (m[3] ? +("0." + m[3]) : 0);
}

export function fmtTime(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60), s = sec - m * 60;
  return m + ":" + s.toFixed(2).padStart(5, "0");
}

// Main discipline code for an event key, e.g. "1500m_men" -> "1500", "3000mSC_women" -> "3000SC".
export const mainCode = (eventKey) => eventKey.replace(/_(men|women)$/, "").replace(/mSC$/, "SC").replace(/m$/, "");
export const genderOf = (eventKey) => (/_women$/.test(eventKey) ? "women" : "men");
export const surnameOf = (name) => {
  const up = name.split(" ").filter((w) => w === w.toUpperCase() && w.length > 1);
  return up.length ? up[up.length - 1] : name.split(" ").pop();
};

// Pick an athlete's best performance for this event (fastest main-event run), to seed the console.
export function bestPerf(athlete, eventKey) {
  const perfs = athlete && athlete.performances;
  if (!perfs || !perfs.length) return null;
  const code = mainCode(eventKey);
  const mains = perfs.filter((p) => p.discipline_code === code);
  const pool = mains.length ? mains : perfs;
  const best = pool.reduce((a, b) => (b.result_score > a.result_score ? b : a));
  return { time: best.mark, place: String(best.place), category: best.category };
}

// Find the best-matching athlete name in a ranking list for free-typed text.
export function matchAthlete(text, list) {
  const nq = norm(text);
  if (!nq || !list.length) return null;
  for (const a of list) if (nq.includes(norm(a.name))) return a.name;          // full name present
  for (const a of list) {                                                      // surname (uppercase token)
    const surn = norm(a.name.split(" ").filter((w) => w === w.toUpperCase() && w.length > 1).join(" "));
    if (surn && nq.includes(surn)) return a.name;
  }
  for (const a of list) {                                                      // any name token >= 4 chars
    for (const tok of a.name.split(/\s+/)) {
      const t = norm(tok);
      if (t.length >= 4 && nq.includes(t)) return a.name;
    }
  }
  return null;
}

// Parse a natural-language what-if into structured hints (all optional).
export function parseQuery(query, currentEvent) {
  const nq = norm(query);
  const out = { athlete: query };

  // championship
  if (/\bworld\b|globally|world rank|world list/.test(nq)) out.championship = "world";
  else if (/birmingham|european|\beuros?\b|road to|qualif|make the team|\bthe team\b/.test(nq)) out.championship = "road_to_birmingham";

  // event (distance + gender); distance alone keeps the current event's gender
  // trailing (?!\d) instead of \b so "5000m"/"1500m" (digit followed by "m") still match
  let dist = null;
  if (/steeple|3000\s?m?\s?sc\b|3,?000\s?steeple/.test(nq)) dist = "3000mSC";
  else if (/\b10[,.]?000(?!\d)|\b10k\b/.test(nq)) dist = "10000m";
  else if (/\b5[,.]?000(?!\d)|\b5k\b/.test(nq)) dist = "5000m";
  else if (/\b1[,.]?500(?!\d)/.test(nq)) dist = "1500m";
  else if (/\b800(?!\d)/.test(nq)) dist = "800m";
  if (dist) {
    const g = /\bwomen'?s?\b|\bwoman\b|\bfemale\b|\bladies\b/.test(nq) ? "women"
      : /\bmen'?s?\b|\bmale\b/.test(nq) ? "men" : genderOf(currentEvent);
    out.eventKey = dist + "_" + g;
  }

  // finish place
  if (/\bwin(s|ning)?\b|\b1st\b|\bfirst\b|\bgold\b|\bchampion\b|\bvictor/.test(nq)) out.place = 1;
  else if (/\b2nd\b|\bsecond\b|runner.?up|\bsilver\b/.test(nq)) out.place = 2;
  else if (/\b3rd\b|\bthird\b|\bbronze\b/.test(nq)) out.place = 3;
  else { const pm = nq.match(/\b(\d+)(?:st|nd|rd|th)\b|\bplace\s+(\d+)|\bfinish(?:es|ing)?\s+(\d+)/); if (pm) out.place = +(pm[1] || pm[2] || pm[3]); }

  // meet category
  if (/olympic|world champ|worlds|\bwch\b/.test(nq)) out.category = "OW";
  else if (/(dl|diamond league)\s*final|diamond\s*final/.test(nq)) out.category = "DF";
  else if (/diamond league|\bdl\b|grand prix|prefontaine|weltklasse|bowerman|continental tour gold/.test(nq)) out.category = "GW";
  else if (/european champ|euro champ|area champ|continental champ/.test(nq)) out.category = "GL";
  else if (/national champ|nationals/.test(nq)) out.category = "C";
  else if (/\bfinal\b/.test(nq)) out.category = "DF";

  // time
  const t = parseTime(query);
  if (t) out.time = fmtTime(t);

  return out;
}
