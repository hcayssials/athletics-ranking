import React, { useEffect, useMemo, useState } from "react";
import { getMeta, getRankings, getAthlete, searchAthletes, runWhatIf, getRequired } from "./api.js";
import { parseTime, surnameOf, bestPerf, matchAthlete, parseQuery, extractSlug, deriveName, looksLikeProfile, extractName } from "./parse.js";
import { INK, SURFACE, BG, ACCENT, MUTE, MONO } from "./theme.js";

// Ranking What-If Studio — "WA Editorial" look (see theme.js), driven by the live FastAPI backend.
// All ranking/qualification numbers come from /api/rankings and /api/whatif (real data, all events).

const CAT_LABELS = {
  OW: "OW — Olympics / World Champs", DF: "DF — Diamond League final",
  GW: "GW — Diamond League / World Indoor", GL: "GL — Area championships",
  A: "A — top international", B: "B — national champs / strong int'l",
  C: "C — national meets", D: "D — regional", E: "E — smaller", F: "F — local",
};

// Rough guide to what each World Athletics category covers (WA sets the exact category per meet).
const CAT_INFO = [
  ["OW", "Olympic Games & World Championships (outdoor and indoor)"],
  ["DF", "Diamond League final"],
  ["GW", "Diamond League meetings & World Indoor Championships"],
  ["GL", "Area senior championships (e.g. European Championships)"],
  ["A", "Top international meetings (e.g. Continental Tour Gold)"],
  ["B", "National Championships & strong internationals (e.g. Continental Tour Silver)"],
  ["C", "Ordinary national-level meetings (e.g. Continental Tour Bronze)"],
  ["D", "Smaller domestic / regional meetings"],
  ["E", "Lower-level domestic meetings"],
  ["F", "Local / club meetings"],
];
const WA_RULES_URL = "https://worldathletics.org/world-ranking-rules/track-field-events-2026";
const WA_RANKINGS_URL = "https://worldathletics.org/world-rankings";
const WA_SCORING_URL = "https://worldathletics.org/about-iaaf/documents/technical-information";
const FEEDBACK_URL = "https://docs.google.com/forms/d/e/1FAIpQLSelCKe92h_KXJKFuVZH-ohaSDNzgUSSZd0KV6fPlyRjA-ETYw/viewform";
const FOOT_LINK = { color: "#6b7480", textDecoration: "underline", textUnderlineOffset: 2 };

// ---------- small helpers ----------
// rank_date is an ISO day string ("2026-06-16"); show it human-readably plus how long ago.
const fmtDate = (s) => {
  if (!s) return "";
  const d = new Date(s + "T00:00:00");
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};
const daysAgo = (s) => {
  if (!s) return "…";
  const d = new Date(s + "T00:00:00");
  if (Number.isNaN(d.getTime())) return s;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const n = Math.round((today - d) / 86400000);
  if (n <= 0) return "today";
  if (n === 1) return "yesterday";
  return `${n} days ago`;
};

// Scenario ↔ URL query, so a what-if can be linked/bookmarked. `a` is the athlete name;
// `pf` carries the World Athletics slug when the athlete was looked up off-list (unranked).
function scenarioToQuery({ champ, ev, name, profile, time, place, category, subEvent, qualify, hasQual }) {
  const p = new URLSearchParams();
  p.set("c", champ);
  p.set("e", ev);
  p.set("a", name);
  if (profile) p.set("pf", profile);
  p.set("t", time);
  p.set("p", String(place));
  p.set("cat", category);
  if (subEvent && subEvent !== "main") p.set("se", subEvent);
  if (hasQual) p.set("q", qualify ? "1" : "0");
  return p.toString();
}

const shortMeet = (s) => {
  if (!s || s === "(hypothetical)") return "Hypothetical";
  const head = s.split(",")[0].trim();
  return head.length > 42 ? head.slice(0, 40) + "…" : head;
};

// Short event label for a counting performance — distinguishes indoor/outdoor and similar
// events (e.g. a 3000m counting toward a 5000m ranking). Falls back to the discipline code.
const shortEvent = (p) => {
  let d = (p.discipline || p.discipline_code || "").toString()
    .replace(/\bMetres\b/gi, "m").replace(/\bKilometres\b|\bKilometers\b/gi, "km")
    .replace(/\bRoad\b/gi, "Rd").replace(/\bSteeplechase\b/gi, "SC")
    .replace(/\bOne Mile\b/gi, "Mile").replace(/\(indoor\)/gi, "(i)")
    .replace(/(\d)\s+(m|km)\b/g, "$1$2").replace(/\s+/g, " ").trim();
  if (p.indoor && !/indoor|\(i\)/i.test(d)) d += " (i)";
  return d || "—";
};

// Indicative qualifying zone for the table: wildcard byes (a defending champion, or the
// Olympic/World champions for the Ultimate) consume the first places, then the rest fill by
// descending score with the championship's per-country cap (null = no cap). Mirrors qualify.py.
function qualifyingZone(rankings) {
  const empty = { qualSet: new Set(), qualPos: {}, lastQualName: null, cutoff: null, invites: [] };
  if (!rankings) return empty;
  const quota = rankings.quota || 30;
  const maxPer = rankings.max_per_country == null ? Infinity : rankings.max_per_country;
  const invites = rankings.auto_invites
    ? rankings.auto_invites.map((i) => i.name)
    : rankings.defending_champion ? [rankings.defending_champion.name] : [];
  const inviteSet = new Set(invites);
  const sorted = [...rankings.athletes].sort((a, b) => b.ranking_score - a.ranking_score);
  // Wildcards hold slots 1..k (exempt from the country cap, wherever they sit on the list);
  // the ranking walk fills the remaining quota-k slots. qualPos = the slot number in the
  // actual qualifying field (which can differ from the raw rank once byes/caps bite).
  const cc = {}; let pos = invites.length, last = null, cutoff = null;
  const qualSet = new Set(), qualPos = {};
  for (const nm of invites) { qualSet.add(nm); qualPos[nm] = invites.indexOf(nm) + 1; }
  for (const a of sorted) {
    if (inviteSet.has(a.name)) continue;              // already in by wildcard
    if (pos >= quota) break;
    if ((cc[a.country] || 0) >= maxPer) continue;     // country already full → blocked
    cc[a.country] = (cc[a.country] || 0) + 1;
    pos++; qualPos[a.name] = pos; qualSet.add(a.name); last = a.name; cutoff = a.ranking_score;
  }
  return { qualSet, qualPos, lastQualName: last, cutoff, invites };
}

// Map a /api/whatif response into the result-panel view model.
function buildResultView(r, champCfg, qualifyOn, methodOpen) {
  const rowKey = (p) => `${p.date_raw || p.date}|${p.mark}|${p.performance_score}`;
  const newKeys = new Set(r.new_counting.filter((p) => !p.hypothetical).map(rowKey));
  const display = r.new_counting.map((p) => ({ ...p, state: p.hypothetical ? "new" : "kept" }));
  for (const p of r.old_counting || []) if (!newKeys.has(rowKey(p))) display.push({ ...p, state: "dropped" });

  const q = (champCfg.has_qualification && qualifyOn && r.qualification) ? r.qualification : null;
  let qual = null;
  if (q) {
    const inField = (q.field_new || []).some((e) => e.name === r.athlete && e.reason === "ranking");
    const blocked = (q.blocked_new || []).some((e) => e.name === r.athlete);
    const status = q.is_auto_invited ? "champion" : inField ? "in" : blocked ? "blocked" : "below";
    const invite = (q.auto_invites || []).find((i) => i.name.toUpperCase() === (r.athlete || "").toUpperCase());
    qual = {
      status, cutoff: q.cutoff_score, position: q.qual_position_new, quota: q.quota,
      country: r.country, countryAhead: q.country_ahead || 0,
      maxPerCountry: q.max_per_country,                       // null = no country cap
      inviteReason: invite ? invite.reason : null,            // why this athlete holds a wildcard
      needPts: Math.max(0, Math.round((q.cutoff_score || 0) - r.new_score)),
    };
  }

  const unranked = !!r.profile_summary;
  const sd = r.score_delta || 0, rd = r.rank_delta || 0;
  return {
    name: r.athlete, country: r.country,
    scopeLabel: (champCfg.scope_label || "World Ranking") + " · " + r.rank_date,
    rankLabel: champCfg.rank_label || "World rank",
    oldRank: r.old_rank, newRank: r.new_rank, rankDelta: rd,
    // An unranked athlete who lands past the tracked list isn't "101st" — we only know they'd
    // miss the top N (new_rank maxes out at list_size + 1).
    listSize: r.list_size, outsideList: unranked && r.list_size != null && r.new_rank > r.list_size,
    oldScore: unranked ? r.recomputed_old_score : r.official_ranking_score, newScore: r.new_score, scoreDelta: sd,
    hypo: r.hypothetical_performance,
    counts: r.new_perf_counts,
    bestN: (r.assumptions && r.assumptions.best_n) || 5,
    windowMonths: (r.assumptions && r.assumptions.window_months) || 12,
    notes: (r.assumptions && r.assumptions.notes) || [],
    qual, display, open: methodOpen,
    unranked, profileSummary: r.profile_summary,
    whatWouldItTake: r.what_would_it_take,
    hypoEvent: r.hypothetical_event,           // which discipline the hypothetical was in
    simNote: r.similar_event_note,             // main-event-rule explanation (similar events)
    blockedByMainRule: !!(r.main_event_rule && r.main_event_rule.blocked_by_main_rule),
  };
}

