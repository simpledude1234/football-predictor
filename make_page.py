"""Download fresh data, predict upcoming matches, write predictions.html."""
import base64
import datetime as dt
import hashlib
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

import difflib

import pandas as pd

import espn
import europe
import fetch_data
import players
import predictor
import record
import simple_page
import tips

HERE = pathlib.Path(__file__).parent
OUT = HERE / "predictions.html"


def main():
    fetch_data.main()
    params_age_days = 999
    if predictor.PARAMS_FILE.exists():
        fitted = json.loads(predictor.PARAMS_FILE.read_text()).get("fitted")
        params_age_days = (dt.date.today() - dt.date.fromisoformat(fitted)).days if fitted else 999
    refit = "--refit" in sys.argv or params_age_days > 14   # re-test the model every 2 weeks
    params = predictor.load_or_fit_params(refit=refit)
    matches = predictor.predict_fixtures(params)
    try:
        matches += europe.predict(params)
    except Exception as e:          # European feed down: the leagues still work
        print(f"European cups skipped this time ({e})")
    matches.sort(key=lambda m: m["sort"])

    # ESPN: who gets booked, plus results for the track record
    cache, upcoming = {"matches": {}}, []
    try:
        cache, upcoming = espn.update()
    except Exception as e:
        print(f"ESPN update skipped this time ({e})")
    link_espn(matches, [{"code": u["code"], "day": _uk_day(u["event"]["date"]), "id": u["event"]["id"],
                         **{c["homeAway"]: c["team"]["displayName"] for c in u["event"]["competitions"][0]["competitors"]}}
                        for u in upcoming])
    pm = players.PlayerModel(cache)

    def finish(ms):
        for m in ms:
            exp = {k["key"]: k["expected"] for k in m["markets"]}
            m["players"] = players.top_picks(pm, m.get("espn_home"), m.get("espn_away"), m["iso"],
                                             exp.get("home_cards"), exp.get("away_cards")) if m.get("espn_home") else []
            m["tips"] = tips.make_tips(m)
    finish(matches)
    record.update(matches)

    # replay of recent past games (only once each), so the track record is useful from day one
    past = predictor.replay(params, days=28, skip=set(record.load()))
    if past:
        code_of = {v: k for k, v in espn.SLUGS.items()}
        link_espn(past, [{"code": code_of.get(e["slug"]), "day": e["date"], "id": e["id"], "home": e["home"],
                          "away": e["away"]} for e in cache.get("matches", {}).values()])
        finish(past)
        record.add_replay(past)
        print(f"Replayed {len(past)} past games for the track record")
    track = record.score(cache)

    now = dt.datetime.now(ZoneInfo("Europe/London"))
    payload = {"generated": now.strftime("%a %d %b %Y, %H:%M"), "generated_ms": int(now.timestamp() * 1000),
               "matches": matches, "report": params["report"], "record": None, "track": track}
    write_page(simple_page.HTML, simple_page.SCRIPT, payload, OUT)
    write_page(HTML, SCRIPT, payload, HERE / "details.html")
    print(f"Wrote {OUT} and details.html with {len(matches)} matches")


def _sim(a, b):
    a, b = espn.norm(a), espn.norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def _uk_day(iso):
    return pd.Timestamp(iso).tz_convert("Europe/London").strftime("%Y-%m-%d")


def link_espn(matches, candidates):
    """Find ESPN's copy of each fixture (same competition and day, closest team names).
    candidates: [{"code", "day", "id", "home", "away"}, ...]"""
    by_day = {}
    for c in candidates:
        by_day.setdefault((c["code"], c["day"]), []).append(c)
    linked = 0
    for m in matches:
        best, best_s = None, 0.0
        for c in by_day.get((m["code"], m["iso"]), []):
            t = {"home": c.get("home") or "", "away": c.get("away") or ""}
            sh, sa = _sim(m["home"], t["home"]), _sim(m["away"], t["away"])
            s = (sh + sa) / 2 if max(sh, sa) >= 0.7 else 0.0   # a team plays once a day
            if s > best_s:
                best, best_s = (c["id"], t), s
        if best and best_s >= 0.5:
            m["espn_id"], m["espn_home"], m["espn_away"] = best[0], best[1].get("home"), best[1].get("away")
            linked += 1
    print(f"Linked {linked} of {len(matches)} matches to ESPN")


