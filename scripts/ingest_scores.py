#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ingest import configured_feeds, ingest
from backend.store import Store


def main() -> int:
    store = Store(os.getenv("SCOREBOARD_DB", ROOT / "data" / "scoreboard.db"))
    store.seed(ROOT / "data" / "schools.json", ROOT / "public" / "scores.json")
    result = ingest(store, configured_feeds())
    print(json.dumps(result))
    store.close()
    return 0 if result.get("provider") else 1


if __name__ == "__main__":
    raise SystemExit(main())
