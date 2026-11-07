// Runs the page's own live model (live_model.js) on game states sent as JSON on
// stdin, for live_record.py. Prints the picks as JSON. Nothing is fetched.
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const cfg = fs.readFileSync(path.join(ROOT, 'live_params.json'), 'utf8');
const SRC = fs.readFileSync(path.join(ROOT, 'live_model.js'), 'utf8').replace('__LIVE_CFG__', cfg);
const mod = { exports: null };
new Function('module', SRC)(mod);
const LIVE = mod.exports;
const jobs = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = jobs.map(j => ({ id: j.id, at: j.at, list: LIVE.picks(j.m, j.L).list.filter(p => p.pick) }));
process.stdout.write(JSON.stringify(out));
