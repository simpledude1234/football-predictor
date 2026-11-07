// Backtest of the live picks: runs the real live_model.js on past games
// rebuilt at half-time (45') and 60', then checks each pick against the final
// stats. Settings are chosen on the fitting half of games (even ESPN ids) and
// scored on the other half (odd ids).
// Run: node tools/live_backtest.js   (after tools/live_backtest_data.py)
// Writes live_params.json (the settings the page uses) and prints the results.
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const D = JSON.parse(fs.readFileSync(path.join(ROOT, 'cache', 'live_bt_data.json'), 'utf8'));
const SRC = fs.readFileSync(path.join(ROOT, 'live_model.js'), 'utf8');

function model(cfg) {
  const m = { exports: null };
  new Function('module', SRC.replace('__LIVE_CFG__', JSON.stringify(cfg)))(m);
  return m.exports;
}

const live = (g, at) => {
  const s = g.snap[at];
  return at === '45' ? { state: 'in', status: 'STATUS_HALFTIME', period: 1, clock: 45, home: s.home, away: s.away }
    : { state: 'in', status: Number(at) < 45 ? 'STATUS_FIRST_HALF' : 'STATUS_SECOND_HALF', period: Number(at) < 45 ? 1 : 2, clock: Number(at), home: s.home, away: s.away };
};
const fin = (g, key) => {
  const b = g.final_box, c = h => (b[h].yellowCards || 0) + (b[h].redCards || 0);
  return { total_shots: b.home.totalShots + b.away.totalShots, total_sot: b.home.shotsOnTarget + b.away.shotsOnTarget,
    home_sot: b.home.shotsOnTarget, away_sot: b.away.shotsOnTarget, home_cards: c('home'), away_cards: c('away'),
    total_cards: c('home') + c('away'), home_fouls: b.home.foulsCommitted, away_fouls: b.away.foulsCommitted,
    home_corners: b.home.wonCorners, away_corners: b.away.wonCorners,
    total_corners: b.home.wonCorners == null || b.away.wonCorners == null ? null : b.home.wonCorners + b.away.wonCorners,
    total_goals: g.score.home + g.score.away }[key];
};
const resultOf = g => g.score.home > g.score.away ? 'H' : g.score.home < g.score.away ? 'A' : 'D';
const NAMES = { result: 'Result', btts: 'Both teams to score', total_shots: 'Total shots', total_sot: 'Total shots on target',
  home_sot: 'Home shots on target', away_sot: 'Away shots on target', home_cards: 'Home bookings', away_cards: 'Away bookings',
  total_cards: 'Total bookings', home_fouls: 'Home fouls', away_fouls: 'Away fouls', total_corners: 'Total corners',
  home_corners: 'Home corners', away_corners: 'Away corners', total_goals: 'Total goals' };
const STATOF = { total_shots: 'shots', total_sot: 'sot', home_sot: 'sot', away_sot: 'sot', home_cards: 'cards',
  away_cards: 'cards', total_cards: 'cards', home_fouls: 'fouls', away_fouls: 'fouls', total_corners: 'corners',
  home_corners: 'corners', away_corners: 'corners', total_goals: 'goals' };

const base = { curves: D.curves, k: { shots: 1, sot: 1, fouls: 1, cards: 1, goals: 1, corners: 1 }, red_own: 0.75, red_opp: 1.25,
  goal_pace: 0, min_pace: 0.05, from: 20, until: 76, goals_line: true,   // picks only in the tested window (20'-75')
  gm: (() => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, 'live_params.json'), 'utf8')).gm; } catch (e) { return undefined; } })() };   // live goal model (tools/live_goals_fit.js)

const AT = ['20', '30', '45', '60', '75'];
const fitG = D.games.filter(g => Number(g.id) % 2 === 0), testG = D.games.filter(g => Number(g.id) % 2 === 1);

// ---- choose how much to trust the pace so far (k), per stat, by log score on the fitting half
function logScore(cfg, stat, games) {
  const L = model(cfg); let s = 0, n = 0;
  for (const g of games) for (const at of ['45', '60']) {
    const Lv = live(g, at), t = L.minute(Lv);
    for (const x of g.pre.markets) {
      if (STATOF[x.key] !== stat || x.estimate || !g.ok[stat]) continue;
      const sides = x.key.startsWith('home') ? ['home'] : x.key.startsWith('away') ? ['away'] : ['home', 'away'];
      const now = sides.reduce((a, h) => a + (stat === 'cards' ? Lv[h].yellow + Lv[h].red : Lv[h][stat]), 0);
      if (fin(g, x.key) == null) continue;
      const y = fin(g, x.key) - now;
      if (!(y >= 0)) continue;
      const f = L.left(stat, t), k = cfg.k[stat], rate = (k * x.expected + now) / (k + 1 - f), mu = rate * f;
      const p = L.cdf(mu, y, x.phi) - L.cdf(mu, y - 1, x.phi);
      s += -Math.log(Math.max(p, 1e-9)); n++;
    }
  }
  return s / n;
}
const cfg = JSON.parse(JSON.stringify(base));
for (const stat of ['shots', 'sot', 'fouls', 'cards', 'corners']) {
  let best = null;
  for (const k of [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10, 1000]) {
    cfg.k[stat] = k; const s = logScore(cfg, stat, fitG);
    if (!best || s < best.s) best = { k, s };
  }
  cfg.k[stat] = best.k;
}
// goal pace (do shots on target so far change the goal rate?), by result log score
function resultLog(c, games) {
  const L = model(c); let s = 0, n = 0;
  for (const g of games) for (const at of ['45', '60']) {
    const p = L._goalsProbs(g.pre, live(g, at));
    const res = resultOf(g);
    s += -Math.log(Math.max(p[res] / 100, 1e-9)); n++;
  }
  return s / n;
}
let bestGP = null;
for (const gp of base.gm ? [0] : [0, 0.25, 0.5, 0.75, 1]) {
  cfg.goal_pace = gp; const s = resultLog(cfg, fitG);
  if (!bestGP || s < bestGP.s) bestGP = { gp, s };
}
cfg.goal_pace = bestGP.gp;

