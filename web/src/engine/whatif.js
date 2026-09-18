// Port of wa_ranking/whatif.py (what_if, required_targets) + fetch.find_athlete.
// Same structured result dicts, field for field — App.jsx renders them unchanged, and
// parity.test.mjs holds this file to the Python engine's exact output.
//
// ctx: { events, championships, placingScores, decay,
//        tables: {resultTableRelPath: [[seconds, score], ...]},
//        getList(championship, event) -> full ranking data }

import { parseTime, placingScore, pyRound, resultScore, scorePerformance, timeForResultScore } from "./scoring.js";
import { insertAndRecompute, rankingScore, rankPosition, resolveWindow, selectCounting } from "./ranking.js";
import { athleteStatus, buildRanked, qualifyingField } from "./qualify.js";

export const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function loadEvent(ctx, event) {
  if (!(event in ctx.events)) {
    throw new Error(`Unknown event '${event}'. Known: ${Object.keys(ctx.events).sort().join(", ")}`);
  }
  return ctx.events[event];
}

function loadChampionship(ctx, championship) {
  if (!(championship in ctx.championships)) {
    throw new Error(`Unknown championship '${championship}'. Known: ${Object.keys(ctx.championships).sort().join(", ")}`);
  }
  return ctx.championships[championship];
}

const champEventConfig = (champ, event) => (champ.events || {})[event] || {};

// Entry-standard marks only count in World Rankings Category C competitions and above.
const STANDARD_CATEGORIES = new Set(["OW", "DF", "GW", "GL", "A", "B", "C"]);

const table = (ctx, relPath) => {
  const t = ctx.tables[relPath];
  if (!t) throw new Error(`Result table not loaded: ${relPath}`);
  return t;
};

// Case-insensitive match on athlete name (full or partial) — fetch.find_athlete.
export function findAthlete(data, name) {
  const needle = name.trim().toLowerCase();
  const exact = data.athletes.filter((a) => a.name.toLowerCase() === needle);
  if (exact.length) return exact[0];
  const partial = data.athletes.filter((a) => a.name.toLowerCase().includes(needle));
  return partial.length === 1 ? partial[0] : partial.length ? partial[0] : null;
}

// Which discipline is the hypothetical in? Main by default, or one of the alt_events.
function resolveInputEvent(ev, subEvent) {
  const main = {
    key: "main",
    label: ev.discipline ?? "main event",
    discipline_code: ev.main_event_codes[0],
    result_table: ev.result_table,
    placing_event_group: ev.placing_event_group ?? "standard",
    indoor: false,
    is_main: true,
    standard_event: null,
  };
  if (!subEvent || subEvent === "main" || subEvent === main.discipline_code) return main;
  for (const alt of ev.alt_events || []) {
    if (alt.key === subEvent) {
      return {
        key: alt.key,
        label: alt.label,
        discipline_code: alt.discipline_code,
        result_table: alt.result_table,
        placing_event_group: alt.placing_event_group ?? ev.placing_event_group ?? "standard",
        indoor: alt.indoor ?? false,
        is_main: false,
        // WA alternative entry standard this similar event can satisfy (e.g. "Mile").
        standard_event: alt.standard_event ?? null,
      };
    }
  }
  const options = ["main", ...(ev.alt_events || []).map((a) => a.key)];
  throw new Error(`Unknown sub_event '${subEvent}'. Options: ${options.join(", ")}.`);
}

