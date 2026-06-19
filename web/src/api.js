// Thin fetch helpers for the WA ranking API. See CONTRACT.md for shapes.
async function j(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const getMeta = () => j("/api/meta");

export const getRankings = (championship, event) =>
  j(`/api/rankings?championship=${championship}&event=${event}`);

export const getAthlete = (championship, event, name) =>
  j(`/api/athlete?championship=${championship}&event=${event}&name=${encodeURIComponent(name)}`);

export const runWhatIf = (body) =>
  j("/api/whatif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