// ---- score the picks
function score(c, games) {
  const L = model(c), out = {};
  const add = (at, key, hit, chance) => {
    for (const k of [at + '|' + key, at + '|__all__', 'both|' + key, 'both|__all__']) {
      const o = out[k] = out[k] || { n: 0, hit: 0, claim: 0 }; o.n++; o.hit += hit ? 1 : 0; o.claim += chance;
    }
  };
  let shown = 0, slots = 0;
  for (const g of games) for (const at of AT) {
    const R = L.picks(g.pre, live(g, at));
    for (const p of R.list) {
      slots++;
      if (!p.pick) continue;
      shown++;
      let hit;
      if (p.key === 'result') hit = resultOf(g) === p.side;
      else if (p.key === 'btts') hit = (g.score.home > 0 && g.score.away > 0) === (p.side === 'yes');
      else { if (!g.ok[STATOF[p.key]]) continue; const a = fin(g, p.key); if (a == null) continue; hit = p.pick === 'over' ? a > p.line : a < p.line; }
      add(at, p.key, hit, p.chance);
    }
  }
  return { out, shown, slots };
}

const before = cfg;   // a per-market correction was tried (2026-11-07) and did not hold up on the test half

const res = score(cfg, testG);
const resBefore = score(before, testG);
const pct = o => o ? (100 * o.hit / o.n).toFixed(1) + '%' : '-';
const claim = o => o ? (o.claim / o.n).toFixed(1) + '%' : '-';
console.log(`Settings chosen on ${fitG.length} games; tested on ${testG.length} other games.`);
console.log('k (trust in pre-match vs pace):', cfg.k, 'goal_pace:', cfg.goal_pace);
console.log(`Picks shown: ${res.shown} of ${res.slots} chances (${(100 * res.shown / res.slots).toFixed(0)}%)`);
console.log('market'.padEnd(26), ...AT.map(a => (a + "': n, landed (claimed)").padEnd(26)));
for (const key of ['__all__', ...Object.keys(NAMES)]) {
  console.log((NAMES[key] || 'ALL PICKS').padEnd(26), ...AT.map(at => { const a = res.out[at + '|' + key]; return `${a ? a.n : 0}, ${pct(a)} (${claim(a)})`.padEnd(26); }));
}
// pace ignored (pre-match numbers scaled by time only), for comparison
const flat = JSON.parse(JSON.stringify(cfg)); for (const k in flat.k) flat.k[k] = 1e6; flat.goal_pace = 0; delete flat.gm;
const rf = score(flat, testG);
console.log(`\nFor comparison, ignoring how the game is going (pre-match numbers x time left): ${rf.out['both|__all__'].n} picks, ${pct(rf.out['both|__all__'])} landed (claimed ${claim(rf.out['both|__all__'])})`);
console.log(`Before the per-market correction: ${resBefore.out['both|__all__'].n} picks, ${pct(resBefore.out['both|__all__'])} landed (claimed ${claim(resBefore.out['both|__all__'])})`);
for (const k of Object.keys(NAMES)) { const a = resBefore.out['both|' + k], b = res.out['both|' + k]; console.log('  ' + NAMES[k].padEnd(24), 'before', `${a ? a.n : 0}, ${pct(a)} (${claim(a)})`.padEnd(24), 'after', `${b ? b.n : 0}, ${pct(b)} (${claim(b)})`); }
console.log(`Live model: ${res.out['both|__all__'].n} picks, ${pct(res.out['both|__all__'])} landed (claimed ${claim(res.out['both|__all__'])})`);

const all = res.out['both|__all__'];
const note = `Tested on ${testG.length} past games (checked at 20, 30, 45, 60 and 75 minutes): ${Math.round(100 * all.hit / all.n)} in 100 live picks landed.`;
const params = { ...cfg, tested: true, note, test: { games: testG.length, picks: all.n, landed: +(100 * all.hit / all.n).toFixed(1),
  claimed: +(all.claim / all.n).toFixed(1), per_market: Object.fromEntries(Object.keys(NAMES).map(k => [k, res.out['both|' + k] ? { n: res.out['both|' + k].n, landed: +(100 * res.out['both|' + k].hit / res.out['both|' + k].n).toFixed(1) } : null])) } };
if (process.argv.includes('--write')) {
  try { const old = JSON.parse(fs.readFileSync(path.join(ROOT, 'live_params.json'), 'utf8')); if (old.pl) params.pl = old.pl; } catch (e) {}   // keep the player settings (tools/live_players_bt.js)
  fs.writeFileSync(path.join(ROOT, 'live_params.json'), JSON.stringify(params, null, 1) + '\n');
  console.log('wrote live_params.json');
}
