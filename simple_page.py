"""The simple tips page: just the prediction for each market, by league and date,
plus a Track record tab that marks every past tip right or wrong."""

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Football Tips</title>
<style>
:root{--bg:#0b1016;--card:#151d27;--soft:#111821;--line:#263243;--text:#eef2f6;--mut:#8c9aab;--good:#34d399;--bad:#f87171;--acc:#60a5fa;--warn:#fbbf24}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text)}
.wrap{max-width:820px;margin:0 auto;padding:0 16px}
header{position:sticky;top:0;z-index:5;background:rgba(11,16,22,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.top{display:flex;align-items:center;gap:10px;padding:14px 0 6px}
.logo{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#34d399,#60a5fa);display:grid;place-items:center}
h1{font-size:19px;margin:0}.sub{color:var(--mut);font-size:12px}
.tabs{display:flex;gap:4px;background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:3px;max-width:520px;margin-top:6px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--bad);margin-left:6px;vertical-align:middle}
.lstat{color:var(--mut);font-size:13px;margin:-2px 0 8px}.min{color:var(--bad);font-weight:700}
.tabs button{flex:1;background:none;border:0;color:var(--mut);padding:7px 12px;border-radius:9px;font-size:14px;font-weight:600;cursor:pointer}
.tabs button.on{background:#1b2532;color:var(--text)}
.chips{display:flex;gap:6px;padding:8px 0 12px;overflow-x:auto;scrollbar-width:none}.chips::-webkit-scrollbar{display:none}@media (min-width:600px){.chips{flex-wrap:wrap;overflow:visible}}
.chip{flex:none;background:var(--soft);color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:6px 13px;font-size:14px;cursor:pointer}
.chip.on{background:rgba(96,165,250,.15);color:var(--acc);border-color:rgba(96,165,250,.5);font-weight:600}
h2{font-size:20px;margin:26px 0 4px;letter-spacing:-.3px}
.beta{font-size:12px;color:var(--warn);font-weight:600;margin-left:8px}
.day{color:var(--mut);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;margin:16px 0 8px}
.m{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px}
.mt{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:8px}
.teams{font-weight:700;font-size:17px}.time{color:var(--mut);font-size:14px;white-space:nowrap}
ul{list-style:none;margin:0;padding:0;columns:2;column-gap:28px}
li{break-inside:avoid;padding:5px 0;border-bottom:1px solid rgba(38,50,67,.6);display:flex;justify-content:space-between;gap:10px;font-size:15px}
li span:first-child{color:var(--mut)}li b{font-weight:650;text-align:right}
li.star b{color:var(--good)}li.star b::before{content:"\2605  "}
.top3{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.top3 span{background:rgba(52,211,153,.12);color:var(--good);border:1px solid rgba(52,211,153,.35);border-radius:999px;padding:3px 10px;font-size:13px;font-weight:600}
.ok{color:var(--good)}.no{color:var(--bad)}.na{color:var(--mut)}
.score{font-weight:700;color:var(--text);margin-left:6px}
.sum{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;margin:12px 0}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.box .n{font-size:22px;font-weight:700}.box .l{color:var(--mut);font-size:13px}
details.m summary{list-style:none;cursor:pointer}details.m summary::-webkit-details-marker{display:none}
.res li span:first-child{color:var(--text)}.res li i{font-style:normal;color:var(--mut);font-size:13px;margin-left:6px}
.empty{color:var(--mut);padding:30px 0;text-align:center}
footer{color:var(--mut);font-size:12px;padding:24px 0 40px;text-align:center}
footer a{color:var(--acc)}
.banner{background:rgba(251,191,36,.12);color:var(--warn);border:1px solid rgba(251,191,36,.35);border-radius:12px;padding:10px 12px;margin:12px 0;font-size:14px}
.mode{max-width:340px;margin:16px 0 4px}.price{display:block;font-weight:400;font-size:13px;color:var(--mut)}
.info{color:var(--mut);font-size:13px;margin:6px 0 0}
.mk{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 6px}.mk .chip{font-size:13px;padding:5px 11px}
.row{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}
.row .g{color:var(--mut);font-size:12px;display:block;margin-top:2px}.row b{text-align:right;white-space:nowrap}
.sort{font-size:13px;color:var(--mut);margin:8px 0}.sort button{background:none;border:0;color:var(--acc);cursor:pointer;font-size:13px;padding:0 4px}.sort button.on{color:var(--text);font-weight:600}
.bestbox{background:linear-gradient(135deg,rgba(52,211,153,.10),rgba(96,165,250,.08));border:1px solid rgba(52,211,153,.35);border-radius:14px;padding:12px 16px;margin:14px 0 4px}
.bestbox h3{margin:0 0 2px;font-size:16px}.bestbox ol{margin:8px 0 0;padding-left:22px}
.bestbox li{display:list-item;border:0;padding:4px 0;font-size:14px}.bestbox .g{color:var(--mut);font-size:12px;display:block}
@media (max-width:620px){ul{columns:1}}
</style></head><body>
<header><div class="wrap">
<div class="top"><div class="logo">&#9917;</div><div><h1>Football Tips</h1><div class="sub">Updated <span id="gen"></span> &middot; times are UK time</div></div></div>
<div class="tabs" id="tabs"><button data-v="tips" class="on">Tips</button><button data-v="market">By market</button><button data-v="live" id="livetab">Live</button><button data-v="track">Track record</button></div>
<div class="chips" id="chips"></div>
</div></header>
<main class="wrap" id="app"></main>
<footer class="wrap">&#9733; = strongest picks for that match. &ldquo;No tip&rdquo; = a normal game for that market, so nothing worth backing. Tips, not guarantees. 18+ &middot; BeGambleAware.org<br><a href="details.html">Detailed view (numbers, price checker, accuracy) &rarr;</a></footer>
<script>__SCRIPT__</script></body></html>"""

SCRIPT = r"""
const D = __DATA__;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
document.getElementById('gen').textContent = D.generated;
const ORDER = ['Champions League', 'Europa League', 'Conference League', 'Premier League', 'Championship', 'Serie A', 'Serie B', 'La Liga', 'Ligue 1', 'Bundesliga', 'Scottish Premiership'];
const ukNow = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date()).replace(',', '');
const upcoming = D.matches.filter(m => m.kickoff > ukNow);
const T = D.track || {games: [], summary: {}, waiting: 0};
let view = 'tips', pick = 'All', mode = 'safe', mkt = null, sortBy = 'chance';
const dayName = iso => new Date(iso + 'T12:00:00').toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long'});

function leagueList(list, dateOf) {
  const first = l => list.filter(m => m.league === l).map(dateOf).sort()[0];
  const ls = ORDER.filter(l => list.some(m => m.league === l));
  return view !== 'track' ? ls.sort((a, b) => first(a).slice(0, 10).localeCompare(first(b).slice(0, 10)) || ORDER.indexOf(a) - ORDER.indexOf(b)) : ls;
}

function valueCard(m) {
  const t = (m.tips || []).filter(x => x.value);
  return `<div class="m"><div class="mt"><span class="teams">${esc(m.home)} v ${esc(m.away)}</span><span class="time">${esc(m.time)}</span></div>
    ${t.length ? `<ul>${t.map(x => `<li><span>${esc(x.label)}</span><b>${esc(x.pick)}<span class="price">${x.chance}% &middot; worth it at ${x.min_odds.toFixed(2)}+</span></b></li>`).join('')}</ul>`
      : '<div class="sub">No higher-price pick: the model has no strong view on the usual lines for this game.</div>'}</div>`;
}

function card(m) {
  if (mode === 'value') return valueCard(m);
  const t = (m.tips || []).filter(x => !x.value);
  const stars = t.filter(x => x.star).slice(0, 3);
  return `<div class="m"><div class="mt"><span class="teams">${esc(m.home)} v ${esc(m.away)}</span><span class="time">${esc(m.time)}</span></div>
    ${stars.length ? `<div class="top3">${stars.map(x => `<span>${esc(x.label)}: ${esc(x.pick)}</span>`).join('')}</div>` : ''}
    <ul>${t.map(x => x.skip ? `<li><span>${esc(x.label)}</span><b class="na" style="font-weight:400">No tip</b></li>` : `<li class="${x.star ? 'star' : ''}"><span>${esc(x.label)}</span><b>${esc(x.pick)}${x.confirmed ? '<br><i class="na" style="font-style:normal;font-weight:400;font-size:13px">in the starting line-up</i>' : ''}</b></li>`).join('')}</ul>
    ${t.some(x => x.key === 'player_booked') && !t.some(x => x.confirmed) ? '<div class="sub">Player picks are checked against the line-ups about an hour before kick-off.</div>' : ''}</div>`;
}

function bestBox() {
  const B = D.best || {}, list = (B[mode] || []).filter(b => pick === 'All' || b.league === pick);
  if (!list.length) return '';
  return `<div class="bestbox"><h3>Best bets &middot; ${esc(dayName(B.day))}</h3>
    <div class="sub">${mode === 'safe' ? 'The picks most likely to land' : 'The higher-price picks most likely to land'}, one per game. ${esc(D.learn_note || '')}</div>
    <ol>${list.map(b => `<li><b>${esc(b.label)}: ${esc(b.pick)}</b> &middot; ${b.chance}% &middot; ${mode === 'safe' ? 'fair price' : 'worth it at'} ${b.odds.toFixed(2)}${mode === 'safe' ? '' : '+'}
      <span class="g">${esc(b.match)} &middot; ${esc(b.time)} &middot; ${esc(b.league)}</span></li>`).join('')}</ol></div>`;
}

function tipsView() {
  const ls = leagueList(upcoming, m => m.kickoff);
  let html = (Date.now() - D.generated_ms) / 3.6e6 > 20 ? '<div class="banner">These tips are more than 20 hours old. Update for fresh ones.</div>' : '';
  html += `<div class="tabs mode"><button data-mode="safe" class="${mode === 'safe' ? 'on' : ''}">Safer tips</button><button data-mode="value" class="${mode === 'value' ? 'on' : ''}">Higher price</button></div>`;
  html += mode === 'safe' ? '<div class="info">Likely to land (72%+ chance), so usually short prices.</div>'
    : `<div class="info">Lines near even money (where bookmakers usually price both sides around 1.85). Back a pick only if your bookmaker's price is at least the &ldquo;worth it at&rdquo; price. ${esc(D.value_note || '')}</div>`;
  html += bestBox();
  (pick === 'All' ? ls : [pick]).forEach(l => {
    const list = upcoming.filter(m => m.league === l);
    if (!list.length) return;
    html += `<h2>${esc(l)}${list.some(m => m.beta) ? '<span class="beta">NEW &middot; not yet tested</span>' : ''}</h2>`;
    let day = '';
    list.forEach(m => { if (m.iso !== day) { day = m.iso; html += `<div class="day">${dayName(day)}</div>`; } html += card(m); });
  });
  return html || '<div class="empty">No upcoming matches yet. New fixtures appear a few days before each round.</div>';
}

// ------------------------------------------------------------ By market tab: one market, every game
const MK_ORDER = ['Match result', 'Both teams to score', 'Total goals', 'Total corners', 'Home corners', 'Away corners', 'Total bookings',
  'Home bookings', 'Away bookings', 'Player to be booked', 'Total shots on target', 'Home shots on target', 'Away shots on target',
  'Total shots', 'Home fouls', 'Away fouls', 'Total free kicks', 'Total offsides', 'Home offsides', 'Away offsides',
  'Total tackles', 'Home tackles', 'Away tackles', 'Home goal kicks', 'Away goal kicks'];
const MK_NAME = {'Match result': "Bookies' favourite"};
const shortDay = iso => new Date(iso + 'T12:00:00').toLocaleDateString('en-GB', {weekday: 'short', day: 'numeric', month: 'short'});

function marketView() {
  const games = upcoming.filter(m => pick === 'All' || m.league === pick);
  const rows = {}, none = {};
  games.forEach(m => (m.tips || []).forEach(t => {
    if (!!t.value !== (mode === 'value') || t.live) return;
    const name = t.market.replace(/^Higher price: /, '');
    if (t.skip) { none[name] = (none[name] || 0) + 1; return; }
    const ch = t.chance ?? (t.key === 'result' ? Math.round(m.final[t.side]) : t.key === 'btts' ? (t.side === 'yes' ? m.btts : 100 - m.btts) : null);
    (rows[name] = rows[name] || []).push({m, t, ch});
  }));
  const rank = n => MK_ORDER.indexOf(n) < 0 ? 99 : MK_ORDER.indexOf(n);
  const names = Object.keys(rows).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  let html = `<div class="tabs mode"><button data-mode="safe" class="${mode === 'safe' ? 'on' : ''}">Safer tips</button><button data-mode="value" class="${mode === 'value' ? 'on' : ''}">Higher price</button></div>`;
  if (!names.length) return html + '<div class="empty">No tips for these games yet.</div>';
  if (!names.includes(mkt)) mkt = names[0];
  html += `<div class="mk">${names.map(n => `<button class="chip${n === mkt ? ' on' : ''}" data-mkt="${esc(n)}">${esc(MK_NAME[n] || n)}</button>`).join('')}</div>`;
  const list = rows[mkt].slice().sort((a, b) => a.m.iso.localeCompare(b.m.iso) || (sortBy === 'chance'
    ? (b.ch ?? -1) - (a.ch ?? -1) || a.m.kickoff.localeCompare(b.m.kickoff)
    : a.m.kickoff.localeCompare(b.m.kickoff) || (b.ch ?? -1) - (a.ch ?? -1)));
  html += `<h2>${esc(MK_NAME[mkt] || mkt)}${mode === 'value' ? ' &middot; higher price' : ''}</h2>`;
  if (mkt === 'Match result') html += `<div class="info">From the bookmakers' prices, not the system's own pick: their prices beat our model on results. Shown for information.</div>`;
  if (/goal kicks/.test(mkt)) html += `<div class="info">Estimates: no free source records goal kicks, so these can't be checked.</div>`;
  html += `<div class="sort">Each day: <button data-sort="chance" class="${sortBy === 'chance' ? 'on' : ''}">most likely first</button>&middot;<button data-sort="time" class="${sortBy === 'time' ? 'on' : ''}">kick-off time</button></div>`;
  const days = [...new Set(list.map(r => r.m.iso))];
  html += days.map(d => `<div class="day">${dayName(d)}</div><div class="m">${list.filter(r => r.m.iso === d).map(({m, t, ch}) => `<div class="row"><span>${t.star ? '&#9733; ' : ''}${esc(m.home)} v ${esc(m.away)}<span class="g">${esc(shortDay(m.iso))} ${esc(m.time)} &middot; ${esc(m.league)}</span></span>
    <b>${esc(t.key === 'result' ? t.pick.replace(/ \(\d+%\)/, '') : t.pick)}${ch != null ? `<span class="price">${ch}% &middot; ${t.value ? 'worth it at ' + t.min_odds.toFixed(2) + '+' : 'fair price ' + (100 / ch).toFixed(2)}</span>` : ''}${t.confirmed ? '<span class="price">in the starting line-up</span>' : ''}</b></div>`).join('')}</div>`).join('');
  if (none[mkt]) html += `<div class="sub">${none[mkt]} more game${none[mkt] > 1 ? 's have' : ' has'} no tip for this market (a normal game, nothing worth backing).</div>`;
  return html;
}

function pct(s) { return s && s[1] ? Math.round(100 * s[0] / s[1]) + '%' : '–'; }

function trackView() {
  const games = T.games.filter(g => pick === 'All' || g.league === pick);
  if (!games.length) return `<div class="empty">No finished matches yet.<br>Every tip is saved before kick-off and marked &#10004; or &#10008; here once the result is in${T.waiting ? ` (${T.waiting} match${T.waiting > 1 ? 'es' : ''} waiting for results)` : ''}.</div>`;
  const sum = {};
  games.forEach(g => g.tips.forEach(t => { if (t.hit === null) return;
    (t.value ? [t.market, '__value__'] : t.live ? [t.market, '__live'] : [t.market, '__all__'].concat(t.star ? ['__star__'] : [])).concat(t.best ? ['__best_' + t.best] : []).forEach(k => { const s = sum[k] = sum[k] || [0, 0]; s[0] += t.hit ? 1 : 0; s[1]++; }); }));
  const markets = Object.keys(sum).filter(k => !k.startsWith('__')).sort((a, b) => sum[b][0] / sum[b][1] - sum[a][0] / sum[a][1]);
  let html = `<h2>How the tips did</h2><div class="sub">${games.length} finished match${games.length > 1 ? 'es' : ''}${pick === 'All' ? '' : ' in ' + esc(pick)}: ${games.filter(g => !g.replay).length} live (tips saved before kick-off) and ${games.filter(g => g.replay).length} replayed (predicted afterwards, using only information from before each game, to give a record from day one).</div>
    <div class="sum"><div class="box"><div class="n">${pct(sum.__all__)}</div><div class="l">All tips right (${sum.__all__ ? sum.__all__[0] + ' of ' + sum.__all__[1] : 0})</div></div>
    <div class="box"><div class="n ok">${pct(sum.__star__)}</div><div class="l">&#9733; tips right (${sum.__star__ ? sum.__star__[0] + ' of ' + sum.__star__[1] : 0})</div></div>
    <div class="box"><div class="n">${pct(sum.__value__)}</div><div class="l">Higher-price picks right (${sum.__value__ ? sum.__value__[0] + ' of ' + sum.__value__[1] : 0}). They need about 54%+ to profit at 1.85.</div></div>
    <div class="box"><div class="n ok">${pct(sum.__best_safe)}</div><div class="l">Best bets right (${sum.__best_safe ? sum.__best_safe[0] + ' of ' + sum.__best_safe[1] : 0})</div></div>
    <div class="box"><div class="n">${pct(sum.__best_value)}</div><div class="l">Higher-price best bets right (${sum.__best_value ? sum.__best_value[0] + ' of ' + sum.__best_value[1] : 0})</div></div>
    <div class="box"><div class="n">${pct(sum.__live)}</div><div class="l">Live picks right at 45' and 60' (${sum.__live ? sum.__live[0] + ' of ' + sum.__live[1] : 0})</div></div></div>
    <div class="m"><ul>${markets.map(k => `<li><span>${esc(k)}</span><b>${pct(sum[k])} <i class="na" style="font-style:normal;font-weight:400">(${sum[k][0]}/${sum[k][1]})</i></b></li>`).join('')}</ul></div>
    <h2>Every game</h2><div class="sub">Tap a game to see each tip. Goal kicks show &ndash; because no free source records them.</div>`;
  let day = '';
  games.forEach(g => {
    if (g.date !== day) { day = g.date; html += `<div class="day">${dayName(day)}</div>`; }
    const safe = g.tips.filter(t => !t.value && !t.live), ok = safe.filter(t => t.hit === true).length, n = safe.filter(t => t.hit !== null).length;
    html += `<details class="m"><summary><div class="mt"><span class="teams">${esc(g.home)} <span class="score">${esc(g.score)}</span> ${esc(g.away)}</span>
      <span class="time ${n && ok / n >= 0.6 ? 'ok' : ''}">${ok}/${n} right</span></div><div class="sub">${esc(g.league)}${g.replay ? ' &middot; replay' : ' &middot; live tip'}</div></summary>
      <ul class="res" style="margin-top:8px">${g.tips.map(t => `<li><span>${t.value ? '<i style="margin:0 6px 0 0">higher price</i>' : ''}${esc(t.label)}: ${esc(t.pick)}<i>${t.actual === '–' ? '' : '(' + esc(t.actual) + ')'}</i></span>
      <b class="${t.hit === true ? 'ok' : t.hit === false ? 'no' : 'na'}">${t.hit === true ? '&#10004;' : t.hit === false ? '&#10008;' : '&ndash;'}</b></li>`).join('')}</ul></details>`;
  });
  return html;
}

function chips() {
  const el = document.getElementById('chips'); el.innerHTML = '';
  const ls = view !== 'track' ? leagueList(upcoming, m => m.kickoff) : ORDER.filter(l => T.games.some(g => g.league === l));
  if (!ls.includes(pick)) pick = 'All';
  ['All', ...ls].forEach(l => {
    const b = document.createElement('button');
    b.className = 'chip' + (l === pick ? ' on' : ''); b.textContent = l === 'All' ? 'All leagues' : l;
    b.addEventListener('click', () => { pick = l; chips(); render(); window.scrollTo(0, 0); });
    el.appendChild(b);
  });
}

function render() { document.getElementById('app').innerHTML = view === 'tips' ? tipsView() : view === 'market' ? marketView() : view === 'live' ? liveView() : trackView(); }
document.querySelectorAll('#tabs button').forEach(b => b.addEventListener('click', () => {
  view = b.dataset.v; document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  document.getElementById('chips').style.display = view === 'live' ? 'none' : '';
  chips(); render(); window.scrollTo(0, 0);
  if (view === 'live') refreshLive();
}));
document.getElementById('app').addEventListener('click', e => {
  const b = e.target.closest('[data-mode]');
  if (b) { mode = b.dataset.mode; render(); return; }
  const k = e.target.closest('[data-mkt]');
  if (k) { mkt = k.dataset.mkt; render(); return; }
  const o = e.target.closest('[data-sort]');
  if (o) { sortBy = o.dataset.sort; render(); }
});
chips(); render();

// ------------------------------------------------------------ Live tab
__LIVE__
const SLUG = D.slugs || {};
let liveData = {}, liveErr = false, liveAt = 0, liveTimer = null;
// UK clock time -> real time (works in any time zone, and across clock changes)
const ukOffsetMs = (() => { const d = new Date(); const uk = Date.parse(new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false}).format(d).replace(' ', 'T') + 'Z'); return uk - d.getTime(); })();
const kickMs = m => Date.parse(m.kickoff.replace(' ', 'T') + ':00Z') - ukOffsetMs;
function inPlayWindow() {
  const now = Date.now();
  return D.matches.filter(m => m.espn_id && SLUG[m.code] && kickMs(m) - 10 * 60e3 <= now && now <= kickMs(m) + 135 * 60e3);
}
function setDot() {
  const live = inPlayWindow().some(m => (liveData[String(m.espn_id)] || {state: 'in'}).state === 'in');
  document.getElementById('livetab').innerHTML = 'Live' + (live ? '<span class="dot"></span>' : '');
}
async function refreshLive() {
  clearTimeout(liveTimer);
  const slugs = [...new Set(inPlayWindow().map(m => SLUG[m.code]))];
  if (slugs.length) {
    liveErr = false;
    await Promise.all(slugs.map(async s => {
      try {
        const r = await fetch('/api/live?slug=' + encodeURIComponent(s), {credentials: 'omit', cache: 'no-store'});
        if (!r.ok) throw new Error('feed');
        const j = await r.json();
        (Array.isArray(j.games) ? j.games : []).forEach(g => { if (g && g.home && g.away) liveData[String(g.id)] = g; });
      } catch (e) { liveErr = true; }
    }));
    liveAt = Date.now();
  }
  setDot();
  if (view === 'live') render();
  if (view === 'live' && document.visibilityState === 'visible') liveTimer = setTimeout(refreshLive, 60e3);
}
document.addEventListener('visibilitychange', () => {
  if (view === 'live' && document.visibilityState === 'visible') refreshLive(); else clearTimeout(liveTimer);
});

function livePickText(m, p) {
  if (p.key === 'result') return p.side === 'H' ? m.home + ' to win' : p.side === 'A' ? m.away + ' to win' : 'Draw';
  if (p.key === 'btts') return p.side === 'yes' ? 'Yes' : 'No';
  return (p.pick === 'over' ? 'Over ' : 'Under ') + p.line;
}
function liveCard(m) {
  const L = liveData[String(m.espn_id)];
  const head = `<div class="mt"><span class="teams">${esc(m.home)}${L && L.state !== 'pre' ? ` <span class="score">${esc(L.home.goals ?? 0)}&ndash;${esc(L.away.goals ?? 0)}</span>` : ''} ${esc(m.away)}</span>`;
  if (!L || L.state === 'pre') return `<div class="m">${head}<span class="time">${esc(m.time)}</span></div><div class="sub">${esc(m.league)} &middot; not started yet</div></div>`;
  if (L.state === 'post') return `<div class="m">${head}<span class="time">Full time</span></div><div class="sub">${esc(m.league)}</div></div>`;
  const R = LIVE.picks(m, L), lab = {};
  (m.tips || []).forEach(x => { lab[x.key] = x.label; });
  const two = (a, b) => `${esc(a ?? '–')}&ndash;${esc(b ?? '–')}`;
  let html = `<div class="m">${head}<span class="time min">${esc(L.display || '')}</span></div>
    <div class="lstat">${esc(m.league)} &middot; Shots ${two(L.home.shots, L.away.shots)} &middot; On target ${two(L.home.sot, L.away.sot)} &middot; Fouls ${two(L.home.fouls, L.away.fouls)} &middot; Bookings ${two(L.home.yellow + L.home.red, L.away.yellow + L.away.red)}${L.home.red || L.away.red ? ` &middot; Red cards ${two(L.home.red, L.away.red)}` : ''}</div>`;
  if (R.t == null || R.t < LIVE.CFG.from) return html + `<div class="sub">Live picks start at ${LIVE.CFG.from} minutes, once there is enough to go on.</div></div>`;
  if (R.late) return html + '<div class="sub">Too late in the game for new picks.</div></div>';
  html += '<ul>' + R.list.map(p => {
    const label = esc(lab[p.key] || (p.key === 'result' ? 'Result' : p.key === 'btts' ? 'Both teams to score' : p.key));
    if (!p.pick) return `<li><span>${label}</span><b class="na" style="font-weight:400">${p.why === 'landed' ? 'Already landed' : 'No tip'}</b></li>`;
    return `<li><span>${label}</span><b>${esc(livePickText(m, p))}</b></li>`;
  }).join('') + '</ul></div>';
  return html;
}
function liveView() {
  const ms = inPlayWindow();
  let html = `<h2>Live${LIVE.CFG.tested ? '' : '<span class="beta">NEW &middot; not yet tested</span>'}</h2>
    <div class="sub">${esc(LIVE.CFG.note || '')} Updates every minute while this tab is open. Bookmakers change live prices fast, so check the price before you bet: a pick at very short odds is not worth it.</div>`;
  if (liveErr) html += '<div class="banner">Live scores are not loading right now. Trying again in a minute.</div>';
  if (!ms.length) {
    const next = upcoming.filter(m => m.espn_id && SLUG[m.code])[0];
    return html + `<div class="empty">No games in play right now.${next ? `<br>Next: ${esc(next.home)} v ${esc(next.away)}, ${dayName(next.iso)} at ${esc(next.time)}.` : ''}</div>`;
  }
  const isIn = m => (liveData[String(m.espn_id)] || {}).state === 'in' ? 1 : 0;
  const order = ms.slice().sort((a, b) => isIn(b) - isIn(a) || a.kickoff.localeCompare(b.kickoff));
  return html + order.map(liveCard).join('') + (liveAt ? `<div class="sub" style="text-align:center">Checked at ${new Date(liveAt).toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'})}</div>` : '');
}
setDot();
setInterval(setDot, 5 * 60e3);
"""
