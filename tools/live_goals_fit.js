// Fits how the live goal model reacts to the game so far (shots on target for and
// against, share of shots, and whether a side is ahead or behind). Chosen by how well
// it predicts each side's goals still to come on half the past games (even ESPN ids),
// then checked on the other half (odd ids) against the old model.
// Run: node tools/live_goals_fit.js [--write]   (--write saves CFG.gm in live_params.json)
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const D = JSON.parse(fs.readFileSync(path.join(ROOT, 'cache', 'live_bt_data.json'), 'utf8'));
const SRC = fs.readFileSync(path.join(ROOT, 'live_model.js'), 'utf8');
const PARAMS = JSON.parse(fs.readFileSync(path.join(ROOT, 'live_params.json'), 'utf8'));
const model = gm => { const m = { exports: null }; new Function('module', SRC.replace('__LIVE_CFG__', JSON.stringify({ ...PARAMS, gm })))(m); return m.exports; };
const AT = ['20', '30', '45', '60', '75'];
const live = (g, at) => ({ state: 'in', status: at === '45' ? 'STATUS_HALFTIME' : Number(at) < 45 ? 'STATUS_FIRST_HALF' : 'STATUS_SECOND_HALF',
  period: Number(at) <= 45 ? 1 : 2, clock: Number(at), home: g.snap[at].home, away: g.snap[at].away });
const use = D.games.filter(g => g.ok.goals && g.ok.sot && g.pre.goals_exp);
const fit = use.filter(g => Number(g.id) % 2 === 0), test = use.filter(g => Number(g.id) % 2 === 1);
const lf = n => { let s = 0; for (let i = 2; i <= n; i++) s += Math.log(i); return s; };
// Poisson log loss of each side's goals still to come
function loss(gm, games) {
  const L = model(gm); let s = 0, n = 0;
  for (const g of games) for (const at of AT) {
    const lam = L._goalsProbs(g.pre, live(g, at)).lam;
    ['home', 'away'].forEach((h, i) => { const y = g.score[h] - g.snap[at][h].goals; if (y < 0) return;
      s += lam[i] - y * Math.log(Math.max(lam[i], 1e-9)) + lf(y); n++; });
  }
  return s / n;
}
let gm = { k: 1, sot: 0, opp: 0, share: 0, lead: 0, trail: 0 };
const grid = { k: [0.5, 1, 2, 4], sot: [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8], opp: [-0.3, -0.2, -0.1, 0, 0.1, 0.2],
  share: [-1, -0.5, 0, 0.5, 1, 1.5, 2], lead: [-0.4, -0.3, -0.2, -0.1, 0, 0.1, 0.2], trail: [-0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4] };
let cur = loss(gm, fit);
for (let pass = 0; pass < 4; pass++) for (const key of Object.keys(grid)) {
  for (const v of grid[key]) { const c = { ...gm, [key]: v }, s = loss(c, fit); if (s < cur - 1e-7) { cur = s; gm = c; } }
}
console.log('chosen on', fit.length, 'games:', gm, 'fit loss', cur.toFixed(5));
console.log(`checked on ${test.length} other games — goals-to-come log loss: old ${loss(null, test).toFixed(5)}, new ${loss(gm, test).toFixed(5)}`);
// how good are the BTTS and over/under-goals chances themselves (Brier score, lower is better)
function brier(gmx, games) {
  const L = model(gmx); let b = 0, o = 0, n = 0;
  for (const g of games) for (const at of AT) {
    const p = L._goalsProbs(g.pre, live(g, at)), yes = g.score.home > 0 && g.score.away > 0;
    b += (p.btts / 100 - (yes ? 1 : 0)) ** 2;
    const now = g.snap[at].home.goals + g.snap[at].away.goals, more = g.score.home + g.score.away > now;
    o += ((1 - Math.exp(-p.rest)) - (more ? 1 : 0)) ** 2; n++;
  }
  return { btts: (b / n).toFixed(4), another_goal: (o / n).toFixed(4) };
}
console.log('Brier (lower is better) old', brier(null, test), 'new', brier(gm, test));
if (process.argv.includes('--write')) {
  PARAMS.gm = gm; fs.writeFileSync(path.join(ROOT, 'live_params.json'), JSON.stringify(PARAMS, null, 1) + '\n'); console.log('wrote live_params.json');
}
