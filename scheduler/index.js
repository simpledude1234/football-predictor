// Starts the site build on GitHub at fixed times (GitHub's own timer never fired for this project).
// It has no web address of its own: it only runs on the timers in wrangler.toml.
// Needs one secret, GITHUB_TOKEN: a fine-grained GitHub token for this repository only,
// with "Actions: Read and write" and nothing else.
const URL = "https://api.github.com/repos/simpledude1234/football-predictor/actions/workflows/update.yml/dispatches";

export default {
  async scheduled(event, env, ctx) {
    // the line-up timers pass their timer, so the build only runs when a kick-off is near
    const lineup = event.cron.startsWith("10,40");
    // tidy the token: copying it often picks up spaces, line breaks or invisible characters
    const token = String(env.GITHUB_TOKEN || "").replace(/[^A-Za-z0-9_]/g, "");
    const r = await fetch(URL, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ftips-scheduler",
      },
      body: JSON.stringify({ ref: "main", inputs: { slot: lineup ? "lineup" : "" } }),
    });
    if (r.status !== 204) {
      // describe the token without showing it, to help find what is wrong
      const raw = String(env.GITHUB_TOKEN || "");
      throw new Error(`GitHub said ${r.status} ${r.statusText}: ${(await r.text()).slice(0, 300)} | token: ${raw.length} chars, ` +
        `${token.length} after tidying, starts "${token.slice(0, 11).replace(/[A-Za-z0-9]/g, (c, i) => i < 4 ? c : "*")}"`);
    }
  },
};
