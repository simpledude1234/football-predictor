// Starts the site build on GitHub at fixed times (GitHub's own timer never fired for this project).
// It has no web address of its own: it only runs on the timers in wrangler.toml.
// Needs one secret, GITHUB_TOKEN: a fine-grained GitHub token for this repository only,
// with "Actions: Read and write" and nothing else.
const URL = "https://api.github.com/repos/simpledude1234/football-predictor/actions/workflows/update.yml/dispatches";

export default {
  async scheduled(event, env, ctx) {
    // the line-up timers pass their timer, so the build only runs when a kick-off is near
    const lineup = event.cron.startsWith("10,40");
    const r = await fetch(URL, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ftips-scheduler",
      },
      body: JSON.stringify({ ref: "main", inputs: { slot: lineup ? "lineup" : "" } }),
    });
    if (r.status !== 204) throw new Error(`GitHub said ${r.status}: ${(await r.text()).slice(0, 200)}`);
  },
};
