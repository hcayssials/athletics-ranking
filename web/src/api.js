// The frontend's data layer. Same six functions the FastAPI server used to back — now
// served by the static data bundle + the local JS engine (see src/engine/), with the two
// live features (name search, unranked profiles) calling World Athletics' GraphQL API
// directly from the browser. Signatures and error-message shapes are unchanged so App.jsx
// (which regex-matches some messages) works as before.
import { buildCtx, loadEngineConfig, loadList, loadMeta, loadRankings } from "./engine/data.js";
import { findAthlete, requiredTargets, todayISO, whatIf } from "./engine/whatif.js";
import { fetchProfile, mainDisciplineName } from "./engine/profile.js";
import { searchCompetitors } from "./engine/graphql.js";

export const getMeta = () => loadMeta();

export async function getRankings(championship, event) {
  const r = await loadRankings(championship, event);
  if (r.error) throw new Error(r.error); // e.g. a list WA couldn't serve at build time
  return r;
}

export async function getAthlete(championship, event, name) {
  const cfg = await loadEngineConfig();
  const data = await loadList(cfg.championships, championship, event);
  const a = findAthlete(data, name);
  if (a === null) throw new Error(`Athlete '${name}' not found in this list.`);
  return a;
}

// Search World Athletics by name (unranked path); event-relevant candidates first.
export async function searchAthletes(name, event) {
  name = (name || "").trim();
  if (name.length < 2) return { name, candidates: [] };
  const cfg = await loadEngineConfig();
  let raw;
  try {
    raw = await searchCompetitors(cfg.graphql, name);
  } catch {
    throw new Error("World Athletics search is temporarily unavailable.");
  }

  let mainName = null, gender = null;
  const ev = event ? cfg.events[event] : null;
  if (ev) {
    mainName = ev.discipline_name || mainDisciplineName(ev.discipline);
    gender = ev.gender;
  }
  const relevance = (c) =>
    (mainName && (c.disciplines || "").includes(mainName) ? 4 : 0) +
    (gender && (c.gender || "").toLowerCase() === gender ? 2 : 0);

  const ranked = [...raw].sort((a, b) => relevance(b) - relevance(a));
  const candidates = ranked.slice(0, 8).filter((c) => c.urlSlug).map((c) => ({
    name: `${(c.givenName || "").trim()} ${(c.familyName || "").trim()}`.trim(),
    country: c.country ?? null,
    slug: (c.urlSlug || "").split("/").pop(),
    disciplines: c.disciplines ?? null,
    gender: c.gender ?? null,
  }));
  return { name, candidates };
}

export async function getRequired(championship, event, name, place, category) {
  const ctx = await buildCtx(championship, event);
  return requiredTargets(ctx, event, name, { championship, place, category });
}

// Run a what-if scenario. `body` is the old POST payload; `profile_country` is a new
// optional pass-through from the search candidate (the CORS-blocked profile page used to
// provide it server-side).
export async function runWhatIf(body) {
  const ctx = await buildCtx(body.championship, body.event, body.sub_event);
  const asOf = body.as_of || todayISO();

  let profileInfo = null;
  if (body.profile && findAthlete(ctx.getList(body.championship, body.event), body.athlete) === null) {
    const windowMonths = ctx.events[body.event].window_months;
    profileInfo = await fetchProfile(ctx, body.profile, body.event, asOf, windowMonths,
                                     { country: body.profile_country ?? null });
  }

  return whatIf(ctx, {
    event: body.event,
    athlete: body.athlete,
    time: body.time,
    category: body.category ?? "GW",
    place: body.place ?? 2,
    championship: body.championship ?? "road_to_birmingham",
    asOf: body.as_of ?? null,
    qualify: !!body.qualify,
    qualificationWindow: !!body.qualification_window,
    profileInfo,
    subEvent: body.sub_event ?? null,
  });
}
