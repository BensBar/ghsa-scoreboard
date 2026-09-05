from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .store import Store, utcnow

SMS_PATTERN = re.compile(
    r"^\s*([A-Z0-9-]{2,12})\s+(\d{1,3})\s+([A-Z0-9-]{2,12})\s+(\d{1,3})"
    r"(?:\s+(Q[1-4]|HALF|OT|FINAL|DELAYED|POSTPONED|CANCELED))?"
    r"(?:\s+(\d{1,2}:\d{2}))?\s*$",
    re.IGNORECASE,
)
RADIO_PATTERN = re.compile(
    r"\b([A-Za-z][A-Za-z .'-]{1,40}?)\s+(?:leads?|ahead(?:\s+of)?|over)\s+"
    r"([A-Za-z][A-Za-z .'-]{1,40}?)\s+(\d{1,3})\s*(?:to|-|–)\s*(\d{1,3})"
    r"(?:\s+(?:with\s+)?(\d{1,2}:\d{2})(?:\s+(?:left|remaining))?)?",
    re.IGNORECASE,
)


@dataclass
class Observation:
    game_id: str
    source_id: str
    home_score: int
    away_score: int
    status: str | None = None
    clock: str | None = None
    confidence: float = 0.35
    evidence_hash: str | None = None


def migrate(store: Store) -> None:
    store.db.executescript("""
    CREATE TABLE IF NOT EXISTS sources (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
      homepage_url TEXT, stream_url TEXT, permission_status TEXT NOT NULL,
      permission_note TEXT, enabled INTEGER NOT NULL DEFAULT 0,
      attribution TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reporters (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, team_ids TEXT NOT NULL,
      secret_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS observations (
      id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL,
      source_id TEXT NOT NULL, home_score INTEGER NOT NULL, away_score INTEGER NOT NULL,
      status TEXT, clock TEXT, confidence REAL NOT NULL, evidence_hash TEXT NOT NULL,
      received_at TEXT NOT NULL, published_at TEXT,
      UNIQUE(source_id,evidence_hash),
      FOREIGN KEY(game_id) REFERENCES games(id), FOREIGN KEY(source_id) REFERENCES sources(id)
    );
    """)
    store.db.commit()


def register_source(store: Store, source: dict[str, Any]) -> None:
    permission = source.get("permissionStatus", "unknown")
    if permission not in {"unknown", "requested", "granted", "denied"}:
        raise ValueError("invalid permission status")
    if source.get("kind") not in {"radio", "social", "ocr", "media", "reporter"}:
        raise ValueError("invalid source kind")
    enabled = bool(source.get("enabled"))
    if enabled and permission != "granted":
        raise ValueError("source cannot be enabled without granted permission")
    store.db.execute("""
    INSERT INTO sources(id,name,kind,homepage_url,stream_url,permission_status,
      permission_note,enabled,attribution,created_at)
    VALUES(?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,
      homepage_url=excluded.homepage_url,stream_url=excluded.stream_url,
      permission_status=excluded.permission_status,permission_note=excluded.permission_note,
      enabled=excluded.enabled,attribution=excluded.attribution
    """, (
        source["id"], source["name"], source["kind"], source.get("homepageUrl"),
        source.get("streamUrl"), permission, source.get("permissionNote"),
        int(enabled), source.get("attribution"), utcnow(),
    ))
    store.db.commit()


def register_reporter(
    store: Store, reporter_id: str, name: str, team_ids: list[str], secret: str
) -> None:
    if len(secret) < 16:
        raise ValueError("reporter secret must be at least 16 characters")
    if not team_ids:
        raise ValueError("reporter must be assigned at least one team")
    known = store.db.execute(
        f"SELECT id FROM teams WHERE id IN ({','.join('?' for _ in team_ids)})", team_ids
    ).fetchall()
    if len(known) != len(set(team_ids)):
        raise ValueError("reporter assignment contains an unknown team")
    salt = secrets.token_hex(16)
    secret_hash = f"{salt}${hashlib.scrypt(secret.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()}"
    store.db.execute("""
    INSERT INTO reporters(id,name,team_ids,secret_hash,created_at) VALUES(?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET name=excluded.name,team_ids=excluded.team_ids,
      secret_hash=excluded.secret_hash,enabled=1
    """, (reporter_id, name, json.dumps(team_ids), secret_hash, utcnow()))
    register_source(store, {
        "id": f"reporter:{reporter_id}", "name": name, "kind": "reporter",
        "permissionStatus": "granted", "enabled": True,
        "permissionNote": "Reporter explicitly enrolled", "attribution": "Verified school reporter",
    })
    store.db.commit()