def write_page(html, script, payload, out):
    # Data goes inside a <script>; escaping "<" stops any text in the data from
    # closing the script tag and running as code.
    data = json.dumps(payload, default=lambda o: o.item() if hasattr(o, "item") else float(o)).replace("<", "\\u003c").replace("\u2028", "\\u2028")
    script = script.replace("__DATA__", data)
    # Content-Security-Policy: the browser will run only this exact script,
    # load nothing from the internet, and send nothing anywhere.
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
    csp = (f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; "
           "img-src data:; base-uri 'none'; form-action 'none'")
    page = html.replace("__CSP__", csp).replace("__SCRIPT__", script)
    # refuse to publish garbled symbols (text saved in the wrong format)
    if any(bad in page for bad in ("â˜", "â€", "Â·", "ðŸ")):
        raise ValueError(f"{out.name}: garbled characters found; not publishing")
    tmp = out.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(out)


HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Football Predictor</title>
<style>
:root{--bg:#0b1016;--bg2:#111821;--card:#151d27;--card2:#1b2532;--line:#263243;--text:#eef2f6;--mut:#8c9aab;--good:#34d399;--goodbg:rgba(52,211,153,.12);--warn:#fbbf24;--bad:#f87171;--badbg:rgba(248,113,113,.12);--acc:#60a5fa;--accbg:rgba(96,165,250,.14)}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text)}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px}
header{position:sticky;top:0;z-index:5;background:rgba(11,16,22,.92);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 0 6px}
.brand{display:flex;align-items:center;gap:10px}.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#34d399,#60a5fa);display:grid;place-items:center;font-size:18px}
h1{font-size:18px;margin:0;letter-spacing:-.2px}.sub{color:var(--mut);font-size:12px}
.mut{color:var(--mut);font-size:13px}
.tabs{display:flex;gap:4px;background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:3px}
.tabs button{flex:1;background:none;border:0;color:var(--mut);padding:7px 12px;border-radius:9px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}
.tabs button.on{background:var(--card2);color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.4)}
.scroll{display:flex;gap:6px;overflow-x:auto;padding:8px 0 10px;scrollbar-width:none}.scroll::-webkit-scrollbar{display:none}
.chip{flex:none;background:var(--bg2);color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer}
.chip.on{background:var(--accbg);color:var(--acc);border-color:rgba(96,165,250,.5);font-weight:600}
.tools{display:flex;gap:8px;align-items:center;padding-bottom:10px}
input,select{background:var(--bg2);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:14px;outline:none}
input:focus,select:focus{border-color:var(--acc)}
#search{flex:1;min-width:0}
main{padding-top:6px;padding-bottom:40px}
.day{position:sticky;top:var(--hh,150px);z-index:3;background:var(--bg);padding:14px 0 8px;font-weight:700;font-size:15px;display:flex;justify-content:space-between;align-items:baseline}
.day span{color:var(--mut);font-weight:500;font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:0 0 12px;overflow:hidden}
.mh{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:14px 16px 10px}
.teams{font-weight:700;font-size:16px;letter-spacing:-.2px}.teams .v{color:var(--mut);font-weight:500;margin:0 4px}
.meta{color:var(--mut);font-size:12px;margin-top:2px}
.time{background:var(--bg2);border:1px solid var(--line);border-radius:8px;padding:3px 8px;font-size:13px;font-weight:600;white-space:nowrap}
.badge{display:inline-block;padding:1px 7px;border-radius:6px;font-size:11px;font-weight:600;margin-left:6px;background:rgba(251,191,36,.14);color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;padding:0 16px 14px}
.cell{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:9px 10px;min-width:0}
.cell.hi{border-color:rgba(52,211,153,.45);background:linear-gradient(0deg,var(--goodbg),var(--goodbg)),var(--bg2)}
.cell.lo{border-color:rgba(248,113,113,.45);background:linear-gradient(0deg,var(--badbg),var(--badbg)),var(--bg2)}
.cl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px;display:flex;justify-content:space-between;gap:4px}
.cv{font-size:20px;font-weight:700;margin:2px 0 1px;letter-spacing:-.3px}.cv small{font-size:12px;color:var(--mut);font-weight:500;margin-left:4px}
.ct{font-size:12px}.ct b{color:var(--good);font-weight:600}.ct i{font-style:normal;color:var(--mut)}
.est{color:var(--warn)}
.more{display:block;width:100%;background:none;border:0;border-top:1px solid var(--line);color:var(--acc);padding:10px;font-size:13px;font-weight:600;cursor:pointer}
.body{display:none;padding:0 16px 16px;border-top:1px solid var(--line)}.card.open .body{display:block}
table{width:100%;border-collapse:collapse;font-size:14px;table-layout:fixed;word-wrap:break-word}
th:nth-child(1),td:nth-child(1){width:40%}
th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:12px}
.num{text-align:right}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
section.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin:12px 0}
h2{font-size:15px;margin:16px 0 8px}
.res{display:flex;gap:6px;margin:8px 0}.res div{flex:1;text-align:center;background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:8px 4px}
.res b{display:block;font-size:18px}.big{border-color:var(--good)!important;background:var(--goodbg)!important}
.banner{background:rgba(251,191,36,.12);color:var(--warn);border:1px solid rgba(251,191,36,.35);border-radius:12px;padding:10px 12px;margin:12px 0}
.check{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:14px}
.check .f{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.check select{flex:2 1 170px}.check input{flex:1 1 80px;width:80px}
.out{font-size:14px;margin-top:4px}
.legend{color:var(--mut);font-size:12px;padding:8px 0 0}
@media (min-width:760px){.top{padding-top:16px}h1{font-size:20px}.tabs{max-width:520px}}
</style></head><body>
<header><div class="wrap">
<div class="top"><div class="brand"><div class="logo">⚽</div><div><h1>Football Predictor</h1><div class="sub">Updated <span id="gen"></span></div></div></div></div>
<div class="tabs" id="views"><button data-v="matches" class="on">Matches</button><button data-v="stand">Standouts</button><button data-v="record">My record</button><button data-v="how">Accuracy</button></div>
<div class="scroll" id="leagues"></div>
<div class="tools"><input id="search" type="search" placeholder="Search a team" autocomplete="off"></div>
</div></header>
<main class="wrap" id="app"></main>
<script>__SCRIPT__</script></body></html>"""

SCRIPT = r"""
const D = __DATA__;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const $ = id => document.getElementById(id);
$('gen').textContent = D.generated;
let league = 'All', view = 'matches', query = '';

// hide matches that have already kicked off (fixture times are UK time)
const ukNow = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date()).replace(',', '');
const upcoming = D.matches.filter(m => m.kickoff > ukNow);
const hoursOld = (Date.now() - D.generated_ms) / 3.6e6;

