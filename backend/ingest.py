from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .store import Store, utcnow


@dataclass
class Feed:
    name: str
    url: str
    token: str | None = None

    def fetch(self, timeout: int = 15) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "GHSA-Scoreboard/2.0"}
        if self.token:
            headers["Authorization"] = "Bearer" + " " + self.token
        request = urllib.request.Request(self.url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)


def configured_feeds() -> list[Feed]:
    feeds = []
    for index, url in enumerate(filter(None, os.getenv("SCORE_FEED_URLS", "").split(","))):
        feeds.append(Feed(
            os.getenv(f"SCORE_FEED_{index}_NAME", f"provider-{index + 1}"),
            url.strip(),
            os.getenv(f"SCORE_FEED_{index}_TOKEN"),
        ))
    return feeds


def ingest(store: Store, feeds: list[Feed], retries: int = 2) -> dict[str, Any]:
    if not feeds:
        return {"provider": None, "changed": 0, "error": "No SCORE_FEED_URLS configured"}
    errors = []
    for feed in feeds:
        for attempt in range(retries + 1):
            started = time.monotonic()
            try:
                payload = feed.fetch()
                changed = 0
                for team in payload.get("teams", []):
                    team["source"] = feed.name
                    store.upsert_team(team)
                seen = set()
                rejected = []
                for game in payload.get("games", []):
                    game_id = game.get("id")
                    if not game_id or game_id in seen:
                        continue
                    seen.add(game_id)
                    game["source"] = feed.name
                    game["lastFeedCheck"] = utcnow()
                    try:
                        changed += int(store.upsert_game(game))
                    except (ValueError, KeyError) as exc:
                        rejected.append({"gameId": game_id, "error": str(exc)})
                store.db.commit()
                latency = int((time.monotonic() - started) * 1000)
                store.health(feed.name, True, None, latency)
                return {
                    "provider": feed.name, "changed": changed, "games": len(seen),
                    "rejected": rejected,
                }
            except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as exc:
                store.db.rollback()
                latency = int((time.monotonic() - started) * 1000)
                message = f"{type(exc).__name__}: {exc}"
                store.health(feed.name, False, message, latency)
                errors.append(f"{feed.name}: {message}")
                if attempt < retries:
                    time.sleep(2 ** attempt)
    return {"provider": None, "changed": 0, "error": "; ".join(errors)}
