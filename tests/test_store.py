from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.db")
        self.store.upsert_team({"id": "away", "name": "Away", "source": "test"})
        self.store.upsert_team({"id": "home", "name": "Home", "source": "test"})
        self.game = {
            "id": "game-1", "kickoff": "2026-09-05T00:00:00Z",
            "homeTeamId": "home", "awayTeamId": "away", "homeScore": 7,
            "awayScore": 3, "status": "Q1", "source": "test", "confidence": 0.9,
            "lastFeedCheck": "2026-09-05T00:01:00Z",
            "lastSuccessfulUpdate": "2026-09-05T00:01:00Z",
            "scoringEvents": [{"sequence": 1, "description": "Home touchdown"}],
        }
        self.store.upsert_game(self.game)
        self.store.db.commit()

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_preserves_home_away_orientation(self) -> None:
        game = self.store.game("game-1")
        self.assertEqual("home", game["homeTeam"]["id"])
        self.assertEqual(7, game["homeScore"])
        self.assertEqual("away", game["awayTeam"]["id"])
        self.assertEqual(3, game["awayScore"])

    def test_rejects_backward_status_transition(self) -> None:
        update = {**self.game, "status": "scheduled"}
        with self.assertRaisesRegex(ValueError, "invalid status transition"):
            self.store.upsert_game(update)

    def test_deduplicates_scoring_events(self) -> None:
        self.store.upsert_game(self.game)
        count = self.store.db.execute(
            "SELECT count(*) FROM scoring_events WHERE game_id='game-1'"
        ).fetchone()[0]
        self.assertEqual(1, count)

    def test_correction_is_audited_and_rollback_restores_value(self) -> None:
        ids = self.store.correct("game-1", {"homeScore": 14}, "official correction", "tester")
        self.assertEqual(14, self.store.game("game-1")["homeScore"])
        self.store.rollback(ids[0], "tester")
        self.assertEqual(7, self.store.game("game-1")["homeScore"])

    def test_rejects_invalid_scores(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            self.store.upsert_game({**self.game, "homeScore": -1})

    def test_invalid_correction_is_atomic(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be corrected"):
            self.store.correct(
                "game-1", {"homeScore": 35, "unsupported": "value"}, "test", "tester"
            )
        self.store.health("test", True, None, 1)
        self.assertEqual(7, self.store.game("game-1")["homeScore"])


if __name__ == "__main__":
    unittest.main()