const leagues = ['All', ...new Set(upcoming.map(m => m.league))];
leagues.forEach(l => { const b = document.createElement('button'); b.textContent = l === 'All' ? 'All leagues' : l; b.className = 'chip' + (l === 'All' ? ' on' : '');
  b.addEventListener('click', () => { league = l; [...$('leagues').children].forEach(x => x.classList.toggle('on', x === b)); render(); }); $('leagues').appendChild(b); });
document.querySelectorAll('#views button').forEach(b => b.addEventListener('click', () => { view = b.dataset.v;
  document.querySelectorAll('#views button').forEach(x => x.classList.toggle('on', x === b)); render(); }));
window.addEventListener('resize', () => document.documentElement.style.setProperty('--hh', document.querySelector('header').offsetHeight + 'px'));
$('search').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); render(); });

const odds = p => p > 0 ? (100 / p).toFixed(2) : '-';
const cls = p => p >= 72 ? 'good' : p >= 60 ? 'warn' : '';
const LAB = {H: 'Home win', D: 'Draw', A: 'Away win'};

function overProb(mean, line, phi) {
  const k = Math.floor(line); let cdf = 0, p;
  if (phi == null || Math.abs(phi - 1) < 0.03) { p = Math.exp(-mean); for (let i = 0; i <= k; i++) { cdf += p; p *= mean / (i + 1); } }
  else if (phi > 1) { const r = mean / (phi - 1), q = mean / (r + mean); p = Math.pow(r / (r + mean), r); for (let i = 0; i <= k; i++) { cdf += p; p *= (i + r) / (i + 1) * q; } }
  else { const n = Math.max(Math.round(mean / (1 - phi)), k + 1), s = mean / n; p = Math.pow(1 - s, n); for (let i = 0; i <= k; i++) { cdf += p; p *= (n - i) / (i + 1) * s / (1 - s); } }
  return Math.min(1, Math.max(0, 1 - cdf));
}

