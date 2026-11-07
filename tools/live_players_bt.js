// Backtest of the live "player to be booked" picks. Runs the page's own
// live_model.js on past games rebuilt at 20, 30, 45, 60 and 75 minutes
// (tools/live_players_data.py). Settings are chosen on half the games (even
// ESPN ids) and checked on the other half (odd ids).
// Run: node tools/live_players_bt.js [--write]   (--write saves them to live_params.json)
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const D = JSON.parse(fs.readFileSync(path.join(ROOT, 'cache', 'live_pl_data.json'), 'utf8'));
const SRC = fs.readFileSync(path.join(ROOT, 'live_model.js'), 'utf8');
const PARAMS = JSON.parse(fs.readFileSync(path.join(ROOT, 'live_params.json'), 'utf8'));

function model(pl) {
  const m = { exports: null };
  new Function('module', SRC.replace('__LIVE_CFG__', JSON.stringify({ ...PARAMS, pl })))(m);
  return m.exports;
}
const AT = ['20', '30', '45', '60', '75'];
const state = (s, at) => ({
  state: 'in', status: at === '45' ? 'STATUS_HALFTIME' : Number(at) < 45 ? 'STATUS_FIRST_HALF' : 'STATUS_SECOND_HALF',
  period: Number(at) <= 45 ? 1 : 2, clock: Number(at),
  home: { ...s.cards.home, goals: 0 }, away: { ...s.cards.away, goals: 0 }, players: s.players });

// every candidate (on the pitch, not yet booked) with the model's chance and whether he was booked later
function rows(pl, games) {
  const L = model(pl), out = [];
  for (const g of games) for (const at of AT) {
    const s = g.snap[at], later = new Set(s.later.map(L.norm));
    const list = L._bookings(g.pre, state(s, at));
    list.forEach((p, i) => out.push({ p: p.chance / 100, hit: later.has(L.norm(p.player)), top: i < 3, at, fouls: p.fouls }));
  }
  return out;
}
const logLoss = rs => rs.reduce((a, r) => a - Math.log(Math.max(1e-9, r.hit ? r.p : 1 - r.p)), 0) / rs.length;

const fit = D.games.filter(g => Number(g.id) % 2 === 0), test = D.games.filter(g => Number(g.id) % 2 === 1);
let best = null;
// s: overall level, g: how much a player's own record counts, h: expected team bookings,
// b: fouls so far, u: a player with no record, a: the game's booking pace so far
for (const s of [0.12, 0.14, 0.16, 0.18]) for (const g of [0.75, 1, 1.25]) for (const h of [0, 0.5, 1])
  for (const b of [0, 0.001, 0.002, 0.004, 0.006]) for (const u of [0.6, 0.8, 1]) for (const a of [0, 1]) {
    const ll = logLoss(rows({ s, g, h, b, u, a }, fit));
    if (!best || ll < best.ll) best = { s, g, h, b, u, a, ll };
  }
const pl = { s: best.s, g: best.g, h: best.h, b: best.b, u: best.u, a: best.a };
{ // correction for the top 3 shown, from the fitting half only
  const t = rows(pl, fit).filter(r => r.top);
  pl.c = +(t.filter(r => r.hit).length / t.reduce((x, r) => x + r.p, 0)).toFixed(3);
}
console.log('fit log score', best.ll.toFixed(5), 'same without fouls', logLoss(rows({ ...pl, b: 0 }, fit)).toFixed(5));
const T = rows(pl, test), base = rows({ ...pl, a: 0, b: 0 }, test);
const top = T.filter(r => r.top).map(r => ({ ...r, p: r.p * pl.c })), sum = rs => ({ n: rs.length, landed: 100 * rs.filter(r => r.hit).length / rs.length, said: 100 * rs.reduce((a, r) => a + r.p, 0) / rs.length });
console.log(`Settings chosen on ${fit.length} games:`, pl);
console.log(`Checked on ${test.length} other games. Log score (lower is better): live model ${logLoss(T).toFixed(4)}, ` +
  `ignoring fouls and pace ${logLoss(base).toFixed(4)}`);
const t3 = sum(top);
console.log(`For comparison, any player on the pitch: ${sum(T).landed.toFixed(1)}% were booked later`);
console.log(`Top 3 players per game shown: ${t3.n} picks, said ${t3.said.toFixed(1)}%, landed ${t3.landed.toFixed(1)}%`);
for (const at of AT) { const x = sum(top.filter(r => r.at === at)); console.log(`  at ${at}': ${x.n} picks, said ${x.said.toFixed(1)}%, landed ${x.landed.toFixed(1)}%`); }
console.log('All players on the pitch, by the chance given:');
for (const [lo, hi] of [[0, 5], [5, 10], [10, 15], [15, 20], [20, 30], [30, 40], [40, 100]]) {
  const x = T.filter(r => r.p * 100 >= lo && r.p * 100 < hi); if (!x.length) continue;
  const y = sum(x); console.log(`  ${lo}-${hi}%: ${y.n} players, said ${y.said.toFixed(1)}%, landed ${y.landed.toFixed(1)}%`);
}
console.log('By fouls so far (all players):');
for (const f of [0, 1, 2, 3]) { const x = T.filter(r => (f === 3 ? r.fouls >= 3 : r.fouls === f)); if (x.length) { const y = sum(x); console.log(`  ${f}${f === 3 ? '+' : ''} fouls: ${y.n}, said ${y.said.toFixed(1)}%, landed ${y.landed.toFixed(1)}%`); } }
if (process.argv.includes('--write')) {
  PARAMS.pl = { ...pl, tested: { games: test.length, picks: t3.n, said: +t3.said.toFixed(1), landed: +t3.landed.toFixed(1) } };
  fs.writeFileSync(path.join(ROOT, 'live_params.json'), JSON.stringify(PARAMS, null, 1) + '\n');
  console.log('wrote live_params.json');
}
