// Live (in-play) picks. Shared by the tips page and the backtest
// (tools/live_backtest.js), so what was tested is exactly what is shown.
//
// Idea: before kick-off the model expects, say, 26 shots. At minute t a known
// share of a match's shots is still to come (curves fitted from past games),
// and the game so far tells us whether it is running hotter or colder than
// expected. Expected final = what has happened + what is still to come.
// Then the same spread as the pre-match tips gives the chance of each line.
// A pick is shown only if it has at least a 72% chance and the line is not
// already decided.

const LIVE = (() => {
  const CFG = __LIVE_CFG__;   // curves and settings, fitted by tools/live_backtest.js
  const BAR = 72;

  // share of the full-match count still to come after minute t (0..90)
  function left(stat, t) {
    const c = CFG.curves[stat], i = Math.max(0, Math.min(90, t)), lo = Math.floor(i), hi = Math.min(90, lo + 1);
    return c[lo] + (c[hi] - c[lo]) * (i - lo);
  }

  // P(count <= k) for negative binomial / Poisson / binomial with mean and spread phi
  function cdf(mean, k, phi) {
    if (k < 0) return 0;
    if (mean <= 1e-9) return 1;
    let p, s = 0;
    if (phi == null || Math.abs(phi - 1) < 0.03) { p = Math.exp(-mean); for (let i = 0; i <= k; i++) { s += p; p *= mean / (i + 1); } }
    else if (phi > 1) { const r = mean / (phi - 1), q = mean / (r + mean); p = Math.pow(r / (r + mean), r); for (let i = 0; i <= k; i++) { s += p; p *= (i + r) / (i + 1) * q; } }
    else { const n = Math.max(Math.round(mean / (1 - phi)), k + 1), x = mean / n; p = Math.pow(1 - x, n); for (let i = 0; i <= k && i <= n; i++) { s += p; p *= (n - i) / (i + 1) * x / (1 - x); } }
    return Math.min(1, s);
  }

  function pois(l, n) { const out = []; let p = Math.exp(-l); for (let i = 0; i <= n; i++) { out.push(p); p *= l / (i + 1); } return out; }

  // the minute of play from ESPN's status
  function minute(L) {
    if (L.state !== 'in') return null;
    if (/HALFTIME/.test(L.status || '')) return 45;
    const c = L.clock == null ? 0 : L.clock;
    return L.period === 1 ? Math.min(c, 45) : Math.max(45, Math.min(c, 90));
  }

  // counts so far for each market
  const STAT = {
    total_shots: ['shots', ['home', 'away']], total_sot: ['sot', ['home', 'away']],
    home_sot: ['sot', ['home']], away_sot: ['sot', ['away']],
    home_cards: ['cards', ['home']], away_cards: ['cards', ['away']], total_cards: ['cards', ['home', 'away']],
    home_fouls: ['fouls', ['home']], away_fouls: ['fouls', ['away']],
  };
  const count = (L, stat, sides) => sides.reduce((a, s) => {
    const x = L[s]; const v = stat === 'cards' ? (x.yellow || 0) + (x.red || 0) : x[stat];
    return v == null || a == null ? null : a + v;
  }, 0);

  // red-card effect on the rest of the game (fewer shots/goals for the side down to 10)
  function redAdj(L, sides, stat) {
    if (sides.length !== 1 || (stat !== 'shots' && stat !== 'sot' && stat !== 'goals')) return 1;
    const me = sides[0], op = me === 'home' ? 'away' : 'home', d = (L[me].red || 0) - (L[op].red || 0);
    return d > 0 ? CFG.red_own : d < 0 ? CFG.red_opp : 1;
  }

  // expected rest-of-game count: pre-match rate updated by the pace so far
  function rest(pre, n, stat, t) {
    const f = left(stat, t), e = 1 - f, k = CFG.k[stat];
    const rate = (k * pre + n) / (k + e);
    return { mean: rate * f, rate };
  }

  function overUnder(key, pre, phi, L, t) {
    const [stat, sides] = STAT[key];
    const n = count(L, stat, sides);
    if (n == null || pre == null) return null;
    const r = rest(pre, n, stat, t);
    const mean = r.mean * redAdj(L, sides, stat);
    const proj = n + mean;
    // which way is the game running compared with what we expected before kick-off?
    const pace = proj / pre - 1;
    if (Math.abs(pace) < CFG.min_pace) return { key, n, proj, pick: null, why: 'normal' };
    const side = pace > 0 ? 'over' : 'under';
    let best = null;
    // over L wins if the final count > L; under L wins if final < L
    for (let line = n + 0.5; line < n + 60; line += 1) {
      const need = line - n + 0.5;                       // more events needed for over
      const pOver = 1 - cdf(mean, need - 1, phi);
      const ch = 100 * (side === 'over' ? pOver : 1 - pOver);
      if (ch >= BAR) {
        if (side === 'over') best = { line, chance: ch };              // keep raising the line while it stays >= 72%
        else if (!best) best = { line, chance: ch };                   // first (lowest) under line that clears 72%
      }
    }
    if (!best) return { key, n, proj, pick: null, why: 'none' };
    return { key, n, proj, pick: side, line: best.line, chance: Math.round(best.chance) };
  }

  // result and both teams to score from goals still to come
  function goals(m, L, t) {
    const f = left('goals', t);
    const lam = ['home', 'away'].map((s, i) => {
      let l = m.goals_exp[i] * f * redAdj(L, [s], 'goals');
      const sot = m.markets.find(x => x.key === s + '_sot');
      if (CFG.goal_pace && sot && L[s].sot != null) {
        const r = rest(sot.expected, L[s].sot, 'sot', t);
        l *= Math.pow(Math.max(0.3, Math.min(3, r.rate / sot.expected)), CFG.goal_pace);
      }
      return l;
    });
    const gh = L.home.goals || 0, ga = L.away.goals || 0;
    const ph = pois(lam[0], 12), pa = pois(lam[1], 12);
    let H = 0, D = 0, A = 0;
    ph.forEach((x, i) => pa.forEach((y, j) => { const a = gh + i, b = ga + j, p = x * y; if (a > b) H += p; else if (a < b) A += p; else D += p; }));
    const tot = H + D + A; H /= tot; D /= tot; A /= tot;
    const yes = (gh > 0 ? 1 : 1 - ph[0]) * (ga > 0 ? 1 : 1 - pa[0]);
    return { H: 100 * H, D: 100 * D, A: 100 * A, btts: 100 * yes, settledBtts: gh > 0 && ga > 0 };
  }

  // all live picks for one match. m = pre-match match data, L = live data from /api/live
  function picks(m, L) {
    const t = minute(L);
    if (t == null) return { t, state: L.state, list: [] };
    if (t < CFG.from || t > CFG.until) return { t, state: L.state, list: [], late: t > CFG.until };
    const list = [];
    const g = goals(m, L, t);
    const best = ['H', 'D', 'A'].reduce((a, b) => g[b] > g[a] ? b : a, 'H');
    list.push({ key: 'result', chance: Math.round(g[best]), side: best, pick: g[best] >= BAR ? best : null });
    if (!g.settledBtts) {
      const s = g.btts >= 50 ? 'yes' : 'no', ch = s === 'yes' ? g.btts : 100 - g.btts;
      list.push({ key: 'btts', chance: Math.round(ch), side: s, pick: ch >= BAR ? s : null });
    } else list.push({ key: 'btts', pick: null, why: 'landed' });
    for (const x of m.markets) {
      if (x.estimate || !STAT[x.key]) continue;
      const r = overUnder(x.key, x.expected, x.phi, L, t);
      if (r) list.push(r);
    }
    return { t, state: L.state, list };
  }

  return { picks, minute, left, cdf, CFG, _goalsProbs: (m, L) => goals(m, L, minute(L)) };
})();
if (typeof module !== 'undefined') module.exports = LIVE;
