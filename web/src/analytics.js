// Anonymous usage counting via GoatCounter (no cookies, no personal data, no athlete names).
// Off unless the build sets VITE_GOATCOUNTER_CODE (the deploy workflow passes the repo
// variable GOATCOUNTER_CODE); GoatCounter's script also ignores localhost, so dev never counts.
//
// What is sent: one page view per load (path only — the shared-scenario query string is
// dropped) and a handful of named events, e.g. "whatif/1500m_men". See `track` call sites.
const CODE = (import.meta.env && import.meta.env.VITE_GOATCOUNTER_CODE) || "";
export const analyticsOn = typeof window !== "undefined" && /^[a-z0-9][a-z0-9-]*$/i.test(CODE);

const queue = [];   // hits recorded before count.js has loaded
let ready = false;

function send(vars) {
  if (!analyticsOn) return;
  if (!ready) { queue.push(vars); return; }
  try { window.goatcounter.count(vars); } catch { /* counting must never break the app */ }
}

export function initAnalytics() {
  if (!analyticsOn || window.goatcounter) return;
  // no_onload: we count the page view ourselves so the query string never leaves the browser.
  window.goatcounter = { no_onload: true };
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://gc.zgo.at/count.js";
  s.dataset.goatcounter = `https://${CODE}.goatcounter.com/count`;
  s.onload = () => {
    ready = true;
    queue.splice(0).forEach(send);
  };
  document.head.appendChild(s);
  send({ path: window.location.pathname });
}

// A named event, e.g. track("whatif", "1500m_men") → "whatif/1500m_men" in the dashboard.
export function track(name, detail) {
  send({ path: detail ? `${name}/${detail}` : name, title: name, event: true });
}
