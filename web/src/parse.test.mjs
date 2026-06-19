// Quick checks for parse.js against the live local backend (http://127.0.0.1:8077).
// Run: node src/parse.test.mjs
import { mainCode, parseQuery, bestPerf, matchAthlete, parseTime, extractSlug, deriveName, looksLikeProfile } from "./parse.js";

const B = "http://127.0.0.1:8077";
let pass = 0, fail = 0;
const eq = (got, want, msg) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; } else { fail++; console.log(`FAIL ${msg}\n   got  ${g}\n   want ${w}`); };
};

// --- mainCode ---
eq(mainCode("1500m_men"), "1500", "mainCode 1500");
eq(mainCode("800m_women"), "800", "mainCode 800");
eq(mainCode("10000m_men"), "10000", "mainCode 10000");
eq(mainCode("3000mSC_women"), "3000SC", "mainCode steeple");

// --- parseTime (multi-digit minutes) ---
eq(parseTime("3:29.50"), 209.5, "parseTime 1500");
eq(parseTime("13:05.00"), 785, "parseTime 5000");
eq(parseTime("27:30.10"), 1650.1, "parseTime 10000");

// --- parseQuery ---
eq(parseQuery("What if Wightman wins a Diamond League final in 3:27.8?", "1500m_men"),
   { athlete: "What if Wightman wins a Diamond League final in 3:27.8?", place: 1, category: "DF", time: "3:27.80" }, "pq wightman");
eq(parseQuery("How does Riva look on the world ranking with a 3:31 win?", "1500m_men"),
   { athlete: "How does Riva look on the world ranking with a 3:31 win?", championship: "world", place: 1, time: "3:31.00" }, "pq world");
eq(parseQuery("women's 5000m: Smith finishes 2nd at the European Champs", "1500m_men"),
   { athlete: "women's 5000m: Smith finishes 2nd at the European Champs", championship: "road_to_birmingham", eventKey: "5000m_women", place: 2, category: "GL" }, "pq event+gender");
eq(parseQuery("steeplechase third place", "1500m_men").eventKey, "3000mSC_men", "pq steeple keeps gender");
eq(parseQuery("Wightman wins nationals in 3:34", "1500m_men").category, "B", "pq nationals -> B (national champs)");
eq(parseQuery("3rd at a national meet", "1500m_men").category, "C", "pq national meet -> C");
eq(parseQuery("the 800 in 1:43.5", "5000m_women").eventKey, "800m_women", "pq 800 keeps women");

// --- extractSlug + deriveName ---
eq(extractSlug("https://worldathletics.org/athletes/great-britain/jake-heyward-14597392"), "jake-heyward-14597392", "slug from url");
eq(extractSlug("https://worldathletics.org/athletes/great-britain/jake-heyward-14597392?foo=1#bar"), "jake-heyward-14597392", "slug strips query/hash");
eq(extractSlug("  jake-heyward-14597392/  "), "jake-heyward-14597392", "slug from bare value + trailing slash");
eq(deriveName("jake-heyward-14597392"), "Jake Heyward", "name from slug");
eq(deriveName("pieter-sisk-14613049"), "Pieter Sisk", "name from slug 2");

// --- looksLikeProfile ---
eq(looksLikeProfile("https://worldathletics.org/athletes/great-britain/jake-heyward-14597392"), true, "profile url");
eq(looksLikeProfile("jake-heyward-14597392"), true, "profile bare slug");
eq(looksLikeProfile("Jake WIGHTMAN"), false, "name not profile");
eq(looksLikeProfile("Narve Gilje NORDÅS"), false, "spaced name not profile");
eq(looksLikeProfile(""), false, "empty not profile");

// --- live data: bestPerf + matchAthlete ---
const main = async () => {
  const rk = await (await fetch(`${B}/api/rankings?championship=road_to_birmingham&event=1500m_men`)).json();
  const list = rk.athletes;
  eq(matchAthlete("what if WIGHTMAN wins", list), "Jake WIGHTMAN", "match surname");
  eq(matchAthlete("how about nader", list), "Isaac NADER", "match lowercase surname");
  eq(matchAthlete("nobody here", list), null, "match miss");

  const ath = await (await fetch(`${B}/api/athlete?championship=road_to_birmingham&event=1500m_men&name=${encodeURIComponent("Jake WIGHTMAN")}`)).json();
  const best = bestPerf(ath, "1500m_men");
  // best main-event (code 1500) by result_score: 3:31.58 (rs 1222) beats 3:34.12 (rs 1187)
  eq(best, { time: "3:31.58", place: "4", category: "GW" }, "bestPerf main-event fastest");

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
};
main().catch((e) => { console.error("test error:", e.message); process.exit(2); });