def authenticate_reporter(store: Store, reporter_id: str, secret: str) -> dict[str, Any]:
    row = store.db.execute(
        "SELECT * FROM reporters WHERE id=? AND enabled=1", (reporter_id,)
    ).fetchone()
    if not row or "$" not in row["secret_hash"]:
        raise PermissionError("invalid reporter credentials")
    salt, expected = row["secret_hash"].split("$", 1)
    supplied = hashlib.scrypt(
        secret.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()
    if not hmac.compare_digest(expected, supplied):
        raise PermissionError("invalid reporter credentials")
    return {"id": row["id"], "name": row["name"], "teamIds": json.loads(row["team_ids"])}


def parse_sms(
    store: Store, text: str, reporter: dict[str, Any], now: datetime | None = None
) -> Observation:
    match = SMS_PATTERN.match(text)
    if not match:
        raise ValueError("use: AWAY 14 HOME 21 Q3 4:32")
    away_code, away_score, home_code, home_score, status, clock = match.groups()
    away_id = _resolve_team(store, away_code)
    home_id = _resolve_team(store, home_code)
    allowed = set(reporter["teamIds"])
    if not ({away_id, home_id} & allowed):
        raise PermissionError("reporter is not assigned to either team")
    candidates = store.db.execute("""
      SELECT id,kickoff,status FROM games WHERE away_team_id=? AND home_team_id=?
        AND status NOT IN ('FINAL','canceled','postponed')
    """, (away_id, home_id)).fetchall()
    now = now or datetime.now(timezone.utc)
    nearby = []
    for candidate in candidates:
        kickoff = datetime.fromisoformat(candidate["kickoff"].replace("Z", "+00:00"))
        distance = abs((now - kickoff).total_seconds())
        if distance <= 18 * 60 * 60:
            nearby.append((distance, candidate))
    nearby.sort(key=lambda item: item[0])
    if not nearby:
        raise ValueError("no current matching game")
    if len(nearby) > 1 and nearby[0][0] == nearby[1][0]:
        raise ValueError("matching game is ambiguous")
    game = nearby[0][1]
    normalized_status = status.upper() if status else None
    if normalized_status == "DELAYED":
        normalized_status = "delayed"
    elif normalized_status == "POSTPONED":
        normalized_status = "postponed"
    elif normalized_status == "CANCELED":
        normalized_status = "canceled"
    return Observation(
        game["id"], f"reporter:{reporter['id']}", int(home_score), int(away_score),
        normalized_status, clock, 0.98,
        hashlib.sha256(text.strip().upper().encode()).hexdigest(),
    )


def extract_radio_observations(
    store: Store, source_id: str, transcript: str, game_id: str
) -> list[Observation]:
    source = store.db.execute(
        "SELECT * FROM sources WHERE id=? AND kind='radio' AND enabled=1 "
        "AND permission_status='granted'", (source_id,)
    ).fetchone()
    if not source:
        raise PermissionError("radio source is not permission-approved")
    game = store.db.execute("""
      SELECT g.*, h.name home_name, h.aliases home_aliases,
        a.name away_name, a.aliases away_aliases
      FROM games g JOIN teams h ON h.id=g.home_team_id
      JOIN teams a ON a.id=g.away_team_id WHERE g.id=?
    """, (game_id,)).fetchone()
    if not game:
        raise ValueError("unknown game")
    observations = []
    for match in RADIO_PATTERN.finditer(transcript):
        leader, trailer, leader_score, trailer_score, clock = match.groups()
        leader_id = _match_game_team(game, leader)
        trailer_id = _match_game_team(game, trailer)
        if not leader_id or not trailer_id or leader_id == trailer_id:
            continue
        home_score, away_score = (
            (int(leader_score), int(trailer_score))
            if leader_id == game["home_team_id"]
            else (int(trailer_score), int(leader_score))
        )
        evidence = hashlib.sha256(
            f"{transcript.strip().lower()}:{match.start()}:{match.group(0).lower()}".encode()
        ).hexdigest()
        observations.append(Observation(
            game_id, source_id, home_score, away_score, clock=clock,
            confidence=0.35, evidence_hash=evidence,
        ))
    return observations


def submit_observation(store: Store, observation: Observation) -> dict[str, Any]:
    if min(observation.home_score, observation.away_score) < 0:
        raise ValueError("scores must be non-negative")
    evidence_hash = observation.evidence_hash or hashlib.sha256(
        f"{observation.game_id}:{observation.home_score}:{observation.away_score}:"
        f"{observation.status}:{observation.clock}".encode()
    ).hexdigest()
    now = utcnow()
    store.db.execute("SAVEPOINT submit_observation")
    try:
        cursor = store.db.execute("""
          INSERT OR IGNORE INTO observations(game_id,source_id,home_score,away_score,status,
            clock,confidence,evidence_hash,received_at)
          VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            observation.game_id, observation.source_id, observation.home_score,
            observation.away_score, observation.status, observation.clock,
            observation.confidence, evidence_hash, now,
        ))
        if cursor.rowcount == 0:
            store.db.execute("RELEASE submit_observation")
            store.db.commit()
            return {"accepted": False, "published": False, "reason": "duplicate evidence"}
        immediate = observation.source_id.startswith("reporter:") and observation.confidence >= 0.9
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        corroboration = store.db.execute("""
          SELECT COUNT(DISTINCT source_id) source_count, COUNT(*) observation_count
          FROM observations WHERE game_id=? AND home_score=? AND away_score=?
            AND received_at>=?
        """, (
            observation.game_id, observation.home_score, observation.away_score, cutoff,
        )).fetchone()
        corroborated = (
            corroboration["source_count"] >= 2 or corroboration["observation_count"] >= 2
        )
        published = immediate or corroborated
        if published:
            game = store.db.execute("SELECT * FROM games WHERE id=?", (observation.game_id,)).fetchone()
            update = {
                "id": game["id"], "kickoff": game["kickoff"],
                "homeTeamId": game["home_team_id"], "awayTeamId": game["away_team_id"],
                "homeScore": observation.home_score, "awayScore": observation.away_score,
                "status": observation.status or game["status"],
                "period": observation.status or game["period"], "clock": observation.clock or game["clock"],
                "source": observation.source_id if immediate else "corroborated-community",
                "confidence": observation.confidence if immediate else 0.75,
                "lastFeedCheck": now, "lastSuccessfulUpdate": now,
                "staleAfterSeconds": game["stale_after_seconds"], "featured": bool(game["featured"]),
            }
            store.upsert_game(update)
            store.db.execute(
                "UPDATE observations SET published_at=? WHERE game_id=? AND home_score=? "
                "AND away_score=? AND received_at>=?",
                (now, observation.game_id, observation.home_score, observation.away_score, cutoff),
            )
        store.db.execute("RELEASE submit_observation")
        store.db.commit()
    except Exception:
        store.db.execute("ROLLBACK TO submit_observation")
        store.db.execute("RELEASE submit_observation")
        raise
    return {
        "accepted": True, "published": published,
        "corroborationCount": corroboration["observation_count"],
        "sourceCount": corroboration["source_count"],
    }


def _resolve_team(store: Store, value: str) -> str:
    needle = value.strip().lower()
    rows = store.db.execute("SELECT id,name,aliases FROM teams").fetchall()
    matches = []
    for row in rows:
        names = {row["id"].lower(), row["name"].lower(), *[
            str(alias).lower() for alias in json.loads(row["aliases"])
        ]}
        abbreviations = {"".join(word[0] for word in name.split()) for name in names if name}
        if needle in names or needle in abbreviations:
            matches.append(row["id"])
    if len(matches) != 1:
        raise ValueError(f"team code is {'unknown' if not matches else 'ambiguous'}: {value}")
    return matches[0]


def _match_game_team(game: Any, spoken: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]", "", spoken.lower())
    for side in ("home", "away"):
        names = [game[f"{side}_name"], *json.loads(game[f"{side}_aliases"])]
        for name in names:
            candidate = re.sub(r"[^a-z0-9]", "", str(name).lower())
            if candidate and (candidate in normalized or normalized in candidate):
                return game[f"{side}_team_id"]
    return None