function checker(m, idx) {
  const opts = [['H', 'Home win'], ['D', 'Draw'], ['A', 'Away win'], ['BY', 'BTTS Yes'], ['BN', 'BTTS No']]
    .concat(m.markets.map(k => ['m:' + k.key, k.label]));
  return `<div class="check" data-i="${idx}"><b>Check a bookmaker price</b>
    <div class="f"><select class="c-m">${opts.map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join('')}</select>
    <select class="c-s"><option value="o">Over</option><option value="u">Under</option></select>
    <input class="c-l" type="number" step="1" placeholder="line e.g. 9.5" inputmode="decimal">
    <input class="c-o" type="number" step="0.01" min="1" placeholder="odds e.g. 1.90" inputmode="decimal"></div>
    <div class="out mut">Pick a market, then type the line and the bookmaker's odds.</div></div>`;
}

document.addEventListener('input', e => {
  const box = e.target.closest('.check'); if (!box) return;
  const m = shown[+box.dataset.i]; if (!m) return;
  const sel = box.querySelector('.c-m').value, side = box.querySelector('.c-s').value;
  const line = parseFloat(box.querySelector('.c-l').value), price = parseFloat(box.querySelector('.c-o').value);
  const isStat = sel.startsWith('m:');
  box.querySelector('.c-s').style.display = box.querySelector('.c-l').style.display = isStat ? '' : 'none';
  let p = null, what = '';
  if (sel in LAB) { p = m.final[sel] / 100; what = LAB[sel]; }
  else if (sel === 'BY') { p = m.btts / 100; what = 'BTTS Yes'; }
  else if (sel === 'BN') { p = 1 - m.btts / 100; what = 'BTTS No'; }
  else if (!isNaN(line)) {
    if (line % 1 === 0) { box.querySelector('.out').innerHTML = 'Use a half line, like 9.5 (whole lines can be a push).'; return; }
    const k = m.markets.find(x => 'm:' + x.key === sel); const po = overProb(k.expected, line, k.phi);
    p = side === 'o' ? po : 1 - po; what = `${side === 'o' ? 'Over' : 'Under'} ${line} ${k.label}`;
  }
  const out = box.querySelector('.out');
  if (p === null) { out.innerHTML = 'Type the line (for example 9.5).'; return; }
  let txt = `<b>${esc(what)}</b>: our chance <b>${Math.round(100 * p)}%</b> · fair odds ${(1 / p).toFixed(2)}`;
  if (!isNaN(price) && price > 1) {
    const edge = p * price - 1;
    txt += edge > 0.05 ? ` · <span class="good">value +${Math.round(100 * edge)}% ✅</span>` : edge > 0 ? ` · <span class="warn">tiny edge +${Math.round(100 * edge)}%</span>` : ` · <span class="bad">no value (${Math.round(100 * edge)}%)</span>`;
  }
  out.innerHTML = txt;
});

