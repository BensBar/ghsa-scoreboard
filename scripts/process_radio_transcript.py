#!/usr/bin/env python3
"""Extract score facts from an approved station's local Whisper transcript.

The transcript is read from stdin and is never written to disk or the database.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.score_desk import extract_radio_observations, migrate, submit_observation
from backend.store import Store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--game", required=True)
    args = parser.parse_args()
    transcript = sys.stdin.read()
    store = Store(os.getenv("SCOREBOARD_DB", ROOT / "data" / "scoreboard.db"))
    migrate(store)
    observations = extract_radio_observations(store, args.source, transcript, args.game)
    results = [submit_observation(store, observation) for observation in observations]
    store.close()
    print(json.dumps({"extracted": len(observations), "results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
