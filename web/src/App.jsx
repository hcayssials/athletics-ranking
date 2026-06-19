import React, { useEffect, useState } from "react";
import { getMeta, getRankings, runWhatIf } from "./api.js";

// Minimal, functional baseline — proves the API wiring. Restyle/extend in Claude Design.
const box = { border: "1px solid #ddd", borderRadius: 8, padding: 12, margin: "8px 0" };

export default function App() {
  const [meta, setMeta] = useState(null);
  const [championship, setChampionship] = useState("road_to_birmingham");
  const [event, setEvent] = useState("1500m_men");
  const [rankings, setRankings] = useState(null);
  const [form, setForm] = useState({ athlete: "", time: "3:30.00", category: "GW", place: 2,
                                      qualify: true, unranked: false, profile: "" });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { getMeta().then(setMeta).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    setRankings(null); setError(null);
    getRankings(championship, event).then(setRankings).catch((e) => setError(e.message));
  }, [championship, event]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null); setResult(null);
    try {
      setResult(await runWhatIf({
        event, championship, athlete: form.athlete, time: form.time,
        category: form.category, place: Number(form.place), qualify: form.qualify,
        profile: form.unranked ? form.profile : null,
      }));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  if (!meta) return <p style={{ padding: 20 }}>Loading… {error}</p>;

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 1000, margin: "0 auto", padding: 16 }}>
      <h1>World Athletics ranking what-if</h1>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select value={championship} onChange={(e) => setChampionship(e.target.value)}>
          {meta.championships.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select value={event} onChange={(e) => setEvent(e.target.value)}>
          {meta.events.map((ev) => <option key={ev.key} value={ev.key}>{ev.label}</option>)}
        </select>
      </div>

      {rankings && (
        <div style={box}>
          <b>Assumptions:</b> best {meta.events.find((e) => e.key === event)?.best_n} ·
          quota {rankings.quota ?? "—"} ·
          champion {rankings.defending_champion?.name ?? "—"} ·
          last update {rankings.rank_date}
        </div>
      )}

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        {/* Rankings table */}
        <div style={{ ...box, flex: "1 1 380px", maxHeight: 420, overflow: "auto" }}>
          {!rankings ? <p>Loading rankings… {error}</p> : (
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead><tr><th>#</th><th>Athlete</th><th>Nat</th><th>Score</th></tr></thead>
              <tbody>
                {rankings.athletes.map((a) => (
                  <tr key={a.competitor_id} style={{ cursor: "pointer" }}
                      onClick={() => setForm({ ...form, athlete: a.name, unranked: false })}>
                    <td>{a.rank}</td><td>{a.name}</td><td>{a.country}</td><td>{a.ranking_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* What-if form */}
        <form style={{ ...box, flex: "1 1 320px" }} onSubmit={submit}>
          <label><input type="checkbox" checked={form.unranked}
            onChange={(e) => setForm({ ...form, unranked: e.target.checked })} /> athlete not ranked</label>
          {form.unranked
            ? <p><input placeholder="WA profile slug e.g. jake-heyward-14597392"
                value={form.profile} onChange={set("profile")} style={{ width: "100%" }} /></p>
            : <p><input placeholder="athlete name" value={form.athlete} onChange={set("athlete")}
                style={{ width: "100%" }} /></p>}
          <p>Time <input value={form.time} onChange={set("time")} /> </p>
          <p>Place <input type="number" value={form.place} onChange={set("place")} style={{ width: 60 }} />
            {"  "}Category <select value={form.category} onChange={set("category")}>
              {meta.categories.map((c) => <option key={c}>{c}</option>)}
            </select></p>
          <label><input type="checkbox" checked={form.qualify}
            onChange={(e) => setForm({ ...form, qualify: e.target.checked })} /> resolve qualification</label>
          <p><button disabled={busy}>{busy ? "Running…" : "Run what-if"}</button></p>
        </form>
      </div>

      {error && <div style={{ ...box, color: "#b00" }}>{error}</div>}
      {result && <Result r={result} />}
    </div>
  );
}

function Result({ r }) {
  const q = r.qualification, ps = r.profile_summary;
  return (
    <div style={box}>
      <h2>{r.athlete} ({r.country})</h2>
      <p style={{ fontSize: 22 }}>
        {ps ? <>UNRANKED → would average <b>{r.new_score}</b>, rank ~#{r.new_rank} (raw)</>
            : <>{r.official_ranking_score} → <b>{r.new_score}</b> ({r.score_delta >= 0 ? "+" : ""}{r.score_delta})
                {"  ·  "}rank {r.old_rank} → {r.new_rank}</>}
      </p>
      <p>{r.hypothetical_performance.time}: result {r.hypothetical_performance.result_score} +
        placing {r.hypothetical_performance.placing_score} ={" "}
        <b>{r.hypothetical_performance.performance_score}</b></p>

      {q && (
        <p>Cutoff {q.cutoff_score} —{" "}
          {q.is_defending_champion ? "qualifies by bye (defending champion)"
            : !q.above_cutoff ? "below the cutoff"
            : q.country_ahead > 0
              ? `above the cutoff, but ${q.country_ahead} higher-ranked compatriots for ${q.max_per_country} places — the federation's call`
              : `above the cutoff — auto-confirmed (#${q.qual_position_new})`}</p>
      )}
      {ps && <p>Currently unranked (best ever #{ps.best_rank}); {ps.counting_with_new} counting
        result(s), {ps.short_of_full_set} short of a full set.
        {ps.required_time && ` To reach the ${ps.target_label} (${ps.target_score}) needs ~${ps.required_time}.`}</p>}

      <h4>Counting performances</h4>
      <ul>{r.new_counting.map((p, i) => (
        <li key={i} style={{ fontWeight: p.hypothetical ? "bold" : "normal" }}>
          {p.performance_score} — {p.mark} {p.category} P{p.place} {p.date}{p.hypothetical ? " ← new" : ""}
        </li>))}</ul>
    </div>
  );
}