function matchCard(m, idx) {
  const f = m.final, best = Object.entries(f).sort((a, b) => b[1] - a[1])[0][0];
  const btts = m.btts >= 50 ? `BTTS Yes ${m.btts}%` : `BTTS No ${100 - m.btts}%`;
  const low = [m.data_matches[0] < 10 ? m.home : null, m.data_matches[1] < 10 ? m.away : null].filter(Boolean);
  const rows = m.markets.map(k => {
    const tips = [];
    if (k.safe_over !== null) tips.push(`Over ${k.safe_over}`);
    if (k.safe_under !== null) tips.push(`Under ${k.safe_under}`);
    const rel = (k.expected - k.league_avg) / k.league_avg;
    const arrow = rel > 0.08 ? '<span class="good">▲ above normal</span>' : rel < -0.08 ? '<span class="bad">▼ below normal</span>' : '<span class="mut">normal</span>';
    return `<tr><td>${esc(k.label)}${k.estimate ? '<div class="est">estimate (not in free data)</div>' : ''}<div class="mut">league normal ${k.league_avg} · ${arrow}</div></td>
      <td class="num"><b>${k.expected.toFixed(1)}</b></td>
      <td class="num">O ${k.line}: <span class="${cls(k.over)}">${k.over}%</span><br>U ${k.line}: <span class="${cls(k.under)}">${k.under}%</span></td>
      <td class="tip">${tips.join('<br>')}</td></tr>`;
  }).join('');
  const SHORT = {total_shots: 'Total shots', total_sot: 'Total on target', home_sot: 'Home on target', away_sot: 'Away on target',
    home_cards: 'Home bookings', away_cards: 'Away bookings', total_cards: 'Total bookings', home_fouls: 'Home fouls', away_fouls: 'Away fouls',
    home_gk: 'Home goal kicks', away_gk: 'Away goal kicks', free_kicks: 'Free kicks'};
  const cells = m.markets.map((k, i) => {
    const rel = (k.expected - k.league_avg) / k.league_avg;
    const dir = rel > 0.08 ? 'hi' : rel < -0.08 ? 'lo' : '';
    let tip;
    if (dir === 'hi' && k.safe_over !== null) tip = `<b>Over ${k.safe_over}</b> <i>· 72%+</i>`;
    else if (dir === 'lo' && k.safe_under !== null) tip = `<b>Under ${k.safe_under}</b> <i>· 72%+</i>`;
    else tip = `<i>${k.over >= 50 ? 'Over' : 'Under'} ${k.line} · ${Math.max(k.over, k.under)}%</i>`;
    return `<div class="cell ${dir}"><div class="cl"><span>${i + 1}. ${SHORT[k.key] || esc(k.label)}</span>${k.estimate ? '<span class="est" title="estimate">est.</span>' : ''}</div>
      <div class="cv">${k.expected.toFixed(1)}<small>${dir === 'hi' ? '▲' : dir === 'lo' ? '▼' : ''} avg ${k.league_avg}</small></div><div class="ct">${tip}</div></div>`;
  }).join('');
  const resCell = `<div class="cell"><div class="cl"><span>13. Match result</span></div><div class="cv">${LAB[best]}<small>${f[best]}%</small></div><div class="ct"><i>H ${f.H}% · D ${f.D}% · A ${f.A}%</i></div></div>`;
  const bttsYes = m.btts >= 50;
  const bttsCell = `<div class="cell ${m.btts >= 60 ? 'hi' : m.btts <= 40 ? 'lo' : ''}"><div class="cl"><span>14. BTTS</span></div><div class="cv">${bttsYes ? 'Yes' : 'No'}<small>${bttsYes ? m.btts : 100 - m.btts}%</small></div><div class="ct"><i>fair odds ${odds(bttsYes ? m.btts : 100 - m.btts)}</i></div></div>`;
  return `<div class="card" data-i="${idx}"><div class="mh"><div><div class="teams">${esc(m.home)}<span class="v">v</span>${esc(m.away)}</div>
    <div class="meta">${esc(m.league)} · expected goals ${m.goals_exp[0]} – ${m.goals_exp[1]}${low.length ? `<span class="badge">little data: ${esc(low.join(', '))}</span>` : ''}</div></div>
    <div class="time">${esc(m.time)}</div></div>
    <div class="grid">${cells}${resCell}${bttsCell}</div>
    <button class="more" type="button">Full details and price checker ▾</button>
    <div class="body">
    <h2>13. Match outcome</h2>
    <div class="res">${['H', 'D', 'A'].map(k => `<div class="${k === best ? 'big' : ''}">${LAB[k]}<b>${f[k]}%</b><span class="mut">fair odds ${odds(f[k])}</span></div>`).join('')}</div>
    <div class="mut">Team stats alone: ${m.model.H}/${m.model.D}/${m.model.A}%. ${m.bookie ? 'Bookmakers: ' + m.bookie.H + '/' + m.bookie.D + '/' + m.bookie.A + '%.' : ''} The final figure follows bookmaker odds, because in testing they were more accurate than team stats alone.</div>
    <h2>14. Both teams to score</h2>
    <div class="res"><div class="${bttsYes ? 'big' : ''}">Yes<b>${m.btts}%</b><span class="mut">fair odds ${odds(m.btts)}</span></div><div class="${!bttsYes ? 'big' : ''}">No<b>${100 - m.btts}%</b><span class="mut">fair odds ${odds(100 - m.btts)}</span></div></div>
    <h2>1–12. Stats markets</h2>
    <table><tr><th>Market</th><th class="num">Expected</th><th class="num">Main line</th><th>Safer tips (72%+)</th></tr>${rows}</table>
    ${checker(m, idx)}
    <div class="mut" style="margin-top:8px">${m.referee ? 'Referee: ' + esc(m.referee) + ' (cards ×' + m.ref_factor + ' vs average). ' : ''}Matches in our data: ${esc(m.home)} ${m.data_matches[0]}, ${esc(m.away)} ${m.data_matches[1]}. Bookings = yellow + red cards.</div>
    </div></div>`;
}

