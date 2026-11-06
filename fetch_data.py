"""Download free match stats and upcoming fixtures from football-data.co.uk."""
import datetime as dt
import pathlib
import requests

LEAGUES = {
    "E0": "Premier League",
    "E1": "Championship",
    "I1": "Serie A",
    "I2": "Serie B",
    "SP1": "La Liga",
    "F1": "Ligue 1",
    "D1": "Bundesliga",
    "SC0": "Scottish Premiership",
}

DATA = pathlib.Path(__file__).parent / "data"


def season_codes(n=3):
    """Current season plus the previous n-1, e.g. ['2627', '2526', '2425']."""
    today = dt.date.today()
    start = today.year if today.month >= 7 else today.year - 1
    return [f"{(start - i) % 100:02d}{(start - i + 1) % 100:02d}" for i in range(n)]


MAX_BYTES = 5_000_000          # real files are well under 1 MB
ALLOWED_HOST = "https://football-data.co.uk/"


def get(url, path):
    """Download a CSV safely: HTTPS to one known site only, size-capped, checked
    before it replaces the old copy. Nothing downloaded is ever run as code."""
    if not url.startswith(ALLOWED_HOST):
        raise ValueError("blocked: unexpected download address")
    with requests.get(url, timeout=60, stream=True, allow_redirects=False,
                      headers={"User-Agent": "FootballPredictor/1.0"}) as r:
        r.raise_for_status()
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) > MAX_BYTES:
                raise ValueError("blocked: file far bigger than expected")
    head = data[:400].decode("utf-8-sig", errors="replace")
    low = data.lower()
    if not head.startswith("Div,Date,") or "HomeTeam" not in head \
            or any(t in low for t in (b"<script", b"<html", b"<?php", b"javascript:")):
        raise ValueError("blocked: file is not the expected football CSV")
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return len(data)


def main():
    DATA.mkdir(exist_ok=True)
    for s in season_codes():
        for code in LEAGUES:
            p = DATA / f"{code}_{s}.csv"
            try:
                print(f"{code} {s}: {get(f'https://football-data.co.uk/mmz4281/{s}/{code}.csv', p)} bytes")
            except Exception as e:
                print(f"{code} {s}: failed ({e})")
    try:
        print("fixtures:", get(ALLOWED_HOST + "fixtures.csv", DATA / "fixtures.csv"), "bytes")
    except Exception as e:
        print(f"fixtures: failed ({e}); using the last good copy")


if __name__ == "__main__":
    main()