export function whatIf(ctx, {
  event, athlete, time: newTime,
  category = "GW", place = 2,
  championship = "road_to_beijing",
  asOf = null, indoor = false,
  qualificationWindow = false, qualify = false,
  profileInfo = null, subEvent = null,
}) {
  asOf = asOf || todayISO();
  const champ = loadChampionship(ctx, championship);
  const ev = loadEvent(ctx, event);
  const champEvent = champEventConfig(champ, event);
  if (qualify && !("quota" in champEvent)) {
    if (champ.contested_events_only) {
      throw new Error(
        `${ev.label ?? event} is not on the ${champ.label ?? championship} programme. `
        + (champ.not_contested_note ?? ""));
    }
    throw new Error(
      `Championship '${championship}' has no quota for event '${event}'; --qualify is `
      + "only meaningful for a qualification championship (e.g. road_to_beijing).");
  }
  const bestN = ev.best_n, window = ev.window_months;
  const inp = resolveInputEvent(ev, subEvent);
  const placingGroup = inp.placing_event_group;
  const mainLabel = ev.discipline ?? "main event";

  // Window: rolling (matches WA's published scores) or the championship's fixed one.
  const qw = champEvent.qualification_window || champ.qualification_window;
  let windowStart = null, windowEnd = null, windowKind = "rolling";
  if (qualificationWindow && qw) {
    windowStart = qw.start;
    windowEnd = qw.end;
    windowKind = "fixed";
  }
  const mainCodes = ev.main_event_codes || [];
  const mainMin = ev.main_event_min ?? 0;
  const sel = {
    windowStart, windowEnd,
    alwaysIncludeCompetitions: champ.always_include_competitions || [],
    mainEventCodes: mainCodes, mainEventMin: mainMin,
  };

  const data = ctx.getList(championship, event);
  let ath = findAthlete(data, athlete);
  if (ath === null) {
    if (!profileInfo) {
      const n = data.athletes.length;
      throw new Error(
        `'${athlete}' is either not in the ${championship} ${event} ranking list `
        + `(top ~${n}), or doesn't yet have enough performances in the window to be `
        + "ranked. If they're unranked, pass profile='<wa-slug>' (e.g. "
        + "'jake-heyward-14597392', the last part of their "
        + "worldathletics.org/athletes/... URL).");
    }
    ath = { name: profileInfo.name, country: profileInfo.country,
            ranking_score: null, rank: null,
            performances: profileInfo.performances };
  } else {
    profileInfo = null; // found on the list — the profile path doesn't apply
  }

  const perfs = ath.performances;

  // Score the hypothetical (fresh result -> no age decay); tag a similar event with its own
  // discipline code so best-N selection treats it as non-main.
  const breakdown = scorePerformance(ctx, table(ctx, inp.result_table), newTime, category, place,
                                     { perfDate: asOf, asOf, eventGroup: placingGroup });
  const newPerf = {
    date: asOf,
    competition: "(hypothetical)",
    category: category.toUpperCase(),
    discipline: inp.label,
    discipline_code: inp.discipline_code,
    indoor: indoor || inp.indoor,
    place,
    mark: String(newTime),
    result_score: breakdown.result_score,
    placing_score: breakdown.placing_score,
    performance_score: breakdown.performance_score,
    month_correction_applied: breakdown.decay !== 0,
    hypothetical: true,
  };

  const recompute = insertAndRecompute(perfs, newPerf, bestN, sel);
  const officialScore = ath.ranking_score ?? null;
  const recomputedOld = rankingScore(perfs, bestN, sel);
  const newScore = recompute.new_score;

  // Explain the main-event rule for a similar-event hypothetical (see whatif.py for the
  // "blocked by the rule" vs "just too slow" distinction).
  let similarEventNote = null;
  let blockedByMainRule = false;
  const similarCapacity = bestN - mainMin;
  if (!inp.is_main && mainMin > 0) {
    const newCounts = recompute.new_perf_counts;
    const free = selectCounting(perfs.concat([newPerf]), bestN, { ...sel, mainEventMin: 0 });
    const wouldCountUnconstrained = free.some((p) => p === newPerf);
    const mainCodeSet = new Set(mainCodes);
    const nonMain = recompute.new_counting.filter((p) => !mainCodeSet.has(p.discipline_code));
    const slots = similarCapacity === 1
      ? `the single non-${mainLabel} slot`
      : `${similarCapacity} non-${mainLabel} slots`;
    if (!newCounts && wouldCountUnconstrained) {
      blockedByMainRule = true;
      const occ = nonMain.length
        ? nonMain.reduce((m, p) => ((p.performance_score || 0) > (m.performance_score || 0) ? p : m))
        : null;
      const held = occ
        ? (occ && similarCapacity === 1
            ? `your ${occ.mark} (${occ.performance_score} pts) already fills it`
            : "your existing similar-event results already fill it")
        : "";
      similarEventNote =
        `This ${inp.label} scores well enough to be one of your top ${bestN} marks, but `
        + `ranking rules require at least ${mainMin} of ${bestN} counting results to be the `
        + `${mainLabel}. A ${inp.label} is a similar event, so it can only take ${slots}`
        + (held ? ` — and ${held}. ` : " — already filled. ")
        + `A faster ${inp.label} won't change your score; you'd need a faster ${mainLabel}.`;
    } else if (!newCounts) {
      similarEventNote =
        `This ${inp.label} doesn't beat any of your current counting results, so your `
        + `score is unchanged. (As a similar event it competes only for ${slots}; at least `
        + `${mainMin} of ${bestN} must be the ${mainLabel}.)`;
    } else {
      const newIds = new Set(recompute.new_counting);
      const displaced = recompute.old_counting.filter((p) => !newIds.has(p));
      if (!displaced.length) {
        similarEventNote =
          `This ${inp.label} counts — it filled an open slot in your set (you had `
          + `fewer than ${bestN} counting results).`;
      } else if (mainCodeSet.has(displaced[0].discipline_code)) {
        similarEventNote =
          `This ${inp.label} counts — it replaced your weakest counting ${mainLabel} `
          + `(${displaced[0].mark}). That's allowed because only ${mainMin} of `
          + `${bestN} need to be the ${mainLabel}; a similar event can fill the other `
          + `${similarCapacity}.`;
      } else {
        similarEventNote =
          `This ${inp.label} counts in ${slots}, replacing your previous `
          + `${displaced[0].mark} similar-event result. It can't push out one of `
          + `your ${mainLabel} results (${mainMin} of ${bestN} must be the ${mainLabel}).`;
      }
    }
  }

  // New rank: hold all other athletes at their current (official) ranking scores.
  const others = data.athletes.filter((a) => a !== ath).map((a) => a.ranking_score);
  const newRank = rankPosition(others, newScore);
  const oldRank = ath.rank ?? null;

  // Optional championship qualification: wildcard byes + entry-standard achievers + country
  // cap + world-ranking fill. champEvent is pre-resolved at build time (build_static.py):
  // where WA publishes a 'road to' feed, quota / standard / byes / standard_achievers come
  // from it, not from the JSON default — the same numbers the Python engine used.
  let qualification = null;
  let qualCfg = null;
  let stdList = [];
  if (qualify) {
    qualCfg = champEvent;
    const quota = champEvent.quota;
    const maxPc = "max_per_country" in champ ? champ.max_per_country : 3; // explicit null = no cap
    const champion = champEvent.defending_champion ?? null;
    const invites = champEvent.auto_invites ?? null;
    const inviteList = (invites && invites.length) ? invites
      : champion ? [{ ...champion, reason: "defending champion (bye)" }] : [];
    const achievers = champEvent.standard_achievers ?? null; // null = unknown (no feed snapshot)
    stdList = (achievers || []).map((s) => ({ name: s.name, country: s.country ?? null, mark: s.mark ?? null }));
    let athletes = data.athletes;
    if (profileInfo) { // unranked athlete isn't in the list — add him so he can slot in
      athletes = athletes.concat([{ name: ath.name, country: ath.country, ranking_score: null }]);
    }
    const isInvited = inviteList.some((i) => ath.name.toUpperCase() === i.name.toUpperCase());
    const alreadyAchieved = stdList.some((s) => ath.name.toUpperCase() === s.name.toUpperCase());

    // Does the hypothetical mark meet the entry standard (right event, window, category)?
    const es = entryStandardCheck(champEvent, ev, inp, breakdown, category, asOf,
                                  champEvent.qualification_window || qw,
                                  indoor || inp.indoor);
    const stdNew = stdList.concat(
      (es && es.meets && !alreadyAchieved)
        ? [{ name: ath.name, country: ath.country ?? null, mark: String(newTime), hypothetical: true }]
        : []);

    const rankedOld = buildRanked(athletes);
    const rankedNew = buildRanked(athletes, { overrideName: ath.name, overrideScore: newScore });
    const qopts = { maxPerCountry: maxPc, defendingChampion: champion, autoInvites: invites };
    const fieldOld = qualifyingField(rankedOld, quota, { ...qopts, standardAchievers: stdList });
    const fieldNew = qualifyingField(rankedNew, quota, { ...qopts, standardAchievers: stdNew });
    const [statusOld, slotOld] = athleteStatus(fieldOld, ath.name);
    const [statusNew, slotNew] = athleteStatus(fieldNew, ath.name);

    const cutoff = fieldNew.cutoff_score;
    const countryAhead = data.athletes.filter((a) =>
      a !== ath && a.country === ath.country && (a.ranking_score || 0) > newScore).length;
    qualification = {
      quota,
      quota_is_total_field: champ.quota_is_total_field ?? false,
      max_per_country: maxPc,
      defending_champion: champion,
      auto_invites: inviteList,
      is_defending_champion: Boolean(champion) && isInvited,
      is_auto_invited: isInvited,
      // Entry-standard route (World Championships): null when the championship has no
      // standard. standard_achievers_known=false means the field is modelled as if nobody
      // had the standard yet (no feed snapshot) — the UI says so.
      entry_standard: es,
      standard_achievers_known: achievers !== null,
      standard_achievers_count: stdList.length,
      already_achieved_standard: alreadyAchieved,
      standard_places: fieldNew.standard_places,
      ranking_places: Math.max(0, quota - inviteList.length - fieldNew.standard_places),
      route_old: route(statusOld, slotOld, isInvited),
      route_new: route(statusNew, slotNew, isInvited),
      qualification_source: champEvent.qualification_source ?? "config",
      cutoff_score: cutoff,
      above_cutoff: newScore !== null && cutoff !== null && newScore >= cutoff,
      status_old: statusOld,
      status_new: statusNew,
      qual_position_old: (slotOld || {}).position ?? null,
      qual_position_new: (slotNew || {}).position ?? null,
      country_count: fieldNew.counts[ath.country] ?? 0,
      country_ahead: countryAhead,
      field_new: fieldNew.slots,
      blocked_new: fieldNew.blocked,
    };
  }

  // Reverse "what would it take" for a ranked athlete: cutoff + #1 targets.
  let whatWouldItTake = null;
  if (!profileInfo) {
    const present = others.filter((s) => s !== null && s !== undefined);
    const top = present.length ? Math.max(...present) : null;
    const targets = [];
    if (qualification && qualification.cutoff_score !== null) {
      targets.push(["reach the qualifying cutoff", qualification.cutoff_score]);
    }
    if (top !== null) targets.push(["reach #1", top + 1]);
    const rows = targetsRequired(ctx, ev, recompute.old_counting, bestN,
                                 breakdown.placing_score, recomputedOld, targets);
    if (qualCfg && qualCfg.entry_standard) {
      rows.unshift(standardTarget(ctx, ev, qualCfg.entry_standard, ath.name, stdList));
    }
    if (rows.length) {
      whatWouldItTake = { place, category: category.toUpperCase(), targets: rows };
    }
  }

  // Unranked-athlete summary (profile-sourced): counting-set completeness + required time.
  let profileSummary = null;
  if (profileInfo) {
    const oldCounting = recompute.old_counting;
    const newCounting = recompute.new_counting;
    const listScores = data.athletes.map((a) => a.ranking_score).filter((s) => s);
    const target = qualification ? qualification.cutoff_score
      : listScores.length ? Math.min(...listScores) : null;
    const req = target !== null
      ? requiredTime(ctx, ev, oldCounting, bestN, breakdown.placing_score, target)
      : [null, null];
    profileSummary = {
      source: "profile",
      ranked: profileInfo.ranked,
      best_rank: profileInfo.best_rank,
      best_rank_weeks: profileInfo.best_rank_weeks,
      counting_now: oldCounting.length,
      counting_with_new: newCounting.length,
      short_of_full_set: Math.max(0, bestN - newCounting.length),
      target_score: target,
      target_label: qualification ? "qualifying cutoff" : "lowest ranked on list",
      required_time: req[0],
      required_result_score: req[1],
      incomplete_window: profileInfo.incomplete_window ?? false,
    };
  }

  return {
    championship,
    event,
    athlete: ath.name,
    country: ath.country ?? null,
    as_of: asOf,
    rank_date: data.rank_date ?? null,
    assumptions: {
      best_n: bestN,
      window_months: window,
      window_kind: windowKind,
      window_start: windowStart || resolveWindow(window, asOf)[0],
      window_end: windowEnd || asOf,
      category: category.toUpperCase(),
      place,
      indoor,
      result_table: ev.result_table,
      placing_edition: ctx.placingScores._meta.edition,
      decay_applied: newPerf.month_correction_applied,
      notes: [
        windowKind === "fixed"
          ? "Window is the fixed qualification period; recomputed scores may differ "
            + "from WA's published (rolling-window) scores."
          : "Rolling window matches WA's published ranking scores.",
        "Hypothetical result dated as_of, so no age-decay (month correction) is applied to it.",
        "Other athletes are held at their current ranking scores (static field).",
        mainMin
          ? `Similar events count; at least ${mainMin} of ${bestN} counting performances `
            + "must be the main event."
          : "Similar events count; no main-event minimum configured.",
        "Old/new rank uses the live ranking list; new rank assumes only this athlete changes.",
      ],
    },
    hypothetical_performance: breakdown,
    hypothetical_event: {
      key: inp.key, label: inp.label,
      discipline_code: inp.discipline_code, is_main: inp.is_main,
      indoor: newPerf.indoor,
    },
    main_event_rule: {
      main_label: mainLabel, main_event_min: mainMin, best_n: bestN,
      similar_capacity: similarCapacity, blocked_by_main_rule: blockedByMainRule,
    },
    similar_event_note: similarEventNote,
    official_ranking_score: officialScore,
    recomputed_old_score: recomputedOld,
    new_score: newScore,
    score_delta: recompute.delta,
    new_perf_counts: recompute.new_perf_counts,
    old_rank: oldRank,
    new_rank: newRank,
    list_size: data.athletes.length,
    rank_delta: oldRank === null ? null : oldRank - newRank,
    old_counting: recompute.old_counting,
    new_counting: recompute.new_counting,
    qualification,
    profile_summary: profileSummary,
    what_would_it_take: whatWouldItTake,
  };
}

