from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.score_desk import (
    Observation, authenticate_reporter, extract_radio_observations, migrate,
    parse_sms, register_reporter, register_source, submit_observation,
)
from backend.store import Store


class ScoreDeskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.db")
        migrate(self.store)
        self.store.upsert_team({"id": "cat", "name": "Catholic", "source": "test"})
        self.store.upsert_team({
            "id": "car", "name": "Carrollton", "aliases": ["Trojans"], "source": "test",
        })
        self.store.upsert_game({
            "id": "game", "kickoff": "2026-09-05T00:00:00Z",
            "homeTeamId": "cat", "awayTeamId": "car", "status": "Q3",
            "homeScore": 7, "awayScore": 14, "source": "seed",
        })
        self.store.db.commit()

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_trusted_reporter_sms_publishes_immediately(self) -> None:
        register_reporter(self.store, "r1", "Reporter", ["car"], "long-random-secret")
        reporter = authenticate_reporter(self.store, "r1", "long-random-secret")
        observation = parse_sms(
            self.store, "CAR 21 CAT 7 Q3 4:32", reporter,
            datetime(2026, 9, 5, 1, tzinfo=timezone.utc),
        )
        result = submit_observation(self.store, observation)
        game = self.store.game("game")
        self.assertTrue(result["published"])
        self.assertEqual(21, game["awayScore"])
        self.assertEqual("4:32", game["clock"])

    def test_radio_requires_permission_and_corroboration(self) -> None:
        register_source(self.store, {
            "id": "radio", "name": "Station", "kind": "radio",
            "permissionStatus": "granted", "enabled": True,
        })
        first = extract_radio_observations(
            self.store, "radio", "Carrollton leads Catholic 21 to 7 with 4:32 remaining.", "game"
        )[0]
        self.assertFalse(submit_observation(self.store, first)["published"])
        second = Observation(
            "game", "radio", 7, 21, "Q3", "4:32", 0.35, "different-clip",
        )
        self.assertTrue(submit_observation(self.store, second)["published"])

    def test_unapproved_radio_is_rejected(self) -> None:
        register_source(self.store, {
            "id": "radio", "name": "Station", "kind": "radio",
            "permissionStatus": "requested", "enabled": False,
        })
        with self.assertRaises(PermissionError):
            extract_radio_observations(self.store, "radio", "Carrollton leads Catholic 21-7", "game")

    def test_source_cannot_be_enabled_without_permission(self) -> None:
        with self.assertRaisesRegex(ValueError, "granted permission"):
            register_source(self.store, {
                "id": "unlicensed", "name": "Unlicensed", "kind": "media",
                "permissionStatus": "unknown", "enabled": True,
            })

    def test_duplicate_evidence_is_not_counted_as_corroboration(self) -> None:
        register_source(self.store, {
            "id": "social", "name": "School feed", "kind": "social",
            "permissionStatus": "granted", "enabled": True,
        })
        observation = Observation("game", "social", 7, 21, evidence_hash="post-1")
        self.assertFalse(submit_observation(self.store, observation)["published"])
        duplicate = submit_observation(self.store, observation)
        self.assertFalse(duplicate["accepted"])
        self.assertEqual(14, self.store.game("game")["awayScore"])

    def test_reporter_requires_team_assignment(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one team"):
            register_reporter(self.store, "r1", "Reporter", [], "long-random-secret")

    def test_sms_ignores_future_rematch(self) -> None:
        self.store.upsert_game({
            "id": "future", "kickoff": "2026-09-12T00:00:00Z",
            "homeTeamId": "cat", "awayTeamId": "car", "status": "scheduled",
            "source": "seed",
        })
        register_reporter(self.store, "r1", "Reporter", ["car"], "long-random-secret")
        reporter = authenticate_reporter(self.store, "r1", "long-random-secret")
        observation = parse_sms(
            self.store, "CAR 21 CAT 7 Q3 4:32", reporter,
            datetime(2026, 9, 5, 1, tzinfo=timezone.utc),
        )
        self.assertEqual("game", observation.game_id)


if __name__ == "__main__":
    unittest.main()
