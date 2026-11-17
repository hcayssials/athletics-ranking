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

export const genderOf = (eventKey) => (/_women$/.test(eventKey) ? "women" : "men");
export const surnameOf = (name) => {
  const up = name.split(" ").filter((w) => w === w.toUpperCase() && w.length > 1);
  return up.length ? up[up.length - 1] : name.split(" ").pop();
};

// Extract the WA athlete slug from a pasted profile URL (or accept a bare slug).
// e.g. "https://worldathletics.org/athletes/great-britain/jake-heyward-14597392?x=1" -> "jake-heyward-14597392"
export function extractSlug(input) {
  let s = (input || "").trim();
  if (!s) return "";
  s = s.split(/[?#]/)[0].replace(/\/+$/, "");          // drop query/hash + trailing slash
  if (s.includes("/")) s = s.slice(s.lastIndexOf("/") + 1);
  return s;
}

// Does this athlete-field text look like a World Athletics profile (URL or bare slug)
// rather than a name? Used to route the single console input to the unranked path.
export function looksLikeProfile(s) {
  const t = (s || "").trim();
  if (!t) return false;
  if (/^https?:\/\//i.test(t) || /worldathletics\.org|\/athletes\//i.test(t)) return true;
  if (!/\s/.test(t) && /-\d{4,}$/.test(t)) return true;   // bare slug, e.g. jake-heyward-14597392
  return false;
}

// Turn a slug into a readable name: "jake-heyward-14597392" -> "Jake Heyward".
export function deriveName(slug) {
  const s = (slug || "").replace(/-\d+$/, "");          // strip the trailing numeric id
  return s.split("-").filter(Boolean).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

// Pick an athlete's best performance in the event's Main Event, to seed the console.
// `mainCodes` are WA's real discipline codes from the event config (10000m is "10K", the
// steeple "3KSC" — they can't be derived from the event key). Null when the athlete has no
// main-event result: a similar-event mark (a 10km road time, a 2000m steeple) must never be
// pre-filled as if it were the main event.
export function bestPerf(athlete, mainCodes) {
  const perfs = athlete && athlete.performances;
  if (!perfs || !perfs.length) return null;
  const codes = new Set(mainCodes || []);
  const pool = perfs.filter((p) => codes.has(p.discipline_code));
  if (!pool.length) return null;
  const best = pool.reduce((a, b) => (b.result_score > a.result_score ? b : a));
  return { time: best.mark, place: String(best.place), category: best.category };
}

// Find the best-matching athlete name in a ranking list for free-typed text.
// Matching is on whole words, never substrings (a surname like "HE" must not match "the"),
// and the athlete with the most name words in the text wins, so "Emmanuel Kiplagat" picks
// Emmanuel Korir KIPLAGAT over a higher-ranked Kelvin KIPLAGAT. Ties go to the higher-ranked
// athlete (list order). Strength of evidence, strongest first:
//   full name > surname (+ given names) > loose name words (>= 4 letters each).
// A surname under 4 letters ("HE", "LI", "AHL") only counts with a given name beside it.
const words = (s) => norm(s).split(/[^a-z0-9]+/).filter(Boolean);

export function matchAthlete(text, list) {
  const q = words(text);
  if (!q.length || !list.length) return null;
  const hay = " " + q.join(" ") + " ";
  const has = (phrase) => phrase && hay.includes(" " + phrase + " ");
  let best = null, bestScore = 0;
  for (const a of list) {
    const parts = a.name.split(/\s+/).filter(Boolean);
    const isSurn = (w) => w === w.toUpperCase() && w !== w.toLowerCase() && w.length > 1;
    const surn = words(parts.filter(isSurn).join(" ")).join(" ");
    const given = words(parts.filter((w) => !isSurn(w)).join(" "));
    const givenHits = given.filter((t) => t.length >= 2 && has(t)).length;
    let score = 0;
    if (has(words(a.name).join(" "))) score = 1000;
    else if (has(surn) && (surn.length >= 4 || givenHits > 0)) score = 100 + givenHits;
    else score = words(a.name).filter((t) => t.length >= 4 && has(t)).length;
    if (score > bestScore) { best = a.name; bestScore = score; }
  }
  return best;
}

// Athletes whose surname is too short to match on its own (under 4 letters: "HE", "LI",
// "AHL") when `name` is nothing but that surname — so the UI can ask for the first name
// instead of silently finding nobody.
export function shortSurnameMatches(name, list) {
  const q = words(name).join(" ");
  if (!q || q.length >= 4) return [];
  return list.filter((a) => {
    const surn = words(a.name.split(/\s+/).filter((w) => w === w.toUpperCase() && w !== w.toLowerCase() && w.length > 1).join(" ")).join(" ");
    return surn === q;
  }).map((a) => a.name);
}

// Pull a likely athlete name out of a natural-language what-if, for the unranked WA search:
// strip a leading framing phrase ("what if …") and any "women's 5000m:" prefix, then keep the
// words before the first scenario verb, preposition, or number. Best-effort — if it comes back
// empty or wrong, the search simply finds nothing and the UI falls back to the profile-link hint.
export function extractName(query) {
  let s = (query || "").trim();
  s = s.replace(/^\s*(what if|how would|how does|how do|what about|how about|will|can|could|if)\b[:,]?\s*/i, "");
  // strip a leading "women's 5000m:" style event prefix — only if the part before the first
  // colon actually names an event/gender (so a time like "3:34" doesn't trigger it).
  const ci = s.indexOf(":");
  if (ci > 0 && ci < 40 &&
      /\b(men|women|ladies|mixed)\b|steeple|\bmile\b|metre|\b\d{3,}\s?m(sc)?\b|road to|\bworld\b|\beuro|birmingham|ultimate|budapest|beijing/i.test(s.slice(0, ci)))
    s = s.slice(ci + 1).trim();
  const cut = s.search(/\b(wins?|winning|won|finish\w*|runs?|running|ran|places?|placing|placed|scores?|gets?|clocks?|goes?|going|looks?|with|at|in|on|to)\b|\d/i);
  if (cut > 0) s = s.slice(0, cut);
  return s.trim().replace(/[?.,;:]+$/, "");
}

// A championship named as the *goal* ("qualify for the World Championships", "make the
// final") says nothing about the meet the race is run at, so it must not set the category.
// Blank those mentions out; "wins the worlds" / "at the Olympics" (the venue) are left alone.
const CHAMP_TERM = /(?:world champ\w*|worlds|wch|olympi\w*|(?:dl |diamond league |diamond )?final)/g;
const GOAL_BEFORE = /(?:qualif\w*|mak(?:e|es|ing)|reach(?:es|ing)?|get(?:s|ting)? (?:in)?to|road to|standard|spot|berth|ticket|select\w*|team|for)(?: \w+){0,2} (?:for |to |at |in )?(?:the )?(?:\d{4} )?$/;
function maskGoals(nq) {
  return nq.replace(CHAMP_TERM, (m, off) => (GOAL_BEFORE.test(nq.slice(0, off)) ? " ".repeat(m.length) : m));
}

const MONTH = "(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*";
// What an ordinal counts when it isn't a finishing place: "first race", "2nd attempt", "23rd May".
const NOT_A_PLACE = `(?:race|races|time|run|outing|meet|meeting|attempt|start|season|lap|laps|half|leg|ever|sub|diamond|dl|year|title|appearance|${MONTH})\\b`;

function parsePlaceWords(nq) {
  // 1. An explicit finishing place wins over everything ("finishing 4th", "4th place", "places 6").
  let m = nq.match(/\bfinish\w*(?: in)? (\d{1,2})(?:st|nd|rd|th)?\b|\bplac(?:e|es|ed|ing) (\d{1,2})(?:st|nd|rd|th)?\b|\b(\d{1,2})(?:st|nd|rd|th) place\b/);
  if (m) return +(m[1] || m[2] || m[3]);
  // 2. Winning words.
  if (/\bwin(s|ning)?\b|\bgold\b|\bchampion\b|\bvictor/.test(nq)) return 1;
  if (/runner.?up|\bsilver\b/.test(nq)) return 2;
  if (/\bbronze\b/.test(nq)) return 3;
  // 3. Ordinals, unless they count something else ("first race", "23rd May", "May 23rd").
  const ord = new RegExp(`(?<!${MONTH} )\\b(first|second|third|\\d{1,2}(?:st|nd|rd|th))\\b(?! (?:of )?${NOT_A_PLACE})`);
  m = nq.match(ord);
  if (m) return { first: 1, second: 2, third: 3 }[m[1]] || parseInt(m[1], 10);
  return null;
}

// Parse a natural-language what-if into structured hints (all optional).
export function parseQuery(query, currentEvent) {
  const nq = norm(query);
  const out = { athlete: query };

  // championship. Specific names first ("World Athletics Ultimate" / "World Championships"
  // both contain "world"); a generic qualifying phrase means the live Road to (Beijing 27).
  // Archived keys (ultimate, birmingham) still parse — App ignores a key that isn't offered.
  if (/ultimate|budapest/.test(nq)) out.championship = "road_to_ultimate";
  else if (/beijing|world champ|\bworlds\b|\bwch\b/.test(nq)) out.championship = "road_to_beijing";
  else if (/\bworld\b|globally|world rank|world list/.test(nq)) out.championship = "world";
  else if (/birmingham|european|\beuros?\b/.test(nq)) out.championship = "road_to_birmingham";
  else if (/road to|qualif|make the team|\bthe team\b/.test(nq)) out.championship = "road_to_beijing";

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
  const place = parsePlaceWords(nq);
  if (place) out.place = place;

  // meet category — from where the race is run, not the championship being aimed at
  const cq = maskGoals(nq);
  if (/olympi|world champ|worlds|\bwch\b/.test(cq)) out.category = "OW";
  else if (/(dl|diamond league)\s*final|diamond\s*final/.test(cq)) out.category = "DF";
  else if (/diamond league|\bdl\b|grand prix|prefontaine|weltklasse|bowerman|continental tour gold/.test(cq)) out.category = "GW";
  else if (/european champ|euro champ|area champ|continental champ/.test(cq)) out.category = "GL";
  else if (/national\s*champ|\bnationals\b/.test(cq)) out.category = "B";   // National Championships
  else if (/national\s*meet|\bdomestic\b/.test(cq)) out.category = "C";     // ordinary national-level meet
  else if (/\bfinal\b/.test(cq)) out.category = "DF";

  // time: "3:29.50"; also a comma decimal ("3:29,50") and dots throughout ("1.41.50")
  const tq = String(query).replace(/(\d:\d{2}),(\d)/, "$1.$2")
    .replace(/(?<![\d.:])(\d{1,2})\.([0-5]\d)\.(\d{1,2})(?![\d.])/, "$1:$2.$3");
  const t = parseTime(tq);
  if (t) out.time = fmtTime(t);

  return out;
}