// Time (before placing points) a single new race needs to lift the average to `target`.
function requiredTime(ctx, ev, countingOld, bestN, placing, target) {
  const scores = countingOld.map((p) => p.performance_score).sort((a, b) => b - a);
  const n = scores.length;
  const sum = (arr) => arr.reduce((s, x) => s + x, 0);
  const needPerf = n + 1 <= bestN
    ? target * (n + 1) - sum(scores)                 // new result just adds to the set
    : target * bestN - sum(scores.slice(0, bestN - 1)); // new result displaces the weakest
  const needResult = Math.ceil(needPerf - placing);
  return [timeForResultScore(table(ctx, ev.result_table), needResult), needResult];
}

// Reverse solver rows: met / reachable (time shown) / unreachable.
function targetsRequired(ctx, ev, countingOld, bestN, placing, currentScore, targets) {
  const rows = [];
  for (const [label, score] of targets) {
    if (score === null || score === undefined) continue;
    if (currentScore !== null && currentScore >= score) {
      rows.push({ label, kind: "score", target_score: pyRound(score), result_score: null, time: null, status: "met" });
      continue;
    }
    const [time, needResult] = requiredTime(ctx, ev, countingOld, bestN, placing, score);
    rows.push({ label, kind: "score", target_score: pyRound(score), result_score: needResult,
                time, status: time ? "reachable" : "unreachable" });
  }
  return rows;
}

