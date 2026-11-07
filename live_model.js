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
  const BAR = CFG.bar || 72;
  // each market's chance corrected by how that market's picks did on past games (tools/live_backtest.js)
  const cal = (key, ch) => {
    const a = CFG.cal && CFG.cal[key]; if (!a) return ch;
    const p = Math.min(0.999, Math.max(0.001, ch / 100)), z = Math.log(p / (1 - p)) + a;
    return 100 / (1 + Math.exp(-z));
  };

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
    total_corners: ['corners', ['home', 'away']], home_corners: ['corners', ['home']], away_corners: ['corners', ['away']],
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

  // the line to suggest: over L wins if the final count > L; under L wins if final < L
  function pickLine(n, mean, phi, side, key) {
    let best = null;
    for (let line = n + 0.5; line < n + 60; line += 1) {
      const need = line - n + 0.5;                       // more events needed for over
      const pOver = 1 - cdf(mean, need - 1, phi);
      const ch = cal(key, 100 * (side === 'over' ? pOver : 1 - pOver));
      if (ch >= BAR) {
        if (side === 'over') best = { line, chance: ch };              // keep raising the line while it stays >= 72%
        else if (!best) best = { line, chance: ch };                   // first (lowest) under line that clears 72%
      }
    }
    return best;
  }

  function overUnder(key, pre, phi, L, t) {
    const [stat, sides] = STAT[key];
    if (!CFG.curves[stat]) return null;                  // a stat not tested yet
    const n = count(L, stat, sides);
    if (n == null || pre == null) return null;
    const r = rest(pre, n, stat, t);
    const mean = r.mean * redAdj(L, sides, stat);
    const proj = n + mean;
    // which way is the game running compared with what we expected before kick-off?
    const pace = proj / pre - 1;
    if (Math.abs(pace) < CFG.min_pace) return { key, n, proj, pick: null, why: 'normal' };
    const side = pace > 0 ? 'over' : 'under';
    const best = pickLine(n, mean, phi, side, key);
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
      // goals still to come, adjusted by how the game is going (fitted on past games, tools/live_goals_fit.js):
      // a side outshooting what was expected scores more; a side behind pushes, a side ahead sits back
      const G = CFG.gm;
      if (G && sot && L[s].sot != null) {
        const o = s === 'home' ? 'away' : 'home', osot = m.markets.find(x => x.key === o + '_sot');
        const ratio = (n, e) => Math.max(0.25, Math.min(4, (G.k * e + n) / (G.k * e + e * (1 - f))));
        const d = (L[s].goals || 0) - (L[o].goals || 0);
        let x = G.sot * Math.log(ratio(L[s].sot, sot.expected));
        if (osot && L[o].sot != null) x += G.opp * Math.log(ratio(L[o].sot, osot.expected));
        if (L[s].shots != null && L[o].shots != null && L[s].shots + L[o].shots > 0)
          x += G.share * ((L[s].shots + 1) / (L[s].shots + L[o].shots + 2) - sot.expected / (sot.expected + (osot ? osot.expected : sot.expected)));
        x += d > 0 ? G.lead : d < 0 ? G.trail : 0;
        l *= Math.exp(x);
      }
      return l;
    });
    const gh = L.home.goals || 0, ga = L.away.goals || 0;
    const ph = pois(lam[0], 12), pa = pois(lam[1], 12);
    let H = 0, D = 0, A = 0;
    ph.forEach((x, i) => pa.forEach((y, j) => { const a = gh + i, b = ga + j, p = x * y; if (a > b) H += p; else if (a < b) A += p; else D += p; }));
    const tot = H + D + A; H /= tot; D /= tot; A /= tot;
    const yes = (gh > 0 ? 1 : 1 - ph[0]) * (ga > 0 ? 1 : 1 - pa[0]);
    return { H: 100 * H, D: 100 * D, A: 100 * A, btts: 100 * yes, settledBtts: gh > 0 && ga > 0, rest: lam[0] + lam[1], lam };
  }

  // total goals: goals so far + goals still to come (same goal rates as the result)
  function totalGoals(m, L, g) {
    const n = (L.home.goals || 0) + (L.away.goals || 0), pre = m.goals_exp[0] + m.goals_exp[1];
    const pace = (n + g.rest) / pre - 1;
    if (Math.abs(pace) < CFG.min_pace) return { key: 'total_goals', n, pick: null, why: 'normal' };
    const side = pace > 0 ? 'over' : 'under', best = pickLine(n, g.rest, 1, side, 'total_goals');
    if (!best) return { key: 'total_goals', n, pick: null, why: 'none' };
    return { key: 'total_goals', n, pick: side, line: best.line, chance: Math.round(best.chance) };
  }

  // names written the same way whatever the accents (Guimarães = Guimaraes)
  const norm = s => String(s || '').normalize('NFD').replace(/[^A-Za-z]/g, '').toLowerCase();

  // Players to be booked from here on. Each player's booking record (m.squad: his
  // bookings per match from past games, compared with his team-mates') is scaled by how
  // many bookings his team should get in this match (that already includes the referee),
  // then his fouls so far in this game add to it (more for fouls made in less time),
  // and the result is scaled by the share of the game still to come. Players already
  // booked, sent off or no longer on the pitch are left out. Settings in CFG.pl were
  // fitted on past games (tools/live_players_bt.js).
  function bookings(m, L, t) {
    const P = CFG.pl;
    if (!P || !m.squad || !L.players) return [];
    const out = [], f = left('cards', t), played = Math.max(1 - f, 0.15);
    const fhN = { home: {}, away: {} };                                  // foul habits by accent-free name
    if (m.fh) for (const s of ['home', 'away']) for (const k in (m.fh[s] || {})) if (k) fhN[s][norm(k)] = m.fh[s][k];
    for (const side of ['home', 'away']) {
      const sq = m.squad[side], ps = L.players[side];
      const cm = m.markets.find(x => x.key === side + '_cards');
      if (!sq || !ps || !cm || !(cm.expected > 0)) continue;
      const rates = {}, known = [];
      for (const k in sq) if (k) { rates[norm(k)] = sq[k]; known.push(sq[k]); }
      if (!known.length) continue;
      const avg = known.reduce((a, b) => a + b, 0) / known.length;
      const n = (L[side].yellow || 0) + (L[side].red || 0);
      const pace = Math.max(0.3, Math.min(3, rest(cm.expected, n, 'cards', t).rate / cm.expected));
      for (const [name, on, y, r, fouls] of ps) {
        if (!on || y || r) continue;
        const own = rates[norm(name)];
        let rel = own == null ? P.u : Math.pow(own / avg, P.g);          // no record: a new face
        const fh = m.fh && m.fh[side];                                    // how often he fouls per game
        if (P.fh && fh && fh[''] > 0) { const x = fh[norm(name)] ?? fhN[side][norm(name)]; if (x != null) rel *= Math.pow(x / fh[''], P.fh); }
        const lam = (P.s * rel * Math.pow(cm.expected / 2, P.h) + P.b * (fouls || 0) / played) * f * Math.pow(pace, P.a);
        out.push({ player: name, side, fouls: fouls || 0, chance: 100 * (1 - Math.exp(-lam)) });
      }
    }
    return out.sort((a, b) => b.chance - a.chance);
  }

  function picks(m, L) {
    const t = minute(L);
    if (t == null) return { t, state: L.state, list: [] };
    if (t < CFG.from || t > CFG.until) return { t, state: L.state, list: [], late: t > CFG.until };
    const list = [];
    const g = goals(m, L, t);
    const best = ['H', 'D', 'A'].reduce((a, b) => g[b] > g[a] ? b : a, 'H'), rc = cal('result', g[best]);
    list.push({ key: 'result', chance: Math.round(rc), side: best, pick: rc >= BAR ? best : null });
    if (!g.settledBtts) {
      const s = g.btts >= 50 ? 'yes' : 'no', ch = cal('btts', s === 'yes' ? g.btts : 100 - g.btts);
      list.push({ key: 'btts', chance: Math.round(ch), side: s, pick: ch >= BAR ? s : null });
    } else list.push({ key: 'btts', pick: null, why: 'landed' });
    for (const x of m.markets) {
      if (x.estimate || !STAT[x.key]) continue;
      const r = overUnder(x.key, x.expected, x.phi, L, t);
      if (r) list.push(r);
    }
    if (CFG.goals_line && m.goals_exp) list.push(totalGoals(m, L, g));
    const booked = bookings(m, L, t);
    // the top few are the ones most likely flattered by chance, so their figure is scaled by CFG.pl.c (tested)
    const players = booked.slice(0, 3).map(p => ({ ...p, chance: Math.round(p.chance * ((CFG.pl && CFG.pl.c) || 1)) }));
    return { t, state: L.state, list, players };
  }

  // how many so far, for checking whether an earlier pick has already landed
  const soFar = (key, L) => key === 'total_goals' ? (L.home.goals || 0) + (L.away.goals || 0)
    : STAT[key] ? count(L, STAT[key][0], STAT[key][1]) : null;

  return { picks, minute, left, cdf, CFG, norm, soFar, _goalsProbs: (m, L) => goals(m, L, minute(L)),
    _bookings: (m, L) => bookings(m, L, minute(L)) };
})();
if (typeof module !== 'undefined') module.exports = LIVE;
