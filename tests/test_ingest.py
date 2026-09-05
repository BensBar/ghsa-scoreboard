from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.ingest import ingest
from backend.store import Store


class FakeFeed:
    def __init__(self, name, payload=None, error=None):
        self.name, self.payload, self.error = name, payload, error

    def fetch(self):
        if self.error:
            raise self.error
        return self.payload


class IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_fails_over_and_imports_provider_catalog(self) -> None:
        payload = {
            "teams": [{"id": "a", "name": "Away"}, {"id": "h", "name": "Home"}],
            "games": [{
                "id": "g", "kickoff": "2026-09-05T00:00:00Z",
                "homeTeamId": "h", "awayTeamId": "a", "status": "scheduled",
            }],
        }
        result = ingest(self.store, [
            FakeFeed("down", error=OSError("offline")),
            FakeFeed("licensed", payload=payload),
        ], retries=0)
        self.assertEqual("licensed", result["provider"])
        self.assertEqual("licensed", self.store.game("g")["source"])

    def test_rejected_game_does_not_drop_later_games(self) -> None:
        teams = [{"id": value, "name": value.upper()} for value in ("a", "h", "x", "y")]
        self.store.upsert_team(teams[0])
        self.store.upsert_team(teams[1])
        self.store.upsert_game({
            "id": "finished", "kickoff": "2026-09-05T00:00:00Z",
            "homeTeamId": "h", "awayTeamId": "a", "status": "FINAL", "source": "test",
        })
        self.store.db.commit()
        payload = {"teams": teams, "games": [
            {
                "id": "finished", "kickoff": "2026-09-05T00:00:00Z",
                "homeTeamId": "h", "awayTeamId": "a", "status": "Q4",
            },
            {
                "id": "next", "kickoff": "2026-09-05T01:00:00Z",
                "homeTeamId": "y", "awayTeamId": "x", "status": "scheduled",
            },
        ]}
        result = ingest(self.store, [FakeFeed("licensed", payload=payload)], retries=0)
        self.assertEqual(1, len(result["rejected"]))
        self.assertIsNotNone(self.store.game("next"))


if __name__ == "__main__":
    unittest.main()
