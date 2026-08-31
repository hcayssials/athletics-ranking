// Port of wa_ranking/qualify.py — quota + wildcard byes + not-in-field + per-country cap.
// Operates on ranking positions/scores only; see the Python module docstring.

export function qualifyingField(ranked, quota, {
  maxPerCountry = 3,
  defendingChampion = null,
  autoInvites = null,
  notInField = null,
} = {}) {
  const invites = autoInvites ? [...autoInvites]
    : defendingChampion ? [{ ...defendingChampion, reason: "defending champion (bye)" }]
    : [];

  const slots = [];
  const counts = {};
  const blocked = [];
  const omitted = [];
  let remaining = quota;
  let pos = 1;
  const inviteNames = new Set(invites.map((i) => i.name.toUpperCase()));
  // Ranked athletes WA doesn't list in the field: no place, no country slot. A wildcard wins.
  const absent = new Map((notInField || [])
    .filter((x) => !inviteNames.has(x.name.toUpperCase()))
    .map((x) => [x.name.toUpperCase(), x]));

  for (const inv of invites) {
    slots.push({
      position: pos,
      name: inv.name,
      country: inv.country ?? null,
      score: null,
      reason: inv.reason ?? "wildcard",
    });
    remaining -= 1;
    pos += 1;
  }

  for (const a of ranked) {
    if (inviteNames.has(a.name.toUpperCase())) continue; // in via wildcard; cap-exempt
    if (absent.has(a.name.toUpperCase())) {
      omitted.push({
        name: a.name, country: a.country ?? null,
        score: a.ranking_score ?? null,
        reason: absent.get(a.name.toUpperCase()).reason ?? "not in the field",
      });
      continue; // ranked, but not entered
    }
    if (remaining <= 0) break;
    const country = a.country ?? null;
    if (maxPerCountry !== null && (counts[country] || 0) >= maxPerCountry) {
      blocked.push({
        name: a.name, country,
        score: a.ranking_score ?? null,
        reason: `country cap (${maxPerCountry})`,
      });
      continue;
    }
    slots.push({
      position: pos, name: a.name, country,
      score: a.ranking_score ?? null, reason: "ranking",
    });
    counts[country] = (counts[country] || 0) + 1;
    remaining -= 1;
    pos += 1;
  }

  const rankingSlots = slots.filter((s) => s.reason === "ranking");
  return {
    quota,
    max_per_country: maxPerCountry,
    slots,
    cutoff_score: rankingSlots.length ? rankingSlots[rankingSlots.length - 1].score : null,
    places_filled: slots.length,
    counts,
    blocked,
    omitted,
    defending_champion: defendingChampion,
    auto_invites: invites,
  };
}

// -> [status, slot]: qualified / not_in_field / blocked_country_cap / out.
export function athleteStatus(field, name) {
  const nm = name.toUpperCase();
  for (const s of field.slots) if (s.name.toUpperCase() === nm) return ["qualified", s];
  for (const o of field.omitted || []) if (o.name.toUpperCase() === nm) return ["not_in_field", o];
  for (const b of field.blocked) if (b.name.toUpperCase() === nm) return ["blocked_country_cap", b];
  return ["out", null];
}

// Score-sorted ranking list, optionally substituting one athlete's score.
export function buildRanked(athletes, { overrideName = null, overrideScore = null } = {}) {
  const rows = athletes.map((a) => {
    let score = a.ranking_score ?? null;
    if (overrideName && a.name.toUpperCase() === overrideName.toUpperCase()) score = overrideScore;
    return { name: a.name, country: a.country ?? null, ranking_score: score };
  });
  rows.sort((a, b) => {
    const ka = a.ranking_score !== null ? 1 : 0;
    const kb = b.ranking_score !== null ? 1 : 0;
    if (ka !== kb) return kb - ka;
    return (b.ranking_score || 0) - (a.ranking_score || 0);
  });
  return rows;
}
