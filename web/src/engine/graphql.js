// Direct browser calls to the World Athletics GraphQL API (CORS-open; verified).
// Endpoint + key come from data/engine.json — the key is scraped from WA's own public JS
// at build time (not a secret) and refreshed by the weekly rebuild. If WA rotates the key
// mid-week these live features degrade until the next build; the core what-if (static
// data + local engine) is unaffected.

export const SEARCH_QUERY = `query S($q:String){
  searchCompetitors(query:$q){ aaAthleteId familyName givenName disciplines gender country urlSlug }
}`;

export const RESULTS_QUERY = `query D($id:Int,$resultsByYear:Int,$resultsByYearOrderBy:String){
  getSingleCompetitorResultsDiscipline(id:$id,resultsByYear:$resultsByYear,resultsByYearOrderBy:$resultsByYearOrderBy){
    resultsByEvent{ discipline disciplineCode results{ date competition venue category race place mark resultScore } }
  }
}`;

export async function gqlQuery(cfg, query, variables) {
  const res = await fetch(cfg.endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": cfg.key },
    body: JSON.stringify({ query, variables }),
  });
  if (!res.ok) throw new Error(`World Athletics API error (HTTP ${res.status}).`);
  const payload = await res.json();
  if (payload.errors) {
    throw new Error(`GraphQL errors: ${JSON.stringify(payload.errors).slice(0, 200)}`);
  }
  return payload.data;
}

export async function searchCompetitors(cfg, name) {
  const data = await gqlQuery(cfg, SEARCH_QUERY, { q: name });
  return data.searchCompetitors || [];
}