function standouts(list) {
  const keys = list.length ? list[0].markets.map(k => [k.key, k.label]) : [];
  return keys.map(([key, label]) => {
    const r = list.map(m => { const k = m.markets.find(x => x.key === key); return {m, k, rel: k.expected / k.league_avg - 1}; }).sort((a, b) => b.rel - a.rel);
    const line = x => `<tr><td>${esc(x.m.home)} v ${esc(x.m.away)}<div class="mut">${esc(x.m.league)} · ${esc(x.m.date)}</div></td><td class="num"><b>${x.k.expected.toFixed(1)}</b> <span class="mut">(normal ${x.k.league_avg})</span></td><td class="num ${x.rel > 0 ? 'good' : 'bad'}">${x.rel > 0 ? '+' : ''}${Math.round(100 * x.rel)}%</td></tr>`;
    return `<section class="box"><h2>${esc(label)}</h2><div class="mut">Highest expected (lean Over)</div><table>${r.slice(0, 3).map(line).join('')}</table>
      <div class="mut" style="margin-top:6px">Lowest expected (lean Under)</div><table>${r.slice(-3).reverse().map(line).join('')}</table></section>`;
  }).join('');
}

function record() {
  const R = D.record;
  if (!R || !R.matches) return `<section class="box"><h2>My record</h2><p>The track record now lives on the main tips page: open it and tap <b>Track record</b>. Every tip is saved before kick-off and marked right or wrong once the result is in.</p><p><a href="index.html" style="color:var(--acc)">Go to the tips page &rarr;</a></p></section>`;
  const rows = R.groups.map(g => `<tr><td>${esc(g.market)}<div class="mut">${esc(g.kind)}</div></td><td class="num">${g.n}</td><td class="num">${g.promised}%</td><td class="num"><b class="${g.hit >= g.promised - 3 ? 'good' : 'bad'}">${g.hit}%</b></td></tr>`).join('');
  return `<section class="box"><h2>My record: ${R.matches} finished matches</h2><div class="mut">${esc(R.from)} to ${esc(R.to)}. Predictions saved before kick-off, then checked against real results.</div>
    <table style="margin-top:8px"><tr><th>Market</th><th class="num">Tips</th><th class="num">Promised</th><th class="num">Landed</th></tr>${rows}</table>
    <p class="mut">Small numbers swing a lot. Judge it after 100+ tips per market.</p></section>`;
}