const badge = (delta, kind) => {
  // kind: 'rank' (▲ up = better) or 'score'
  const up = delta > 0, down = delta < 0;
  const bg = up ? "#e3f3e9" : down ? "#fbe4e1" : "#eceef2";
  const fg = up ? "#1f6b43" : down ? "#9c352a" : "#6b7480";
  return { bg, fg };
};

// True on phone-width screens; lets inline styles branch on layout (CSS-in-JS can't use
// media queries). Both App and ResultPanel use it to stack columns and shrink hero numbers.
function useIsNarrow(maxWidth = 760) {
  const q = `(max-width: ${maxWidth}px)`;
  const [narrow, setNarrow] = useState(() =>
    typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = (e) => setNarrow(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return narrow;
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [championship, setChampionship] = useState("road_to_birmingham");
  const [event, setEvent] = useState("1500m_men");
  const [rankings, setRankings] = useState(null);
  const [rankErr, setRankErr] = useState("");
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ athlete: "", time: "3:30.00", place: 1, category: "GW", qualify: true, subEvent: "main" });
  const [selected, setSelected] = useState(null);
  const [athleteInfo, setAthleteInfo] = useState(null); // clicked athlete's perfs (preview before a what-if)
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [methodOpen, setMethodOpen] = useState(false);
  const [catHelp, setCatHelp] = useState(false);
  const [candidates, setCandidates] = useState(null); // WA search matches for an unlisted name
  const [searching, setSearching] = useState(false);
  const [pending, setPending] = useState(null); // a queued natural-language run, executed once its list loads
  const [pendingShare, setPendingShare] = useState(null); // a scenario restored from the URL, run once its list loads
  const [copiedLink, setCopiedLink] = useState(false);

  // Everything championship-specific (labels, qualification, contested events) is meta-driven.
  const champCfg = meta ? (meta.championships.find((c) => c.key === championship) || {}) : {};
  const hasQual = !!champCfg.has_qualification;
  // An event absent from an invitational's programme (e.g. the steeplechase at the Ultimate
  // Championship) — show a notice instead of a ranking list.
  const notContested = (champCfg.not_contested || []).includes(event);
  const narrow = useIsNarrow();

  const entryStandardFor = (ev) => (meta && (meta.events.find((e) => e.key === ev) || {}).entry_standard) || "";

  useEffect(() => {
    getMeta().then((m) => {
      setMeta(m);
      const sp = new URLSearchParams(window.location.search);
      if (sp.get("a")) {
        // A shared scenario in the URL — restore it and queue a run once its list loads.
        const champ = m.championships.some((c) => c.key === sp.get("c")) ? sp.get("c") : championship;
        const ev = m.events.some((e) => e.key === sp.get("e")) ? sp.get("e") : event;
        const f = {
          athlete: sp.get("a"),
          time: sp.get("t") || "3:30.00",
          place: parseInt(sp.get("p"), 10) || 1,
          category: m.categories.includes(sp.get("cat")) ? sp.get("cat") : "GW",
          qualify: sp.get("q") !== "0",
          subEvent: sp.get("se") || "main",
        };
        setChampionship(champ); setEvent(ev); setForm(f);
        setPendingShare({ f, champ, ev, profile: sp.get("pf") || null });
        return;
      }
      const es = (m.events.find((e) => e.key === event) || {}).entry_standard;
      if (es) setForm((s) => ({ ...s, time: es }));   // sensible starting time for the initial event
    }).catch((e) => setRankErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    setRankings(null); setRankErr("");
    if (notContested) return;                 // no list to load — the notice panel shows instead
    getRankings(championship, event).then(setRankings).catch((e) => setRankErr(e.message));
  }, [championship, event, notContested]);

  // Execute a URL-restored scenario once the ranking list for its event/championship has loaded.
  useEffect(() => {
    if (!pendingShare || !rankings) return;
    if (rankings.championship !== pendingShare.champ || rankings.event !== pendingShare.ev) return;
    const { f, champ, ev, profile } = pendingShare;
    setPendingShare(null);
    run(f, champ, ev, profile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingShare, rankings]);

  // Manual selector changes start fresh; NL changes (via `pending`) keep their queued run alive.
  const changeChampionship = (c) => { setChampionship(c); setResult(null); setSelected(null); setAthleteInfo(null); setError(""); setCandidates(null); };
  // New event → reset Time to that event's entry standard and Place to 1 (keep Category) so the
  // console never shows a time from the previous event. A later athlete pick still overrides these.
  const changeEvent = (e) => {
    setEvent(e); setResult(null); setSelected(null); setAthleteInfo(null); setError(""); setCandidates(null);
    setForm((s) => ({ ...s, time: entryStandardFor(e), place: 1, subEvent: "main" }));
  };

  const zone = useMemo(() => (hasQual ? qualifyingZone(rankings) : qualifyingZone(null)), [rankings, hasQual]);
  const list = rankings ? rankings.athletes : [];
  const selCountry = selected ? (list.find((a) => a.name === selected) || {}).country : null;

  const eventCfg = meta ? (meta.events.find((e) => e.key === event) || {}) : {};
  const eventLabel = eventCfg.label || event;
  const categories = meta ? meta.categories : ["GW"];

  async function run(overrideForm, champ = championship, ev = event, profile = null) {
    const f = overrideForm || form;
    let name = (f.athlete || "").trim();
    // A pasted World Athletics link/slug in the athlete field → unranked profile path.
    if (!profile && looksLikeProfile(name)) {
      profile = extractSlug(name);
      name = deriveName(profile) || profile;
    }
    if (!name) { setError("Enter an athlete — a name from the list, or a World Athletics link."); setResult(null); return; }
    if (!parseTime(f.time)) { setError("Enter a time like 3:29.00."); setResult(null); return; }
    setBusy(true); setError(""); setCandidates(null);
    try {
      const champQual = !!((meta.championships.find((x) => x.key === champ) || {}).has_qualification);
      const r = await runWhatIf({
        event: ev, championship: champ, athlete: name, time: f.time,
        category: f.category, place: Math.max(1, parseInt(f.place) || 1),
        qualify: champQual && f.qualify,
        ...(f.subEvent && f.subEvent !== "main" ? { sub_event: f.subEvent } : {}),
        ...(profile ? { profile } : {}),
      });
      setResult(r); setSelected(r.athlete);
      // Reflect the scenario in the address bar so it can be copied / bookmarked / shared.
      const q = scenarioToQuery({
        champ, ev, name: r.athlete || name, profile,
        time: f.time, place: Math.max(1, parseInt(f.place) || 1),
        category: f.category, subEvent: f.subEvent, qualify: f.qualify, hasQual: champQual,
      });
      window.history.replaceState(null, "", `${window.location.pathname}?${q}`);
      setCopiedLink(false);
    } catch (e) {
      setResult(null);
      // A ranked lookup that isn't on the list → auto-search World Athletics for that name.
      const notFound = !profile && /not in the .*ranking list|enough performances/i.test(e.message);
      if (notFound) { await searchFor(name, ev); }
      else { setError(e.message); }
    } finally { setBusy(false); }
  }

  // Copy the current scenario's URL (already in the address bar after a run) to the clipboard.
  function copyLink() {
    const url = window.location.href;
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(url).then(() => {
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 1800);
    }).catch(() => {});
  }

  // Auto-search WA for an unlisted name and surface matches the user can pick from.
  async function searchFor(name, ev = event) {
    setSearching(true); setError("");
    try {
      const { candidates: cands } = await searchAthletes(name, ev);
      setCandidates(cands);
      if (!cands.length) setError(`Couldn't find “${name}” on World Athletics. Check the spelling, or paste their profile link.`);
    } catch {
      setError(`${name} isn't in the top ~100, and the World Athletics search is unavailable right now — paste their profile link to run the analysis.`);
    } finally { setSearching(false); }
  }

  // Pick a search match → run the unranked analysis from that athlete's profile.
  function pickCandidate(c) {
    setCandidates(null);
    run({ ...form, athlete: c.name }, championship, event, c.slug);
  }

  // Click/pick an athlete → select it, preview their performances, and seed Time/Place/Category
  // from their best performance. A fresh selection clears any prior what-if result.
  async function selectAthlete(name) {
    setSelected(name); setResult(null); setAthleteInfo(null); setError("");
    setForm((s) => ({ ...s, athlete: name }));
    try {
      const ath = await getAthlete(championship, event, name);
      setAthleteInfo(ath);
      const best = bestPerf(ath, event);
      if (best) setForm((s) => ({ ...s, athlete: name, ...best }));
    } catch { /* keep current values if the lookup fails */ }
  }

  // Natural-language box: parse → switch event/championship if named → queue a run for that list.
  function interpret() {
    if (!query.trim()) return;
    const p = parseQuery(query, event);
    const champ = p.championship && meta.championships.some((c) => c.key === p.championship) ? p.championship : championship;
    const ev = p.eventKey && meta.events.some((e) => e.key === p.eventKey) ? p.eventKey : event;
    if (champ !== championship) changeChampionship(champ);
    if (ev !== event) changeEvent(ev);
    setError("");
    setPending({ p, champ, ev });
  }

  // Execute a queued NL run once the ranking list for its event/championship has loaded.
  useEffect(() => {
    if (!pending || !rankings) return;
    if (rankings.championship !== pending.champ || rankings.event !== pending.ev) return;
    const { p, champ, ev } = pending;
    setPending(null);
    (async () => {
      const athlete = matchAthlete(p.athlete, rankings.athletes);
      if (!athlete) {
        // Not on the ranking list → treat as unranked: search World Athletics for the name,
        // with the parsed scenario values pre-filled so picking a candidate runs the right what-if.
        const f = { ...form, subEvent: "main" };
        if (p.time) f.time = p.time;
        if (p.place != null) f.place = p.place;
        if (p.category) f.category = p.category;
        setForm(f);
        const name = extractName(query);
        if (!name) { setError("Couldn't tell which athlete you meant — try starting the question with their name."); return; }
        await searchFor(name, ev);
        return;
      }
      let f = { ...form, athlete, subEvent: "main" };
      try {
        const best = bestPerf(await getAthlete(champ, ev, athlete), ev);
        if (best) f = { ...f, ...best };           // default to their best performance…
      } catch { /* ignore lookup failure */ }
      if (p.time) f.time = p.time;                 // …then let explicit query values win
      if (p.place != null) f.place = p.place;
      if (p.category) f.category = p.category;
      setForm(f); setSelected(athlete);
      run(f, champ, ev);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, rankings]);

  if (!meta) return <p style={{ padding: 24, fontFamily: "'Archivo', system-ui, sans-serif", color: INK }}>Loading… {rankErr}</p>;

  const tabBase = { padding: "9px 16px", border: "none", borderRadius: 7, fontSize: 13.5, fontWeight: 700, cursor: "pointer" };
  const tab = (active) => ({ ...tabBase, background: active ? INK : "transparent", color: active ? SURFACE : "#6b7480" });
  const labelStyle = { display: "block", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: MUTE, fontWeight: 600, marginBottom: 5 };
  const inputStyle = { width: "100%", padding: "11px 12px", border: "1px solid #d8dce2", borderRadius: 9, fontSize: 14, background: "#fff" };
  const thCell = (align, padding) => ({ textAlign: align, padding, fontSize: 10.5, letterSpacing: "0.08em", color: MUTE, fontWeight: 600, textTransform: "uppercase" });

  const scoreSentence = `Ranking score: average of the best ${eventCfg.best_n || 5} results from the last ${eventCfg.window_months || 12} months, rounded down.`;
  const quota = (rankings && rankings.quota) || 30;
  const champClause = rankings && rankings.defending_champion ? ", champion auto-qualifies" : "";
  const isUltimate = championship === "road_to_ultimate";
  const assumptionLine = notContested
    ? champCfg.not_contested_note
    : isUltimate
      ? `${scoreSentence} Ultimate qualifying is worldwide: ${quota} places, no country cap, Olympic & World champions get wildcards.`
      : hasQual
        ? `${scoreSentence} Birmingham qualifying (Europe only): ${quota} places, max 3 per country${champClause}.`
        : `${scoreSentence} All nations — no quota or qualifying caps.`;

  // Examples target the qualifying bubble (qualification tabs) or athletes climbing the list
  // (world) — not the top names who are essentially safe. That's where a what-if actually tells
  // you something. (Phrasings are kept parseable by parseQuery: meet → category, "win"/"2nd" → place.)
  const exName = (a) => a && surnameOf(a.name);
  const at = (i) => list[Math.max(0, Math.min(list.length - 1, i))];
  let examples = [];
  if (list.length >= 6) {
    if (isUltimate) {
      const cut = list.findIndex((a) => a.name === zone.lastQualName);
      const i = cut >= 0 ? cut : Math.min(list.length - 1, quota - 1);
      examples = [
        `What if ${exName(at(i + 1))} wins a Diamond League meeting?`,
        `Does ${exName(at(i + 3))} make the Ultimate by winning their national champs?`,
        `What if ${exName(at(i))} finishes 2nd in a Diamond League final?`,
      ];
    } else if (hasQual) {
      const cut = list.findIndex((a) => a.name === zone.lastQualName);
      const i = cut >= 0 ? cut : Math.min(list.length - 1, quota - 1);
      examples = [
        `What if ${exName(at(i + 1))} finishes 2nd at the European Champs?`,
        `Does ${exName(at(i + 4))} make the team by winning their national champs?`,
        `What if ${exName(at(i))} wins a Diamond League meeting?`,
      ];
    } else {
      examples = [
        `What if ${exName(at(12))} wins a Diamond League meeting?`,
        `How far does ${exName(at(22))} climb with a Diamond League win?`,
        `What if ${exName(at(35))} finishes 2nd at the World Championships?`,
      ];
    }
  }

  return (
    <div style={{ fontFamily: "'Archivo', system-ui, sans-serif", color: INK, background: SURFACE, minHeight: "100vh" }}>
      <div style={{ maxWidth: 1320, margin: "0 auto", padding: narrow ? "0 14px 40px" : "0 28px 64px" }}>

        {/* HEADER */}
        <header style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 16, padding: "26px 0 18px", borderBottom: `2px solid ${INK}` }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: "0.22em", fontWeight: 600, color: MUTE, textTransform: "uppercase" }}>World Athletics · Middle Distance</div>
            <h1 style={{ margin: "4px 0 0", fontSize: narrow ? 23 : 30, fontWeight: 800, letterSpacing: "-0.02em" }}>Ranking What-If Studio</h1>
          </div>
          <div style={{ textAlign: "right", fontFamily: MONO, fontSize: 11, color: MUTE, lineHeight: 1.5 }}>
            <div>RANKINGS UPDATED</div>
            <div style={{ color: INK, fontWeight: 600, fontSize: 13 }}>{rankings ? daysAgo(rankings.rank_date) : notContested ? "—" : "…"}</div>
            {rankings && <div style={{ fontSize: 11 }}>{fmtDate(rankings.rank_date)}</div>}
          </div>
        </header>

        {/* TOGGLE + EVENT + ASSUMPTIONS */}
        <section style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14, padding: "18px 0" }}>
          <div style={{ display: "inline-flex", padding: 4, background: "#eceef2", borderRadius: 10, gap: 4, flexWrap: "wrap" }}>
            {meta.championships.map((c) => (
              <button key={c.key} onClick={() => changeChampionship(c.key)} style={tab(championship === c.key)}>{c.short_label || c.label}</button>
            ))}
          </div>
          <select value={event} onChange={(e) => changeEvent(e.target.value)} style={{ padding: "10px 14px", border: "1px solid #d8dce2", borderRadius: 9, background: "#fff", fontSize: 14, fontWeight: 600, color: INK }}>
            {meta.events.map((ev) => {
              const off = (champCfg.not_contested || []).includes(ev.key);
              return <option key={ev.key} value={ev.key}>{ev.label}{off ? " — not contested" : ""}</option>;
            })}
          </select>
          <div style={{ flex: 1 }} />
          <div style={{ fontFamily: MONO, fontSize: 11.5, color: "#6b7480", textAlign: "right", maxWidth: 460, lineHeight: 1.5 }}>{assumptionLine}</div>
        </section>

        {notContested ? (
          <NotContestedPanel eventLabel={eventLabel} champCfg={champCfg} events={meta.events}
            onWorld={() => changeChampionship("world")} onEvent={changeEvent} />
        ) : (<>

        {/* ASK BAR */}
        <section style={{ background: INK, borderRadius: 14, padding: "20px 22px", color: SURFACE, marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, letterSpacing: "0.14em", fontWeight: 600, color: ACCENT, textTransform: "uppercase" }}>
            <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: ACCENT }} />
            Ask a what-if
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && interpret()}
              placeholder="e.g. What if Wightman wins in Birmingham in 3:29.0?"
              style={{ flex: 1, minWidth: 280, padding: "14px 16px", border: "none", borderRadius: 10, background: "#14181f", color: SURFACE, fontSize: 16, outline: "none" }} />
            <button onClick={interpret} style={{ padding: "14px 26px", border: "none", borderRadius: 10, background: ACCENT, color: INK, fontSize: 15, fontWeight: 700, cursor: "pointer" }}>Interpret →</button>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {examples.map((ex) => (
              <button key={ex} onClick={() => { setQuery(ex); setTimeout(interpret, 0); }}
                style={{ padding: "7px 12px", border: "1px solid #2a313b", borderRadius: 20, background: "transparent", color: "#d8dce2", fontSize: 12.5, cursor: "pointer", fontFamily: MONO }}>
                {ex.length > 46 ? ex.slice(0, 44) + "…" : ex}
              </button>
            ))}
          </div>
        </section>

        {/* RESULT PANEL */}
        <section style={{ marginBottom: 24 }}>
          {result && (
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
              <button onClick={copyLink}
                style={{ padding: "6px 12px", border: "1px solid #d8dce2", borderRadius: 8, background: "#fff", color: copiedLink ? "#1f6b43" : "#6b7480", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: MONO }}>
                {copiedLink ? "Link copied ✓" : "Copy share link"}
              </button>
            </div>
          )}
          {result
            ? <ResultPanel rv={buildResultView(result, champCfg, form.qualify, methodOpen)} onToggle={() => setMethodOpen((v) => !v)} />
            : athleteInfo
              ? <AthletePreview info={athleteInfo} eventCfg={eventCfg} champCfg={champCfg} rankDate={rankings ? rankings.rank_date : null}
                  event={event} championship={championship} categories={categories} />
              : (
                <div style={{ border: "1.5px dashed #d8dce2", borderRadius: 14, padding: "40px 28px", textAlign: "center", color: MUTE }}>
                  <div style={{ fontSize: 17, fontWeight: 600, color: "#6b7480" }}>{busy ? "Running…" : selected ? `Loading ${selected}'s performances…` : "Run a what-if to see the impact"}</div>
                  <div style={{ fontSize: 13.5, marginTop: 6 }}>Pick an athlete from the table or type a question above. The rank change shows here.</div>
                </div>
              )}
        </section>

        {/* MAIN GRID */}
        <section style={{ display: "grid", gridTemplateColumns: narrow ? "1fr" : "1.55fr 1fr", gap: 22, alignItems: "start" }}>

          {/* RANKINGS TABLE */}
          <div style={{ background: BG, border: "1px solid #e7eaef", borderRadius: 14, overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "16px 18px 12px" }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>{(champCfg.scope_label || "World Ranking") + " — " + eventLabel}</h2>
              <span style={{ fontFamily: MONO, fontSize: 11, color: MUTE }}>{rankings ? `${list.length} athletes` : "loading…"}</span>
            </div>
            {/* e.g. "the DL Final winner also gets a wildcard" — a pending bye the list can't show yet */}
            {champCfg.qualification_footnote && (
              <div style={{ padding: "0 18px 10px", fontSize: 11.5, color: "#6b7480", lineHeight: 1.45 }}>
                ⓘ {champCfg.qualification_footnote}
              </div>
            )}
            <div style={{ maxHeight: 560, overflow: "auto" }}>
              {rankErr && <div style={{ padding: 18, color: "#9c352a", fontSize: 13 }}>{rankErr}</div>}
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
                <thead>
                  <tr style={{ position: "sticky", top: 0, background: "#f2f4f7", zIndex: 1 }}>
                    <th style={thCell("right", "9px 10px 9px 18px")}>#</th>
                    {hasQual && <th style={thCell("right", "9px 10px")} title="Position in the qualifying field after wildcard byes and any per-country cap">Quota</th>}
                    <th style={thCell("left", "9px 10px")}>Athlete</th>
                    <th style={thCell("left", "9px 10px")}>Nat</th>
                    <th style={thCell("right", "9px 18px 9px 10px")}>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {!rankings && !rankErr && Array.from({ length: 12 }).map((_, i) => (
                    <tr key={`sk-${i}`} style={{ borderBottom: "1px solid #f2f4f7" }}>
                      <td style={{ padding: "10px 10px 10px 18px", textAlign: "right" }}><span className="wf-skel" style={{ width: 16, animationDelay: `${(i % 6) * 0.08}s` }} /></td>
                      {hasQual && <td style={{ padding: "10px" }}><span className="wf-skel" style={{ width: 16, animationDelay: `${(i % 6) * 0.08}s` }} /></td>}
                      <td style={{ padding: "10px" }}><span className="wf-skel" style={{ width: 96 + (i % 4) * 24, animationDelay: `${(i % 6) * 0.08}s` }} /></td>
                      <td style={{ padding: "10px" }}><span className="wf-skel" style={{ width: 26, animationDelay: `${(i % 6) * 0.08}s` }} /></td>
                      <td style={{ padding: "10px 18px 10px 10px", textAlign: "right" }}><span className="wf-skel" style={{ width: 34, animationDelay: `${(i % 6) * 0.08}s` }} /></td>
                    </tr>
                  ))}
                  {list.map((a) => {
                    const isSel = selected === a.name;
                    const inZone = hasQual && zone.qualSet.has(a.name);
                    const compat = selCountry && a.country === selCountry && !isSel;
                    const bg = isSel ? INK : compat ? "#f2f4f7" : inZone ? "rgba(47,125,82,0.05)" : BG;
                    const fg = isSel ? SURFACE : INK;
                    return (
                      <React.Fragment key={a.competitor_id || a.name}>
                        <tr onClick={() => selectAthlete(a.name)}
                          style={{ cursor: "pointer", background: bg, color: fg, borderBottom: "1px solid #f2f4f7", transition: "background 0.12s" }}>
                          <td style={{ textAlign: "right", padding: "8px 10px 8px 18px", fontFamily: MONO, fontWeight: 600, color: isSel ? ACCENT : inZone ? "#1f8a4c" : "#9aa1ac" }}>{a.rank}</td>
                          {hasQual && (
                            <td style={{ textAlign: "right", padding: "8px 10px", fontFamily: MONO, fontSize: 12, fontWeight: 600, color: isSel ? ACCENT : zone.qualPos[a.name] ? "#1f8a4c" : "#c4c9d0" }}>
                              {zone.qualPos[a.name] || "—"}
                            </td>
                          )}
                          <td style={{ padding: "8px 10px", fontWeight: 600 }}>
                            <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", marginRight: 8, verticalAlign: "middle", background: isSel ? ACCENT : compat ? "#2f4a6b" : "transparent" }} />
                            {a.name}
                          </td>
                          <td style={{ padding: "8px 10px", fontFamily: MONO, fontSize: 12, color: "#6b7480" }}>{a.country}</td>
                          <td style={{ padding: "8px 18px 8px 10px", textAlign: "right", fontFamily: MONO, fontWeight: 600 }}>{Math.round(a.ranking_score)}</td>
                        </tr>
                        {hasQual && zone.lastQualName === a.name && (
                          <tr><td colSpan={5} style={{ padding: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 18px", background: INK, color: ACCENT, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em" }}>
                              <span style={{ flex: 1, height: 1, background: "#2a313b" }} />
                              {`QUALIFYING CUTOFF · ${rankings.quota} places${zone.invites.length ? (rankings.auto_invites ? ` · ${zone.invites.length} to wildcard${zone.invites.length > 1 ? "s" : ""}` : " · 1 to champion") : ""} · ≈ ${zone.cutoff != null ? Math.round(zone.cutoff) : "—"} pts`}
                              <span style={{ flex: 1, height: 1, background: "#2a313b" }} />
                            </div>
                          </td></tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* WHAT-IF CONSOLE */}
          <div style={{ background: BG, border: "1px solid #e7eaef", borderRadius: 14, padding: "18px 18px 20px", position: narrow ? "static" : "sticky", top: 16 }}>
            <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 700 }}>What-if console</h2>
            <p style={{ margin: "0 0 14px", fontSize: 12.5, color: MUTE }}>Fine-tune the scenario, then run it.</p>

            <label style={labelStyle}>Athlete</label>
            <input value={form.athlete}
              onChange={(e) => {
                const v = e.target.value;
                if (list.some((a) => a.name === v)) selectAthlete(v);              // picked from the datalist
                else { setForm({ ...form, athlete: v }); setSelected(v); }
              }}
              list="wf-athletes" placeholder="Type a name, or paste a World Athletics link" style={{ ...inputStyle, marginBottom: 6 }} />
            <p style={{ margin: "0 0 14px", fontSize: 11.5, color: MUTE, lineHeight: 1.4 }}>
              Unranked / not in the list? Paste their worldathletics.org profile link — first lookup can take ~30s.
            </p>
            <datalist id="wf-athletes">{list.map((a) => <option key={a.competitor_id || a.name} value={a.name} />)}</datalist>

            {eventCfg.input_events && eventCfg.input_events.length > 1 && (
              <div style={{ marginBottom: 14 }}>
                <label style={labelStyle}>Event for this performance</label>
                <select value={form.subEvent} onChange={(e) => setForm({ ...form, subEvent: e.target.value })}
                  style={{ ...inputStyle, marginBottom: 4 }}>
                  {eventCfg.input_events.map((ie) => (
                    <option key={ie.key} value={ie.key}>{ie.label}{ie.is_main ? " — main event" : ""}</option>
                  ))}
                </select>
                {form.subEvent !== "main" && (
                  <p style={{ margin: 0, fontSize: 11.5, color: MUTE, lineHeight: 1.4 }}>
                    Similar event — enter the time for this distance. At least {eventCfg.main_event_min} of {eventCfg.best_n} counting
                    results must be the {(eventCfg.input_events.find((ie) => ie.is_main) || {}).label}, so it can only fill a non-main slot.
                  </p>
                )}
                {(eventCfg.input_events.find((ie) => ie.key === form.subEvent) || {}).road && (
                  <p style={{ margin: "6px 0 0", fontSize: 11.5, color: "#6b7480", lineHeight: 1.4 }}>
                    Scored as a standard road 10K. World Athletics adjusts for course difficulty — a downhill or short course
                    can score a bit lower — so a specific race may come out below this.
                  </p>
                )}
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <label style={labelStyle}>Time</label>
                <input value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} placeholder="3:29.00" style={{ ...inputStyle, fontFamily: MONO }} />
              </div>
              <div>
                <label style={labelStyle}>Finish place</label>
                <input value={form.place} onChange={(e) => setForm({ ...form, place: e.target.value })} type="number" min="1" style={{ ...inputStyle, fontFamily: MONO }} />
              </div>
            </div>

            <label style={labelStyle}>Meet category</label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} style={{ ...inputStyle, marginBottom: 6 }}>
              {categories.map((c) => <option key={c} value={c}>{CAT_LABELS[c] || c}</option>)}
            </select>
            <button onClick={() => setCatHelp((v) => !v)}
              style={{ background: "none", border: "none", padding: 0, marginBottom: catHelp ? 8 : 14, color: "#6b7480", fontSize: 11.5, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", textDecoration: "underline", textUnderlineOffset: 2 }}>
              {catHelp ? "Hide category guide" : "ⓘ What do these categories mean?"}
            </button>
            {catHelp && (
              <div style={{ marginBottom: 14, padding: "12px 14px", background: "#f2f4f7", border: "1px solid #e7eaef", borderRadius: 10, fontSize: 12, color: "#3a414c", lineHeight: 1.5 }}>
                <p style={{ margin: "0 0 8px" }}>Higher categories award more placing points. World Athletics assigns each meet's exact category — this is a rough guide:</p>
                <ul style={{ margin: "0 0 8px", padding: 0, listStyle: "none", display: "grid", gap: 5 }}>
                  {CAT_INFO.map(([k, desc]) => (
                    <li key={k} style={{ display: "flex", gap: 8 }}>
                      <b style={{ flex: "none", width: 22, fontFamily: MONO, color: INK }}>{k}</b>
                      <span>{desc}</span>
                    </li>
                  ))}
                </ul>
                <p style={{ margin: "0 0 8px" }}>Heads-up: a <b>National Championships</b> is usually category <b>B</b>, whereas an ordinary national meeting is <b>C</b> — so check which one a meet actually is.</p>
                <a href={WA_RULES_URL} target="_blank" rel="noreferrer" style={{ color: "#2f4a6b", fontWeight: 600 }}>
                  Look up the official rules &amp; per-meet categories on World Athletics →
                </a>
              </div>
            )}

            {hasQual && (
              <label onClick={() => setForm((s) => ({ ...s, qualify: !s.qualify }))} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", padding: "10px 0 0", userSelect: "none" }}>
                <span style={{ width: 38, height: 22, borderRadius: 11, background: form.qualify ? "#1f8a4c" : "#d8dce2", position: "relative", flex: "none", boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.06)", transition: "background 0.15s", backgroundImage: form.qualify ? "radial-gradient(circle at 27px 11px, #fff 7px, transparent 7px)" : "radial-gradient(circle at 11px 11px, #fff 7px, transparent 7px)" }} />
                <span style={{ fontSize: 13.5, fontWeight: 600 }}>Resolve {(champCfg.short_label || "").replace(/^Road to /, "")} qualification</span>
              </label>
            )}

            <button onClick={() => run()} disabled={busy} style={{ width: "100%", marginTop: 16, padding: 14, border: "none", borderRadius: 10, background: INK, color: SURFACE, fontSize: 15, fontWeight: 700, cursor: busy ? "default" : "pointer", opacity: busy ? 0.7 : 1 }}>
              {busy ? "Running…" : "Run what-if"}
            </button>
            {error && <div style={{ marginTop: 12, padding: "10px 12px", background: "#fbe4e1", border: "1px solid #f0c5c0", borderRadius: 8, color: "#9c352a", fontSize: 12.5 }}>{error}</div>}

            {searching && <div style={{ marginTop: 12, fontSize: 12.5, color: MUTE }}>Searching World Athletics…</div>}
            {candidates && candidates.length > 0 && (
              <div style={{ marginTop: 12, border: "1px solid #e7eaef", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
                <div style={{ padding: "8px 12px", background: "#f2f4f7", fontSize: 11.5, fontWeight: 700, color: "#6b7480" }}>Not in the list — did you mean?</div>
                {candidates.map((c) => (
                  <button key={c.slug} onClick={() => pickCandidate(c)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: "9px 12px", border: "none", borderTop: "1px solid #f2f4f7", background: "transparent", cursor: "pointer", fontFamily: "inherit" }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600, color: INK }}>{c.name} <span style={{ fontFamily: MONO, fontSize: 11, color: "#6b7480" }}>{c.country}</span></div>
                    {c.disciplines && <div style={{ fontSize: 11, color: MUTE, marginTop: 1 }}>{c.disciplines}</div>}
                  </button>
                ))}
                <div style={{ padding: "7px 12px", fontSize: 11, color: MUTE, borderTop: "1px solid #f2f4f7" }}>Runs from their World Athletics profile — first lookup can take ~30s.</div>
              </div>
            )}
          </div>
        </section>

        </>)}

        <footer style={{ marginTop: 28, paddingTop: 14, borderTop: "1px solid #e7eaef", fontSize: 11, color: "#9aa1ac", fontFamily: MONO, lineHeight: 1.6 }}>
          <div>
            Live data from the World Athletics ranking API · {eventLabel} · edition {rankings ? rankings.rank_date : notContested ? "—" : "…"}. Result scores from the WA 2025 Scoring Tables; placing points from the 2026 World Ranking placing table. Other athletes held at current scores — only the chosen athlete moves.
          </div>
          <div style={{ marginTop: 8 }}>
            Sources:{" "}
            <a href={WA_RANKINGS_URL} target="_blank" rel="noreferrer" style={FOOT_LINK}>World Rankings</a> ·{" "}
            <a href={WA_SCORING_URL} target="_blank" rel="noreferrer" style={FOOT_LINK}>Scoring Tables</a> ·{" "}
            <a href={WA_RULES_URL} target="_blank" rel="noreferrer" style={FOOT_LINK}>Ranking Rules</a>
          </div>
          <div style={{ marginTop: 6 }}>
            Spot any issues?{" "}
            <a href={FEEDBACK_URL} target="_blank" rel="noreferrer" style={FOOT_LINK}>Let me know!</a>
          </div>
        </footer>
      </div>
    </div>
  );
}

// Shown when the selected event isn't on the championship's programme (e.g. the steeplechase
// or 10000m at the Ultimate Championship): a clear notice plus escape routes, in place of the
// ranking list and console. The event stays selectable so users learn it's absent by design.
function NotContestedPanel({ eventLabel, champCfg, events, onWorld, onEvent }) {
  const offKeys = new Set(champCfg.not_contested || []);
  const contested = events.filter((e) => !offKeys.has(e.key));
  const alsoOff = events.filter((e) => offKeys.has(e.key)).map((e) => e.label);
  return (
    <section style={{ border: "1.5px dashed #d8dce2", borderRadius: 16, padding: "48px 28px 40px", textAlign: "center", background: BG, animation: "wf-rise 0.4s ease both" }}>
      <div style={{ fontSize: 11, letterSpacing: "0.18em", textTransform: "uppercase", color: MUTE, fontWeight: 600 }}>{champCfg.scope_label}</div>
      <h2 style={{ margin: "10px 0 8px", fontSize: 22, fontWeight: 800, letterSpacing: "-0.01em" }}>{eventLabel} — not on the programme</h2>
      <p style={{ margin: "0 auto", maxWidth: 620, fontSize: 14.5, color: "#3a414c", lineHeight: 1.6 }}>
        {champCfg.not_contested_note || "This event is not contested at this championship."}
      </p>
      <p style={{ margin: "8px auto 24px", maxWidth: 620, fontSize: 12.5, color: MUTE, lineHeight: 1.6 }}>
        Events without a place on the programme: {alsoOff.join(" · ")}.
      </p>
      <button onClick={onWorld} style={{ padding: "12px 22px", border: "none", borderRadius: 10, background: INK, color: SURFACE, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>
        View {eventLabel} in the World Ranking →
      </button>
      <div style={{ marginTop: 24, fontSize: 11.5, letterSpacing: "0.1em", textTransform: "uppercase", color: MUTE, fontWeight: 600 }}>or pick a contested event</div>
      <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap", marginTop: 10 }}>
        {contested.map((e) => (
          <button key={e.key} onClick={() => onEvent(e.key)}
            style={{ padding: "7px 13px", border: "1px solid #d8dce2", borderRadius: 20, background: "#fff", color: INK, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
            {e.label}
          </button>
        ))}
      </div>
    </section>
  );
}

// Reverse-solver target rows ("reach the cutoff → ~3:41"), shared by the what-if result block
// and the click-to-preview card. Each row is met / reachable (shows the time) / unreachable.
function TargetRows({ rows }) {
  return (
    <div style={{ display: "grid", gap: 7 }}>
      {rows.map((t, i) => {
        const cap = t.label.charAt(0).toUpperCase() + t.label.slice(1);
        return (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, fontSize: 13 }}>
            <span style={{ color: INK }}>{cap}{" "}
              <span style={{ color: MUTE, fontFamily: MONO, fontSize: 11.5 }}>({t.target_score})</span>
            </span>
            <span style={{ fontFamily: MONO, fontWeight: 700, whiteSpace: "nowrap" }}>
              {t.status === "met" ? <span style={{ color: "#1f8a4c" }}>already there ✓</span>
                : t.status === "reachable" ? <span style={{ color: ACCENT }}>~{t.time}</span>
                  : <span style={{ color: MUTE, fontWeight: 600 }}>out of reach here</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// Counting-performances table, shared by the what-if result and the click-to-preview card.
// Rows may carry a `state` ("new" / "dropped") to flag the what-if diff; plain rows render clean.
function PerfTable({ rows }) {
  return (
    <div style={{ overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, minWidth: 540 }}>
        <thead>
          <tr style={{ color: MUTE, fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase" }}>
            {[["Meet", "left"], ["Event", "left"], ["Cat", "left"], ["Pl", "right"], ["Mark", "right"], ["Result", "right"], ["Place pts", "right"], ["Perf score", "right"]].map(([h, al]) => (
              <th key={h} style={{ textAlign: al, padding: "6px 8px", fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => {
            let tag = "", tagBg = "transparent", rowBg = "transparent", strike = "none", op = 1;
            if (p.state === "new") { tag = "NEW"; tagBg = "#1f8a4c"; rowBg = "#e3f3e9"; }
            else if (p.state === "dropped") { tag = "OUT"; tagBg = "#c62b35"; strike = "line-through"; op = 0.55; }
            return (
              <tr key={i} style={{ borderTop: "1px solid #f2f4f7", background: rowBg, textDecoration: strike, opacity: op }}>
                <td style={{ padding: "7px 8px" }}>
                  {tag && <span style={{ display: "inline-block", fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 4, marginRight: 7, background: tagBg, color: "#fff", verticalAlign: "middle", fontFamily: MONO }}>{tag}</span>}
                  {shortMeet(p.competition)}
                </td>
                <td style={{ padding: "7px 8px", color: "#6b7480" }}>{shortEvent(p)}</td>
                <td style={{ padding: "7px 8px", fontFamily: MONO }}>{p.category}</td>
                <td style={{ padding: "7px 8px", textAlign: "right", fontFamily: MONO }}>{p.place}</td>
                <td style={{ padding: "7px 8px", textAlign: "right", fontFamily: MONO }}>{p.mark}</td>
                <td style={{ padding: "7px 8px", textAlign: "right", fontFamily: MONO, color: "#6b7480" }}>{p.result_score}</td>
                <td style={{ padding: "7px 8px", textAlign: "right", fontFamily: MONO, color: "#6b7480" }}>{p.placing_score}</td>
                <td style={{ padding: "7px 8px", textAlign: "right", fontFamily: MONO, fontWeight: 600 }}>{p.performance_score}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Read-only card shown when an athlete is clicked (before any what-if): current standing +
// their counting performances. Running a what-if replaces this with the full ResultPanel.
function AthletePreview({ info, eventCfg, champCfg, rankDate, event, championship, categories }) {
  const lbl = { fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: MUTE, fontWeight: 600 };
  // Reverse solver: the time this athlete would need (at a chosen place/category) to reach the
  // cutoff / #1 — fetched live so it updates as the place/category controls change.
  const [rPlace, setRPlace] = useState(1);
  const [rCat, setRCat] = useState("B");   // default to a B-level meet (national champs) — realistic baseline
  const [wwit, setWwit] = useState(null);
  const [wErr, setWErr] = useState(false);
  useEffect(() => {
    let live = true;
    setWwit(null); setWErr(false);
    getRequired(championship, event, info.name, Math.max(1, parseInt(rPlace) || 1), rCat)
      .then((r) => { if (live) setWwit(r); })
      .catch(() => { if (live) setWErr(true); });
    return () => { live = false; };
  }, [championship, event, info.name, rPlace, rCat]);
  return (
    <div style={{ border: "1px solid #d8dce2", borderRadius: 16, overflow: "hidden", background: BG, animation: "wf-rise 0.4s ease both" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "16px 22px", background: INK, color: SURFACE }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.01em" }}>{info.name}</span>
          <span style={{ fontFamily: MONO, fontSize: 12, padding: "3px 8px", borderRadius: 5, background: "#14181f", color: ACCENT }}>{info.country}</span>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 11, color: "#9aa1ac" }}>{(champCfg.scope_label || "World Ranking") + (rankDate ? " · " + rankDate : "")}</span>
      </div>
      <div style={{ display: "flex", gap: 32, padding: "16px 24px", flexWrap: "wrap", borderBottom: "1px solid #d8dce2" }}>
        <div>
          <div style={lbl}>{champCfg.rank_label || "World rank"}</div>
          <div style={{ fontSize: 34, fontWeight: 800, marginTop: 4 }}>{info.rank != null ? `#${info.rank}` : "—"}</div>
        </div>
        <div>
          <div style={lbl}>Ranking score</div>
          <div style={{ fontSize: 34, fontWeight: 800, fontFamily: MONO, marginTop: 4 }}>{info.ranking_score != null ? Math.round(info.ranking_score) : "—"}</div>
        </div>
      </div>

      {/* reverse solver: what time it would take to reach key targets */}
      <div style={{ padding: "14px 24px", borderBottom: "1px solid #d8dce2" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: MUTE, fontWeight: 600 }}>What it would take</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#6b7480" }}>
            finishing
            <input type="number" min="1" value={rPlace} onChange={(e) => setRPlace(e.target.value)}
              style={{ width: 46, padding: "4px 6px", border: "1px solid #d8dce2", borderRadius: 7, fontFamily: MONO, fontSize: 12 }} />
            in a
            <select value={rCat} onChange={(e) => setRCat(e.target.value)}
              style={{ padding: "4px 6px", border: "1px solid #d8dce2", borderRadius: 7, fontSize: 12, background: "#fff" }}>
              {(categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            meet
          </div>
        </div>
        {wwit && wwit.targets.length > 0 ? <TargetRows rows={wwit.targets} />
          : wErr ? <div style={{ fontSize: 12.5, color: MUTE }}>Couldn't compute the required times right now.</div>
            : <div style={{ fontSize: 12.5, color: MUTE }}>Calculating…</div>}
      </div>

      <div style={{ padding: "14px 22px 20px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: MUTE, fontWeight: 600, marginBottom: 8 }}>
          Counting performances (best {eventCfg.best_n || 5} of {eventCfg.window_months || 12} mo)
        </div>
        <PerfTable rows={info.performances || []} />
        <div style={{ fontSize: 12, color: MUTE, marginTop: 12 }}>Set a time, place &amp; category on the right, then run a what-if to see the impact.</div>
      </div>
    </div>
  );
}

function ResultPanel({ rv, onToggle }) {
  const narrow = useIsNarrow();
  const rankB = badge(rv.rankDelta, "rank");
  const scoreB = badge(rv.scoreDelta, "score");
  const rankBadgeText = rv.rankDelta > 0 ? `▲ ${Math.abs(rv.rankDelta)} place${Math.abs(rv.rankDelta) === 1 ? "" : "s"}`
    : rv.rankDelta < 0 ? `▼ ${Math.abs(rv.rankDelta)} place${Math.abs(rv.rankDelta) === 1 ? "" : "s"}` : "no change";

  let verdict = null;
  if (rv.qual) {
    const q = rv.qual;
    const cap = q.maxPerCountry;   // null = no country cap (e.g. the Ultimate Championship)
    const fieldRules = cap != null ? `wildcard byes + ${cap}-per-country cap applied` : "wildcard byes applied; no country cap";
    if (q.status === "champion") verdict = { mark: "★", title: q.inviteReason ? `QUALIFIES — WILDCARD (${q.inviteReason.toUpperCase()})` : "QUALIFIES — DEFENDING CHAMPION BYE", detail: "Enters by wildcard regardless of ranking, exempt from any country cap, and consumes one place.", bg: "#e7eef6", fg: "#1c3a5e", bar: "#2f4a6b" };
    else if (q.status === "in") verdict = { mark: "✓", title: "INSIDE THE QUALIFYING ZONE", detail: `Auto-confirmed on score — qualifying position #${q.position} of ${q.quota} (${fieldRules}).`, bg: "#e3f3e9", fg: "#1b3d2a", bar: "#1f8a4c" };
    else if (q.status === "blocked") verdict = { mark: "≈", title: "ELIGIBLE — BUT FEDERATION'S CALL", detail: `Above the cutoff, yet ${q.countryAhead} higher-ranked ${q.country} athletes already hold the ${cap} places. The cap is a maximum — selection is ${q.country}'s decision.`, bg: "#fdebed", fg: "#2f4a6b", bar: "#2f4a6b" };
    else verdict = { mark: "✕", title: "OUTSIDE THE QUALIFYING ZONE", detail: `Below the cutoff by ${q.needPts} pts at this score.`, bg: "#fbe4e1", fg: "#8a2b22", bar: "#c62b35" };
  }

  return (
    <div style={{ border: "1px solid #d8dce2", borderRadius: 16, overflow: "hidden", background: BG, animation: "wf-rise 0.4s ease both" }}>
      {/* name bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "16px 22px", background: INK, color: SURFACE }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.01em" }}>{rv.name}</span>
          <span style={{ fontFamily: MONO, fontSize: 12, padding: "3px 8px", borderRadius: 5, background: "#14181f", color: ACCENT }}>{rv.country}</span>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 11, color: "#9aa1ac" }}>{rv.scopeLabel}</span>
      </div>

      {/* verdict */}
      {verdict && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "14px 22px", background: verdict.bg, color: verdict.fg, borderLeft: `5px solid ${verdict.bar}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 24, lineHeight: 1 }}>{verdict.mark}</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: "0.02em" }}>{verdict.title}</div>
              <div style={{ fontSize: 12.5, opacity: 0.9, marginTop: 2 }}>{verdict.detail}</div>
            </div>
          </div>
          <div style={{ fontFamily: MONO, fontSize: 11, textAlign: "right", flex: "none" }}>
            <div style={{ opacity: 0.7 }}>CUTOFF</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{rv.qual.cutoff != null ? Math.round(rv.qual.cutoff) : "—"}</div>
          </div>
        </div>
      )}

      {/* rank + score */}
      <div style={{ display: "grid", gridTemplateColumns: narrow ? "1fr" : "1.4fr 1fr" }}>
        <div style={{ padding: "22px 24px", borderRight: narrow ? "none" : "1px solid #d8dce2", borderBottom: narrow ? "1px solid #d8dce2" : "none" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: MUTE, fontWeight: 600 }}>{rv.rankLabel}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
            {rv.unranked && rv.outsideList ? (
              <>
                <span style={{ fontSize: narrow ? 22 : 26, fontWeight: 800, color: "#9aa1ac", letterSpacing: "-0.01em" }}>UNRANKED</span>
                <span style={{ fontSize: narrow ? 22 : 28, color: ACCENT }}>→</span>
                <span style={{ fontSize: narrow ? 26 : 34, fontWeight: 800, lineHeight: 1, letterSpacing: "-0.02em" }}>Outside the top {rv.listSize}</span>
                <span style={{ marginLeft: 6, alignSelf: "center", fontSize: 12.5, fontWeight: 700, padding: "4px 11px", borderRadius: 20, background: "#eceef2", color: "#6b7480", whiteSpace: "nowrap" }}>wouldn’t break into the list</span>
              </>
            ) : rv.unranked ? (
              <>
                <span style={{ fontSize: narrow ? 22 : 26, fontWeight: 800, color: "#9aa1ac", letterSpacing: "-0.01em" }}>UNRANKED</span>
                <span style={{ fontSize: narrow ? 22 : 28, color: ACCENT }}>→</span>
                <span style={{ fontSize: narrow ? 52 : 74, fontWeight: 900, lineHeight: 0.9, letterSpacing: "-0.04em" }}>#{rv.newRank}</span>
                <span style={{ marginLeft: 6, alignSelf: "center", fontSize: 12.5, fontWeight: 700, padding: "4px 11px", borderRadius: 20, background: "#eceef2", color: "#6b7480", whiteSpace: "nowrap" }}>would slot in (raw)</span>
              </>
            ) : (
              <>
                <span style={{ fontSize: narrow ? 40 : 56, fontWeight: 800, lineHeight: 1, color: "#9aa1ac", letterSpacing: "-0.03em" }}>#{rv.oldRank}</span>
                <span style={{ fontSize: narrow ? 22 : 28, color: ACCENT }}>→</span>
                <span style={{ fontSize: narrow ? 52 : 74, fontWeight: 900, lineHeight: 0.9, letterSpacing: "-0.04em" }}>#{rv.newRank}</span>
                <span style={{ marginLeft: 6, alignSelf: "center", fontSize: 12.5, fontWeight: 700, padding: "4px 11px", borderRadius: 20, background: rankB.bg, color: rankB.fg, whiteSpace: "nowrap" }}>{rankBadgeText}</span>
              </>
            )}
          </div>
        </div>
        <div style={{ padding: "22px 24px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 16 }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: MUTE, fontWeight: 600 }}>Ranking score</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 4, fontFamily: MONO, flexWrap: "wrap" }}>
              <span style={{ fontSize: 18, color: "#9aa1ac" }}>{Math.round(rv.oldScore)}</span>
              <span style={{ color: ACCENT }}>→</span>
              <span style={{ fontSize: 28, fontWeight: 600 }}>{rv.newScore}</span>
              <span style={{ fontSize: 13, fontWeight: 700, padding: "2px 8px", borderRadius: 20, background: scoreB.bg, color: scoreB.fg }}>{(rv.scoreDelta > 0 ? "+" : "") + rv.scoreDelta}</span>
            </div>
          </div>
          <div style={{ borderTop: "1px solid #d8dce2", paddingTop: 14 }}>
            <div style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: MUTE, fontWeight: 600 }}>
              This {rv.hypoEvent && !rv.hypoEvent.is_main ? rv.hypoEvent.label : "race"} scores
            </div>
            <div style={{ fontFamily: MONO, fontSize: 13, marginTop: 5, color: "#3a414c" }}>
              {rv.hypo.time} · result <b>{rv.hypo.result_score}</b> + place pts <b>{rv.hypo.placing_score}</b> = <b>{rv.hypo.performance_score}</b>
            </div>
            {rv.simNote ? (
              <div style={{
                marginTop: 8, fontSize: 12, lineHeight: 1.5, borderRadius: 6, padding: "9px 11px",
                background: rv.blockedByMainRule ? "#fdebed" : "#eef2f7",
                color: "#2f4a6b", border: `1px solid ${rv.blockedByMainRule ? "#f3c9cf" : "#d3dceb"}`,
              }}>
                {rv.blockedByMainRule && <b>Why didn’t this change the score? </b>}{rv.simNote}
              </div>
            ) : (
              <div style={{ fontSize: 11.5, color: "#9aa1ac", marginTop: 3 }}>
                {rv.counts ? "Counts toward the new average — it displaced a weaker result." : `Not strong enough to enter the best-${rv.bestN} — the score is unchanged.`}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* unranked profile summary */}
      {rv.unranked && rv.profileSummary && (() => {
        const ps = rv.profileSummary;
        const bestN = ps.counting_with_new + ps.short_of_full_set;   // size of a full counting set
        const shortNow = Math.max(0, bestN - ps.counting_now);       // results missing right now
        return (
          <div style={{ padding: "12px 24px", borderTop: "1px solid #d8dce2", background: "#eef2f7", fontSize: 12.5, color: "#2f4a6b", lineHeight: 1.55 }}>
            <b>Not currently ranked</b> for this event. A ranking score averages the best {bestN} results from the past {rv.windowMonths} months — {rv.name} has <b>{ps.counting_now}</b>
            {shortNow > 0 ? <>, so <b>{shortNow} more {shortNow === 1 ? "result is" : "results are"} needed</b> for a full set</> : ", a full set"}; this race would make {ps.counting_with_new}.
            {ps.best_rank ? ` Career-best rank #${ps.best_rank}${ps.best_rank_weeks ? ` (${ps.best_rank_weeks} weeks spent at it)` : ""}.` : ""}
            {ps.required_time ? ` To reach the ${ps.target_label} (${Math.round(ps.target_score)}), it would take about ${ps.required_time}.` : ""}
            {ps.incomplete_window ? " (Window data may be incomplete — couldn't reach the full results feed.)" : ""}
          </div>
        );
      })()}

      {/* reverse solver: what it would take to reach key targets */}
      {rv.whatWouldItTake && rv.whatWouldItTake.targets.length > 0 && (() => {
        const w = rv.whatWouldItTake;
        const ord = (n) => n === 1 ? "1st" : n === 2 ? "2nd" : n === 3 ? "3rd" : `${n}th`;
        return (
          <div style={{ padding: "14px 24px", borderTop: "1px solid #d8dce2" }}>
            <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: MUTE, fontWeight: 600, marginBottom: 9 }}>
              What it would take — finishing {ord(w.place)} in a category {w.category} meet
            </div>
            <TargetRows rows={w.targets} />
          </div>
        );
      })()}

      {/* methodology */}
      <div style={{ borderTop: "1px solid #d8dce2" }}>
        <button onClick={onToggle} style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 22px", background: SURFACE, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 700, color: INK, fontFamily: "inherit", textAlign: "left" }}>
          <span>Assumptions &amp; counting performances</span>
          <span style={{ transition: "transform 0.18s", transform: rv.open ? "rotate(180deg)" : "none", fontSize: 16, color: MUTE }}>⌄</span>
        </button>
        {rv.open && (
          <div style={{ padding: "4px 22px 22px" }}>
            <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: MUTE, fontWeight: 600, margin: "14px 0 8px" }}>Assumptions in play</div>
            <ul style={{ margin: "0 0 20px", padding: 0, listStyle: "none", display: "grid", gap: 7 }}>
              {rv.notes.map((n, i) => (
                <li key={i} style={{ display: "flex", gap: 9, fontSize: 12.5, color: "#3a414c", lineHeight: 1.45 }}>
                  <span style={{ color: ACCENT, fontWeight: 700, flex: "none" }}>—</span><span>{n}</span>
                </li>
              ))}
            </ul>
            <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: MUTE, fontWeight: 600, marginBottom: 8 }}>Counting performances (best {rv.bestN} of {rv.windowMonths} mo)</div>
            <PerfTable rows={rv.display} />
          </div>
        )}
      </div>
    </div>
  );
}
