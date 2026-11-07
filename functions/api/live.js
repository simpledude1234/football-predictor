// Live scores and stats for the Live tab: GET /api/live?slug=eng.1
// For games in play it also gives each player's fouls and cards so far.
// Cloudflare runs this on our own site. It fetches ESPN's free scoreboard
// itself, so ESPN only ever sees Cloudflare, never the visitor (no IP, no
// cookies, no browser details are passed on). It returns only a few numbers
// per game, accepts only our 11 competitions, and is not an open proxy.
// Replies are cached for 30 seconds, so ESPN is asked at most about twice a
// minute per league however many people have the page open.

const SLUGS = new Set(["eng.1", "eng.2", "ita.1", "ita.2", "esp.1", "fra.1", "ger.1", "sco.1",
  "uefa.champions", "uefa.europa", "uefa.europa.conf"]);
const BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/";
const HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "public, max-age=30",
  "X-Content-Type-Options": "nosniff",
  "X-Robots-Tag": "noindex",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
};

const reply = (body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), { status, headers: { ...HEADERS, ...extra } });

const num = v => { const n = Number(v); return Number.isFinite(n) && n >= 0 && n < 1000 ? n : null; };

function trim(ev) {
  const c = (ev.competitions || [])[0] || {};
  const st = c.status || ev.status || {};
  const sides = {};
  const idSide = {};
  for (const t of c.competitors || []) {
    const ha = t.homeAway;
    if (ha !== "home" && ha !== "away") continue;
    idSide[String(t.team && t.team.id)] = ha;
    const s = {};
    for (const x of t.statistics || []) s[x.name] = x.displayValue;
    sides[ha] = { name: String((t.team && t.team.displayName) || "").slice(0, 60), goals: num(t.score),
      shots: num(s.totalShots), sot: num(s.shotsOnTarget), fouls: num(s.foulsCommitted), corners: num(s.wonCorners),
      yellow: 0, red: 0 };
  }
  if (!sides.home || !sides.away) return null;
  for (const d of c.details || []) {
    const ha = idSide[String(d.team && d.team.id)];
    if (!ha) continue;
    if (d.redCard) sides[ha].red += 1;
    else if (d.yellowCard) sides[ha].yellow += 1;
  }
  return { id: String(ev.id).replace(/\D/g, "").slice(0, 12), state: String((st.type && st.type.state) || ""),
    status: String((st.type && st.type.name) || "").slice(0, 40), period: num(st.period), clock: num(st.clock / 60),
    display: String(st.displayClock || "").slice(0, 12), home: sides.home, away: sides.away };
}

// Players in a game in play, from ESPN's match summary: [name, on the pitch now (1/0), yellow, red, fouls so far].
// Only these five things per player are passed on.
function squads(s) {
  const out = {};
  for (const t of (s && s.rosters) || []) {
    const ha = t.homeAway;
    if (ha !== "home" && ha !== "away") continue;
    out[ha] = (t.roster || []).slice(0, 40).map(p => {
      const st = {};
      for (const x of p.stats || []) st[x.name] = x.value;
      const on = (p.starter || p.subbedIn) && !p.subbedOut ? 1 : 0;
      return [String((p.athlete && p.athlete.displayName) || "").slice(0, 60), on,
        num(st.yellowCards) || 0, num(st.redCards) || 0, num(st.foulsCommitted) || 0];
    }).filter(p => p[0]);
  }
  return out.home && out.away ? out : null;
}

async function espnJson(url) {
  // a brand-new request: nothing from the visitor is forwarded
  const r = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0", "Accept": "application/json" },
    redirect: "manual",            // never follow a redirect elsewhere
    cf: { cacheTtl: 30, cacheEverything: true },
  });
  if (r.status !== 200) throw new Error("feed");
  const text = await r.text();
  if (text.length > 3000000) throw new Error("feed");
  return JSON.parse(text);
}

export async function onRequestGet({ request }) {
  const slug = new URL(request.url).searchParams.get("slug") || "";
  if (!SLUGS.has(slug)) return reply({ error: "unknown competition" }, 400);
  const day = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  let data;
  try {
    data = await espnJson(`${BASE}${slug}/scoreboard?dates=${day}`);
  } catch (e) {
    return reply({ error: "live feed unavailable" }, 502, { "Cache-Control": "no-store" });
  }
  const games = (data.events || []).slice(0, 40).map(trim).filter(Boolean);
  // player details for games in play (for the player-to-be-booked picks); a game without them still shows
  await Promise.all(games.filter(g => g.state === "in").slice(0, 12).map(async g => {
    try { g.players = squads(await espnJson(`${BASE}${slug}/summary?event=${g.id}`)); } catch (e) { g.players = null; }
  }));
  return reply({ slug, at: Date.now(), games });
}

export async function onRequest() {   // anything other than GET
  return reply({ error: "method not allowed" }, 405, { "Allow": "GET" });
}
