// Port of wa_ranking/qualify.py — wildcards + entry-standard achievers + per-country cap + quota.
// Operates on ranking positions/scores only; see the Python module docstring.

export function qualifyingField(ranked, quota, {
  maxPerCountry = 3,
  defendingChampion = null,
  autoInvites = null,
  standardAchievers = null,
} = {}) {
  const invites = autoInvites ? [...autoInvites]
    : defendingChampion ? [{ ...defendingChampion, reason: "defending champion (bye)" }]
    : [];

  const slots = [];
  const counts = {};
  const blocked = [];
  let remaining = quota;
  let pos = 1;
  const inviteNames = new Set(invites.map((i) => i.name.toUpperCase()));
  const scoreOf = new Map(ranked.map((a) => [a.name.toUpperCase(), a.ranking_score ?? null]));
  const lookup = (key) => (scoreOf.has(key) ? scoreOf.get(key) : null);

  for (const inv of invites) {
    slots.push({
      position: pos,
      name: inv.name,
      country: inv.country ?? null,
      score: lookup(inv.name.toUpperCase()),
      reason: inv.reason ?? "wildcard",
    });
    remaining -= 1;
    pos += 1;
  }

  // Entry-standard achievers: in next, whatever their ranking; they count toward the cap
  // and are not capped by the quota (they can only squeeze the ranking fill).
  const standardNames = new Set();
  for (const s of standardAchievers || []) {
    const key = s.name.toUpperCase();
    if (inviteNames.has(key) || standardNames.has(key)) continue;
    standardNames.add(key);
    const country = s.country ?? null;
    if (maxPerCountry !== null && (counts[country] || 0) >= maxPerCountry) {
      blocked.push({
        name: s.name, country,
        score: lookup(key),
        reason: `country cap (${maxPerCountry})`,
        route: "entry standard",
      });
      continue;
    }
    slots.push({
      position: pos, name: s.name, country,
      score: lookup(key), reason: "entry standard",
      mark: s.mark ?? null,
    });
    counts[country] = (counts[country] || 0) + 1;
    remaining -= 1;
    pos += 1;
  }

  for (const a of ranked) {
    const key = a.name.toUpperCase();
    if (inviteNames.has(key) || standardNames.has(key)) continue; // in (or capped) already
    if (remaining <= 0) break;
    const country = a.country ?? null;
    if (maxPerCountry !== null && (counts[country] || 0) >= maxPerCountry) {
      blocked.push({
        name: a.name, country,
        score: a.ranking_score ?? null,
        reason: `country cap (${maxPerCountry})`,
        route: "ranking",
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
  const standardSlots = slots.filter((s) => s.reason === "entry standard");
  return {
    quota,
    max_per_country: maxPerCountry,
    slots,
    cutoff_score: rankingSlots.length ? rankingSlots[rankingSlots.length - 1].score : null,
    places_filled: slots.length,
    standard_places: standardSlots.length,
    ranking_places: rankingSlots.length,
    counts,
    blocked,
    defending_champion: defendingChampion,
    auto_invites: invites,
  };
}

// -> [status, slot]: qualified / blocked_country_cap / out. A qualified slot's `reason`
// says the route (wildcard label, "entry standard" or "ranking").
export function athleteStatus(field, name) {
  const nm = name.toUpperCase();
  for (const s of field.slots) if (s.name.toUpperCase() === nm) return ["qualified", s];
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
