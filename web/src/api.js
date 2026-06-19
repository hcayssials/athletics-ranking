// Thin fetch helpers for the WA ranking API. See CONTRACT.md for shapes.
async function j(url, opts) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON body (e.g. a 500 page) */ }
  if (!res.ok) throw new Error((data && data.error) || `Server error (HTTP ${res.status})`);
  if (data === null) throw new Error("Unexpected non-JSON response from the server.");
  return data;
}

export const getMeta = () => j("/api/meta");

export const getRankings = (championship, event) =>
  j(`/api/rankings?championship=${championship}&event=${event}`);

export const getAthlete = (championship, event, name) =>
  j(`/api/athlete?championship=${championship}&event=${event}&name=${encodeURIComponent(name)}`);

export const searchAthletes = (name, event) =>
  j(`/api/search?name=${encodeURIComponent(name)}&event=${event}`);

export const runWhatIf = (body) =>
  j("/api/whatif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