// Reverse-solver row for the entry standard: the time IS the standard (no placing points
// involved); "met" when WA already lists the athlete as having achieved it.
function standardTarget(ctx, ev, standard, athlete, achievers) {
  const met = achievers.some((s) => athlete.toUpperCase() === s.name.toUpperCase());
  return { label: "meet the entry standard", kind: "standard",
           target_score: resultScore(table(ctx, ev.result_table), standard), result_score: null,
           time: standard, status: met ? "met" : "reachable" };
}

// How an athlete gets in: wildcard / standard / ranking / blocked_country_cap / out.
function route(status, slot, isInvited) {
  if (isInvited) return "wildcard";
  if (status === "qualified") return (slot || {}).reason === "entry standard" ? "standard" : "ranking";
  return status === "blocked_country_cap" ? status : "out";
}

// Does the hypothetical mark meet the championship's entry standard? Mirrors
// whatif.py:_entry_standard_check — main event (or a listed road/mile alternative, never an
// indoor mark), inside the qualification window, Category C meet or above. gap_seconds is
// signed (+ = slower), in hundredths so both engines agree exactly.
function entryStandardCheck(qualCfg, ev, inp, breakdown, category, asOf, window, indoor) {
  let standard = qualCfg.entry_standard;
  if (!standard) return null;
  let stdEvent = ev.discipline ?? "main event";
  let altOk = true;
  if (!inp.is_main) {
    const altName = inp.standard_event;
    const alt = (qualCfg.alt_entry_standards || []).find((a) => altName && a.event === altName) || null;
    if (alt) { standard = alt.entry_standard; stdEvent = altName; }
    else altOk = false;
  }
  const stdS = parseTime(standard);
  const hypS = breakdown.seconds;
  const gap = (pyRound(hypS * 100) - pyRound(stdS * 100)) / 100;
  const meetsMark = hypS <= stdS;
  let inside = true;
  if (window && window.start && window.end) inside = window.start <= asOf && asOf <= window.end;
  const validCat = STANDARD_CATEGORIES.has(category.toUpperCase());
  indoor = Boolean(indoor);
  const meets = meetsMark && inside && validCat && !indoor && altOk;
  const mainLabel = ev.discipline ?? "main event";
  let note;
  if (!altOk) {
    note = `No entry standard for the ${inp.label} — only a ${mainLabel} `
      + "(or a listed road/mile alternative) can meet the standard.";
  } else if (indoor) {
    note = "Indoor (short-track) marks count for the ranking but not for the entry standard.";
  } else if (!validCat) {
    note = `A category ${category.toUpperCase()} meet doesn't count for the entry standard `
      + "(Category C or above needed); it still counts for the ranking.";
  } else if (!inside) {
    note = `Outside the qualification window (${window.start} to ${window.end}).`;
  } else if (meetsMark) {
    note = `Meets the ${stdEvent} entry standard (${standard}) by ${Math.abs(gap).toFixed(2)}s.`;
  } else {
    note = `${gap.toFixed(2)}s short of the ${stdEvent} entry standard (${standard}).`;
  }
  return {
    standard,
    standard_event: stdEvent,
    standard_seconds: stdS,
    hypothetical_seconds: hypS,
    gap_seconds: gap,
    meets_mark: meetsMark,
    inside_window: inside,
    valid_category: validCat,
    indoor_invalid: indoor,
    event_valid: altOk,
    meets,
    note,
  };
}

