"""The simple tips page: just the prediction for each market, by league and date."""

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Football Tips</title>
<style>
:root{--bg:#0b1016;--card:#151d27;--soft:#111821;--line:#263243;--text:#eef2f6;--mut:#8c9aab;--good:#34d399;--acc:#60a5fa;--warn:#fbbf24}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text)}
.wrap{max-width:820px;margin:0 auto;padding:0 16px}
header{position:sticky;top:0;z-index:5;background:rgba(11,16,22,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.top{display:flex;align-items:center;gap:10px;padding:14px 0 4px}
.logo{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#34d399,#60a5fa);display:grid;place-items:center}
h1{font-size:19px;margin:0}.sub{color:var(--mut);font-size:12px}
.chips{display:flex;gap:6px;overflow-x:auto;padding:8px 0 12px;scrollbar-width:none}.chips::-webkit-scrollbar{display:none}
.chip{flex:none;background:var(--soft);color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:6px 13px;font-size:14px;cursor:pointer}
.chip.on{background:rgba(96,165,250,.15);color:var(--acc);border-color:rgba(96,165,250,.5);font-weight:600}
h2{font-size:20px;margin:26px 0 4px;letter-spacing:-.3px}
.beta{font-size:12px;color:var(--warn);font-weight:600;margin-left:8px}
.note{color:var(--mut);font-size:13px;margin:0 0 6px}
.day{color:var(--mut);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;margin:16px 0 8px}
.m{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px}
.mt{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:8px}
.teams{font-weight:700;font-size:17px}.time{color:var(--mut);font-size:14px;white-space:nowrap}
ul{list-style:none;margin:0;padding:0;columns:2;column-gap:28px}
li{break-inside:avoid;padding:5px 0;border-bottom:1px solid rgba(38,50,67,.6);display:flex;justify-content:space-between;gap:10px;font-size:15px}
li span:first-child{color:var(--mut)}li b{font-weight:650;text-align:right}
li.star b{color:var(--good)}li.star b::before{content:"â˜… ";}
.top3{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.top3 span{background:rgba(52,211,153,.12);color:var(--good);border:1px solid rgba(52,211,153,.35);border-radius:999px;padding:3px 10px;font-size:13px;font-weight:600}
.empty{color:var(--mut);padding:30px 0;text-align:center}
footer{color:var(--mut);font-size:12px;padding:24px 0 40px;text-align:center}
footer a{color:var(--acc)}
.banner{background:rgba(251,191,36,.12);color:var(--warn);border:1px solid rgba(251,191,36,.35);border-radius:12px;padding:10px 12px;margin:12px 0;font-size:14px}
@media (max-width:620px){ul{columns:1}}
</style></head><body>
<header><div class="wrap">
<div class="top"><div class="logo">âš½</div><div><h1>Football Tips</h1><div class="sub">Updated <span id="gen"></span> Â· times are UK time</div></div></div>
<div class="chips" id="chips"></div>
</div></header>
<main class="wrap" id="app"></main>
<footer class="wrap">â˜… = strongest picks for that match. Tips, not guarantees. 18+ Â· BeGambleAware.org<br><a href="details.html">Detailed view (numbers, price checker, accuracy) â†’</a></footer>
<script>__SCRIPT__</script></body></html>"""

SCRIPT = r"""
const D = __DATA__;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
document.getElementById('gen').textContent = D.generated;
const ORDER = ['Champions League', 'Europa League', 'Conference League', 'Premier League', 'Championship', 'Serie A', 'Serie B', 'La Liga', 'Ligue 1', 'Bundesliga', 'Scottish Premiership'];
const ukNow = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date()).replace(',', '');
const upcoming = D.matches.filter(m => m.kickoff > ukNow);
const first = l => upcoming.filter(m => m.league === l).map(m => m.kickoff).sort()[0];
const leagues = ORDER.filter(l => upcoming.some(m => m.league === l)).sort((a, b) => first(a).slice(0, 10).localeCompare(first(b).slice(0, 10)) || ORDER.indexOf(a) - ORDER.indexOf(b));
let pick = 'All';

function tips(m) {
  const name = {home: m.home, away: m.away};
  const LABEL = {total_shots: 'Total shots', total_sot: 'Total shots on target', home_sot: `${m.home} shots on target`, away_sot: `${m.away} shots on target`,
    home_cards: `${m.home} bookings`, away_cards: `${m.away} bookings`, total_cards: 'Total bookings', home_fouls: `${m.home} fouls`, away_fouls: `${m.away} fouls`,
    home_gk: `${m.home} goal kicks`, away_gk: `${m.away} goal kicks`, free_kicks: 'Total free kicks'};
  const f = m.final, best = Object.keys(f).reduce((a, b) => f[a] >= f[b] ? a : b);
  const res = best === 'H' ? `${m.home} to win` : best === 'A' ? `${m.away} to win` : 'Draw';
  const out = [{l: 'Result', p: res + (f[best] < 45 ? ' (close call)' : ''), star: f[best] >= 60}];
  out.push({l: 'Both teams to score', p: m.btts >= 50 ? 'Yes' : 'No', star: m.btts >= 62 || m.btts <= 38});
  m.markets.forEach(k => {
    const rel = (k.expected - k.league_avg) / k.league_avg;
    let p;
    if (rel >= 0 && k.safe_over !== null) p = `Over ${k.safe_over}`;
    else if (rel < 0 && k.safe_under !== null) p = `Under ${k.safe_under}`;
    else p = `${k.over >= 50 ? 'Over' : 'Under'} ${k.line}`;
    out.push({l: LABEL[k.key], p, star: Math.abs(rel) > 0.12 && !k.estimate});
  });
  return out;
}

function card(m) {
  const t = tips(m);
  const stars = t.filter(x => x.star).slice(0, 3);
  return `<div class="m"><div class="mt"><span class="teams">${esc(m.home)} v ${esc(m.away)}</span><span class="time">${esc(m.time)}</span></div>
    ${stars.length ? `<div class="top3">${stars.map(x => `<span>${esc(x.l)}: ${esc(x.p)}</span>`).join('')}</div>` : ''}
    <ul>${t.map(x => `<li class="${x.star ? 'star' : ''}"><span>${esc(x.l)}</span><b>${esc(x.p)}</b></li>`).join('')}</ul></div>`;
}

function render() {
  const show = pick === 'All' ? leagues : [pick];
  let html = (Date.now() - D.generated_ms) / 3.6e6 > 20 ? '<div class="banner">These tips are more than 20 hours old. Update for fresh ones.</div>' : '';
  show.forEach(l => {
    const list = upcoming.filter(m => m.league === l);
    const beta = list.some(m => m.beta);
    html += `<h2>${esc(l)}${beta ? '<span class="beta">NEW Â· not yet tested</span>' : ''}</h2>`;
    let day = '';
    list.forEach(m => {
      if (m.iso !== day) { day = m.iso; html += `<div class="day">${new Date(day + 'T12:00:00').toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long'})}</div>`; }
      html += card(m);
    });
  });
  document.getElementById('app').innerHTML = html || '<div class="empty">No upcoming matches yet. New fixtures appear a few days before each round.</div>';
}

const chips = document.getElementById('chips');
['All', ...leagues].forEach(l => {
  const b = document.createElement('button');
  b.className = 'chip' + (l === 'All' ? ' on' : ''); b.textContent = l === 'All' ? 'All leagues' : l;
  b.addEventListener('click', () => { pick = l; [...chips.children].forEach(x => x.classList.toggle('on', x === b)); render(); window.scrollTo(0, 0); });
  chips.appendChild(b);
});
render();
"""