function how() {
  const R = D.report, M = R.markets;
  const names = {total_shots: 'Total shots', total_sot: 'Total shots on target', home_sot: 'Home shots on target', away_sot: 'Away shots on target',
    home_cards: 'Home bookings', away_cards: 'Away bookings', total_cards: 'Total bookings', home_fouls: 'Home fouls', away_fouls: 'Away fouls'};
  const rows = Object.entries(names).map(([k, n]) => { const x = M[k];
    return `<tr><td>${n}</td><td class="num">${x.avg_miss_final}</td><td class="num">${x.avg_miss_league_average}</td><td class="num">${x['safer_over_promised_%']}% → <b>${x['safer_over_hit_%']}%</b></td></tr>`; }).join('');
  return `<section class="box"><h2>Honest test on ${R.matches_tested} real matches</h2>
  <div class="mut">Period: ${esc(R.test_period)}. Each match was predicted using only games played before it, and these results were kept out while the model was being set up.</div>
  <table style="margin-top:8px"><tr><th>Market</th><th class="num">Our avg miss</th><th class="num">League-avg miss</th><th class="num">Safer tips: promised → landed</th></tr>${rows}</table>
  <p><b>Match result:</b> our pick was right ${M.match_result['final_pick_right_%']}% of the time (bookmaker favourite: ${M.match_result['bookmaker_pick_right_%']}%).</p>
  <p><b>BTTS:</b> right ${M.btts['final_pick_right_%']}% (saying "Yes" every time: ${M.btts['always_yes_right_%']}%). When we said Yes at 60%+, it landed ${M.btts['strong_yes_hit_%']}%.</p>
  <p><b>What this means:</b> shots, shots on target and fouls are where the tool knows most. Bookings sit close to a coin-flip around the bookmaker line, so treat them with care. Goal kicks and free kicks are estimates, because no free source records them.</p>
  <p class="mut">No tool can guarantee wins. Bet only what you can afford to lose. 18+. If gambling stops being fun: BeGambleAware.org</p></section>`;
}

let shown = [];
document.addEventListener('click', e => { const b = e.target.closest('.more'); if (!b) return; const c = b.closest('.card'); c.classList.toggle('open'); b.textContent = c.classList.contains('open') ? 'Hide details ▴' : 'Full details and price checker ▾'; });
function render() {
  shown = upcoming.filter(m => (league === 'All' || m.league === league) && (!query || (m.home + ' ' + m.away).toLowerCase().includes(query)));
  const stale = hoursOld > 20 ? `<div class="banner">⚠ These predictions are ${Math.round(hoursOld)} hours old. Run “Update predictions” for fresh ones.</div>` : '';
  const app = $('app');
  $('search').style.display = view === 'how' || view === 'record' ? 'none' : '';
  if (view === 'how') app.innerHTML = how();
  else if (view === 'record') app.innerHTML = record();
  else if (!shown.length) app.innerHTML = stale + '<p class="mut">No upcoming matches here yet. New fixtures appear a few days before each round.</p>';
  else if (view === 'stand') app.innerHTML = stale + standouts(shown);
  else {
    let html = stale + '<div class="legend">Green = expected well above the league average (lean Over). Red = well below (lean Under). "72%+" = the safer line. Tap "Full details" for every line and the price checker.</div>', day = '';
    shown.forEach((m, i) => {
      if (m.iso !== day) { day = m.iso; const n = shown.filter(x => x.iso === day).length;
        html += `<div class="day">${new Date(day + 'T12:00:00').toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long'})}<span>${n} match${n > 1 ? 'es' : ''}</span></div>`; }
      html += matchCard(m, i);
    });
    app.innerHTML = html;
  }
  document.documentElement.style.setProperty('--hh', document.querySelector('header').offsetHeight + 'px');
}
render();
"""

if __name__ == "__main__":
    main()
