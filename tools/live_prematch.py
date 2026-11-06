"""Backtest helper: pre-match predictions for past games (only earlier data used),
linked to ESPN ids. Saves cache/live_bt_prematch.json (local only)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import espn  # noqa: E402
import make_page  # noqa: E402
import predictor  # noqa: E402

OUT = espn.CACHE.parent / "live_bt_prematch.json"


def main(days=100):
    params = predictor.load_or_fit_params(refit=False)
    past = predictor.replay(params, days=days)
    cache = espn.load_cache()
    code_of = {v: k for k, v in espn.SLUGS.items()}
    make_page.link_espn(past, [{"code": code_of.get(e["slug"]), "day": e["date"], "id": e["id"], "home": e["home"],
                                "away": e["away"]} for e in cache["matches"].values()])
    keep = [{"espn_id": m["espn_id"], "iso": m["iso"], "code": m["code"], "home": m["home"], "away": m["away"],
             "goals_exp": m["goals_exp"], "final": m["final"], "btts": m["btts"],
             "markets": [{k: x[k] for k in ("key", "expected", "phi", "estimate")} for x in m["markets"]]}
            for m in past if m.get("espn_id")]
    OUT.write_text(json.dumps(keep, default=lambda o: o.item() if hasattr(o, "item") else float(o)), encoding="utf-8")
    print(f"saved {len(keep)} of {len(past)}")


if __name__ == "__main__":
    main()
