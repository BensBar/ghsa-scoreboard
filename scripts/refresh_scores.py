#!/usr/bin/env python3
"""
Best-effort score refresh for GHSA Scoreboard.

MaxPreps / GHSA HTML is JS-heavy and anti-bot fragile. This script:
  1. Loads data/schools.json + public/scores.json
  2. Tries lightweight fetches of MaxPreps schedule pages
  3. On success, merges parsed scores into scores.json
  4. Always stamps updatedAt; exits 0 even if scrape is empty
     (so the Action can still run / document the pipeline)

Manual override: edit public/scores.json directly.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORES_PATH = ROOT / "public" / "scores.json"
SCHOOLS_PATH = ROOT / "data" / "schools.json"

UA = (
    "Mozilla/5.0 (compatible; GHSA-Scoreboard/1.0; +https://github.com/BensBar/ghsa-scoreboard)"
)


def fetch(url: str, timeout: int = 20) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"fetch failed: {url} -> {exc}", file=sys.stderr)
        return None


def try_parse_maxpreps(html: str) -> dict | None:
    """Very loose heuristics — MaxPreps markup changes often."""
    # Look for common final/live patterns in embedded JSON-ish blobs
    m = re.search(
        r'"homeScore"\s*:\s*(\d+|null).{0,80}?"awayScore"\s*:\s*(\d+|null)',
        html,
        re.I | re.S,
    )
    if m:
        hs, aws = m.group(1), m.group(2)
        return {
            "homeScore": None if hs == "null" else int(hs),
            "awayScore": None if aws == "null" else int(aws),
        }
    # Fallback: "Final 28-14" style
    m2 = re.search(r"(?:Final|FINAL)\s+(\d+)\s*[-–]\s*(\d+)", html)
    if m2:
        return {"homeScore": int(m2.group(1)), "awayScore": int(m2.group(2))}
    return None


def main() -> int:
    schools = json.loads(SCHOOLS_PATH.read_text())
    scores = json.loads(SCORES_PATH.read_text())
    by_id = {s["id"]: s for s in schools.get("schools", schools.get("pinned", []))}

    changed = False
    for game in scores.get("pinned", []):
        school = by_id.get(game["id"])
        if not school:
            continue
        url = school.get("maxpreps", {}).get("schedule") or school.get("maxpreps", {}).get("team")
        if not url:
            continue
        html = fetch(url)
        if not html:
            continue
        parsed = try_parse_maxpreps(html)
        if not parsed:
            print(f"no parseable score for {game['id']}")
            continue
        for key in ("homeScore", "awayScore"):
            if parsed.get(key) is not None and game.get(key) != parsed[key]:
                game[key] = parsed[key]
                changed = True
        # If we got numeric scores and status still scheduled, bump to FINAL as a guess
        if (
            game.get("homeScore") is not None
            and game.get("awayScore") is not None
            and game.get("status") == "scheduled"
        ):
            game["status"] = "FINAL"
            changed = True
        print(f"checked {game['id']}: {parsed}")

    scores["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    SCORES_PATH.write_text(json.dumps(scores, indent=2) + "\n")
    print("wrote", SCORES_PATH, "changed=" + str(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