// Standalone reverse solver (no hypothetical time) — whatif.required_targets.
export function requiredTargets(ctx, event, athlete, {
  championship = "road_to_beijing", place = 1, category = "GW",
} = {}) {
  const champ = loadChampionship(ctx, championship);
  const ev = loadEvent(ctx, event);
  const champEvent = champEventConfig(champ, event);
  const bestN = ev.best_n;
  const placingGroup = ev.placing_event_group ?? "standard";
  const sel = {
    alwaysIncludeCompetitions: champ.always_include_competitions || [],
    mainEventCodes: ev.main_event_codes || [],
    mainEventMin: ev.main_event_min ?? 0,
  };

  const data = ctx.getList(championship, event);
  const ath = findAthlete(data, athlete);
  if (ath === null) {
    throw new Error(`'${athlete}' is not in the ${championship} ${event} ranking list.`);
  }
  const oldCounting = selectCounting(ath.performances, bestN, sel);
  const placing = placingScore(ctx.placingScores, category, place, placingGroup);
  const others = data.athletes.filter((a) => a !== ath).map((a) => a.ranking_score);
  const present = others.filter((s) => s !== null && s !== undefined);
  const top = present.length ? Math.max(...present) : null;

  let cutoff = null;
  let stdList = [];
  if ("quota" in champEvent) {
    stdList = (champEvent.standard_achievers || []).map((s) => ({ name: s.name, country: s.country ?? null, mark: s.mark ?? null }));
    const field = qualifyingField(buildRanked(data.athletes), champEvent.quota, {
      maxPerCountry: "max_per_country" in champ ? champ.max_per_country : 3,
      defendingChampion: champEvent.defending_champion ?? null,
      autoInvites: champEvent.auto_invites ?? null,
      standardAchievers: stdList,
    });
    cutoff = field.cutoff_score;
  }

  const targets = [];
  if (cutoff !== null) targets.push(["reach the qualifying cutoff", cutoff]);
  if (top !== null) targets.push(["reach #1", top + 1]);
  const rows = targetsRequired(ctx, ev, oldCounting, bestN, placing,
                               ath.ranking_score ?? null, targets);
  if ("quota" in champEvent && champEvent.entry_standard) {
    rows.unshift(standardTarget(ctx, ev, champEvent.entry_standard, ath.name, stdList));
  }
  return { event, championship, athlete: ath.name,
           place, category: category.toUpperCase(), targets: rows };
}
