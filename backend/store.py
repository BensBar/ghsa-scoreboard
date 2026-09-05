from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUSES = {
    "scheduled", "Q1", "Q2", "HALF", "Q3", "Q4", "OT",
    "FINAL", "delayed", "postponed", "canceled",
}
LIVE_STATUSES = {"Q1", "Q2", "HALF", "Q3", "Q4", "OT", "delayed"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        self.db.close()

    def _migrate(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]',
          city TEXT, classification TEXT, region TEXT, ranking INTEGER, record TEXT,
          color TEXT, logo TEXT, venue TEXT, latitude REAL, longitude REAL,
          broadcast_url TEXT, source TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS games (
          id TEXT PRIMARY KEY, kickoff TEXT NOT NULL, home_team_id TEXT NOT NULL,
          away_team_id TEXT NOT NULL, home_score INTEGER, away_score INTEGER,
          status TEXT NOT NULL, period TEXT, clock TEXT, possession_team_id TEXT,
          home_timeouts INTEGER, away_timeouts INTEGER, venue TEXT,
          source TEXT NOT NULL, source_game_id TEXT, confidence REAL NOT NULL,
          last_feed_check TEXT, last_successful_update TEXT, last_score_change TEXT,
          stale_after_seconds INTEGER NOT NULL DEFAULT 120, featured INTEGER NOT NULL DEFAULT 0,
          UNIQUE(source, source_game_id),
          FOREIGN KEY(home_team_id) REFERENCES teams(id),
          FOREIGN KEY(away_team_id) REFERENCES teams(id)
        );
        CREATE TABLE IF NOT EXISTS scoring_events (
          id TEXT PRIMARY KEY, game_id TEXT NOT NULL, sequence INTEGER NOT NULL,
          period TEXT, clock TEXT, team_id TEXT, description TEXT NOT NULL,
          home_score INTEGER, away_score INTEGER, occurred_at TEXT,
          UNIQUE(game_id, sequence), FOREIGN KEY(game_id) REFERENCES games(id)
        );
        CREATE TABLE IF NOT EXISTS corrections (
          id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, field TEXT NOT NULL,
          old_value TEXT, new_value TEXT, reason TEXT NOT NULL, corrected_by TEXT NOT NULL,
          corrected_at TEXT NOT NULL, rolled_back_at TEXT,
          FOREIGN KEY(game_id) REFERENCES games(id)
        );
        CREATE TABLE IF NOT EXISTS provider_health (
          provider TEXT PRIMARY KEY, last_attempt TEXT, last_success TEXT,
          last_error TEXT, latency_ms INTEGER
        );
        """)
        self.db.commit()

    def seed(self, schools_path: Path, scores_path: Path) -> None:
        if self.db.execute("SELECT 1 FROM teams LIMIT 1").fetchone():
            return
        catalog = json.loads(schools_path.read_text())
        now = utcnow()
        for team in [*catalog.get("schools", []), *catalog.get("opponents", [])]:
            self.upsert_team({
                "id": team["id"], "name": team["name"], "aliases": team.get("aliases", []),
                "city": team.get("city"), "classification": team.get("ghsaClass"),
                "region": team.get("region"), "ranking": team.get("ranking"),
                "record": team.get("record"), "color": team.get("primaryColor"),
                "logo": team.get("logo"), "venue": team.get("venue"),
                "latitude": team.get("latitude"), "longitude": team.get("longitude"),
                "broadcastUrl": team.get("broadcastUrl"), "source": "catalog",
                "updatedAt": now,
            })
        legacy = json.loads(scores_path.read_text())
        for item in [*legacy.get("pinned", []), *legacy.get("topGames", [])]:
            school_id = item.get("schoolId") or item["id"]
            if not self.db.execute("SELECT 1 FROM teams WHERE id=?", (school_id,)).fetchone():
                self.upsert_team({"id": school_id, "name": item["name"], "source": "legacy"})
            opponent_id = item.get("opponentId") or self._slug(item["opponent"])
            if not self.db.execute("SELECT 1 FROM teams WHERE id=?", (opponent_id,)).fetchone():
                self.upsert_team({"id": opponent_id, "name": item["opponent"], "source": "legacy"})
            home_id, away_id = (
                (school_id, opponent_id) if item.get("isHome") else (opponent_id, school_id)
            )
            game_id = item["id"] if item.get("schoolId") else f"{school_id}-{item['kickoff'][:10]}"
            duplicate = self.db.execute(
                "SELECT id FROM games WHERE kickoff=? AND home_team_id=? AND away_team_id=?",
                (item["kickoff"], home_id, away_id),
            ).fetchone()
            if duplicate:
                game_id = duplicate["id"]
            self.upsert_game({
                "id": game_id, "kickoff": item["kickoff"], "homeTeamId": home_id,
                "awayTeamId": away_id, "homeScore": item.get("homeScore"),
                "awayScore": item.get("awayScore"), "status": item.get("status", "scheduled"),
                "source": "seed", "sourceGameId": item["id"], "confidence": 0.5,
                "lastFeedCheck": legacy.get("updatedAt"), "lastSuccessfulUpdate": None,
                "featured": item in legacy.get("topGames", []),
            })
        self.db.commit()

    @staticmethod
    def _slug(value: str) -> str:
        return "-".join("".join(c.lower() if c.isalnum() else " " for c in value).split())

    def upsert_team(self, team: dict[str, Any]) -> None:
        self.db.execute("""
        INSERT INTO teams (id,name,aliases,city,classification,region,ranking,record,color,logo,
          venue,latitude,longitude,broadcast_url,source,updated_at)
        VALUES (:id,:name,:aliases,:city,:classification,:region,:ranking,:record,:color,:logo,
          :venue,:latitude,:longitude,:broadcast_url,:source,:updated_at)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name, aliases=excluded.aliases,
          city=COALESCE(excluded.city,teams.city),
          classification=COALESCE(excluded.classification,teams.classification),
          region=COALESCE(excluded.region,teams.region), ranking=excluded.ranking,
          record=COALESCE(excluded.record,teams.record), color=COALESCE(excluded.color,teams.color),
          logo=COALESCE(excluded.logo,teams.logo), venue=COALESCE(excluded.venue,teams.venue),
          latitude=COALESCE(excluded.latitude,teams.latitude),
          longitude=COALESCE(excluded.longitude,teams.longitude),
          broadcast_url=COALESCE(excluded.broadcast_url,teams.broadcast_url),
          source=excluded.source, updated_at=excluded.updated_at
        """, {
            "id": team["id"], "name": team["name"],
            "aliases": json.dumps(team.get("aliases", [])), "city": team.get("city"),
            "classification": team.get("classification"), "region": team.get("region"),
            "ranking": team.get("ranking"), "record": team.get("record"),
            "color": team.get("color"), "logo": team.get("logo"), "venue": team.get("venue"),
            "latitude": team.get("latitude"), "longitude": team.get("longitude"),
            "broadcast_url": team.get("broadcastUrl"), "source": team.get("source", "provider"),
            "updated_at": team.get("updatedAt", utcnow()),
        })

    def upsert_game(self, game: dict[str, Any]) -> bool:
        self._validate_game(game)
        old = self.db.execute(
            "SELECT home_score,away_score,status,period,clock FROM games WHERE id=?", (game["id"],)
        ).fetchone()
        if old and not self._valid_transition(old["status"], game["status"]):
            raise ValueError(f"invalid status transition: {old['status']} to {game['status']}")
        changed = old is None or any(old[k] != game.get({
            "home_score": "homeScore", "away_score": "awayScore", "status": "status",
            "period": "period", "clock": "clock",
        }[k]) for k in old.keys())
        score_changed = old is None or old["home_score"] != game.get("homeScore") or old["away_score"] != game.get("awayScore")
        now = game.get("lastFeedCheck", utcnow())
        successful = game.get("lastSuccessfulUpdate") or (now if changed else None)
        last_score = game.get("lastScoreChange") or (now if score_changed else None)
        self.db.execute("""
        INSERT INTO games (id,kickoff,home_team_id,away_team_id,home_score,away_score,status,
          period,clock,possession_team_id,home_timeouts,away_timeouts,venue,source,source_game_id,
          confidence,last_feed_check,last_successful_update,last_score_change,stale_after_seconds,featured)
        VALUES (:id,:kickoff,:home,:away,:hs,:aws,:status,:period,:clock,:possession,:hto,:ato,
          :venue,:source,:source_id,:confidence,:check_at,:success_at,:score_at,:stale_after,:featured)
        ON CONFLICT(id) DO UPDATE SET kickoff=excluded.kickoff, home_team_id=excluded.home_team_id,
          away_team_id=excluded.away_team_id, home_score=excluded.home_score,
          away_score=excluded.away_score, status=excluded.status, period=excluded.period,
          clock=excluded.clock, possession_team_id=excluded.possession_team_id,
          home_timeouts=excluded.home_timeouts, away_timeouts=excluded.away_timeouts,
          venue=COALESCE(excluded.venue,games.venue), source=excluded.source,
          source_game_id=excluded.source_game_id, confidence=excluded.confidence,
          last_feed_check=excluded.last_feed_check,
          last_successful_update=COALESCE(excluded.last_successful_update,games.last_successful_update),
          last_score_change=COALESCE(excluded.last_score_change,games.last_score_change),
          stale_after_seconds=excluded.stale_after_seconds, featured=excluded.featured
        """, {
            "id": game["id"], "kickoff": game["kickoff"], "home": game["homeTeamId"],
            "away": game["awayTeamId"], "hs": game.get("homeScore"),
            "aws": game.get("awayScore"), "status": game["status"],
            "period": game.get("period"), "clock": game.get("clock"),
            "possession": game.get("possessionTeamId"), "hto": game.get("homeTimeouts"),
            "ato": game.get("awayTimeouts"), "venue": game.get("venue"),
            "source": game.get("source", "unknown"), "source_id": game.get("sourceGameId", game["id"]),
            "confidence": float(game.get("confidence", 0.8)), "check_at": now,
            "success_at": successful, "score_at": last_score,
            "stale_after": int(game.get("staleAfterSeconds", 120)),
            "featured": int(bool(game.get("featured"))),
        })
        for event in game.get("scoringEvents", []):
            event_id = event.get("id") or hashlib.sha256(
                f"{game['id']}:{event.get('sequence')}:{event.get('description')}".encode()
            ).hexdigest()[:24]
            self.db.execute("""
            INSERT OR IGNORE INTO scoring_events
              (id,game_id,sequence,period,clock,team_id,description,home_score,away_score,occurred_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (event_id, game["id"], event["sequence"], event.get("period"),
                  event.get("clock"), event.get("teamId"), event["description"],
                  event.get("homeScore"), event.get("awayScore"), event.get("occurredAt")))
        return changed

    def _validate_game(self, game: dict[str, Any]) -> None:
        required = ("id", "kickoff", "homeTeamId", "awayTeamId", "status")
        if any(not game.get(key) for key in required):
            raise ValueError(f"game missing required field: {game.get('id', '<unknown>')}")
        if game["homeTeamId"] == game["awayTeamId"]:
            raise ValueError("home and away teams must differ")
        if game["status"] not in VALID_STATUSES:
            raise ValueError(f"invalid status: {game['status']}")
        for key in ("homeScore", "awayScore", "homeTimeouts", "awayTimeouts"):
            value = game.get(key)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{key} must be a non-negative integer")
        confidence = float(game.get("confidence", 0.8))
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    @staticmethod
    def _valid_transition(previous: str, current: str) -> bool:
        if previous == current or current in {"delayed", "postponed", "canceled"}:
            return True
        if previous in {"FINAL", "canceled"}:
            return False
        if previous in {"delayed", "postponed"}:
            return current in VALID_STATUSES - {"scheduled"}
        order = {"scheduled": 0, "Q1": 1, "Q2": 2, "HALF": 3, "Q3": 4, "Q4": 5, "OT": 6, "FINAL": 7}
        return previous not in order or current not in order or order[current] >= order[previous]

    def scoreboard(self, filters: dict[str, str] | None = None) -> dict[str, Any]:
        filters = filters or {}
        clauses, args = [], []
        if filters.get("date"):
            clauses.append("substr(g.kickoff,1,10)=?")
            args.append(filters["date"])
        if filters.get("status"):
            statuses = [x for x in filters["status"].split(",") if x in VALID_STATUSES]
            if statuses:
                clauses.append(f"g.status IN ({','.join('?' for _ in statuses)})")
                args.extend(statuses)
        if filters.get("classification"):
            clauses.append("(h.classification=? OR a.classification=?)")
            args.extend([filters["classification"]] * 2)
        if filters.get("region"):
            clauses.append("(h.region=? OR a.region=?)")
            args.extend([filters["region"]] * 2)
        if filters.get("q"):
            clauses.append("(h.name LIKE ? OR a.name LIKE ? OR h.aliases LIKE ? OR a.aliases LIKE ?)")
            term = f"%{filters['q']}%"
            args.extend([term] * 4)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(f"""
        SELECT g.*, h.name home_name,h.record home_record,h.ranking home_ranking,
          h.classification home_classification,h.region home_region,h.color home_color,h.logo home_logo,
          a.name away_name,a.record away_record,a.ranking away_ranking,
          a.classification away_classification,a.region away_region,a.color away_color,a.logo away_logo
        FROM games g JOIN teams h ON h.id=g.home_team_id JOIN teams a ON a.id=g.away_team_id
        {where} ORDER BY CASE WHEN g.status IN ('Q1','Q2','HALF','Q3','Q4','OT','delayed') THEN 0
          WHEN g.status='scheduled' THEN 1 ELSE 2 END, g.kickoff, g.featured DESC
        """, args).fetchall()
        games = [self._game_dict(row) for row in rows]
        health = [dict(row) for row in self.db.execute("SELECT * FROM provider_health")]
        last_success = max((g["lastSuccessfulUpdate"] or "" for g in games), default="") or None
        return {"generatedAt": utcnow(), "lastSuccessfulUpdate": last_success,
                "games": games, "providerHealth": health}

    def game(self, game_id: str) -> dict[str, Any] | None:
        board = self.scoreboard()
        game = next((g for g in board["games"] if g["id"] == game_id), None)
        if game:
            game["scoringEvents"] = [dict(row) for row in self.db.execute(
                "SELECT * FROM scoring_events WHERE game_id=? ORDER BY sequence", (game_id,)
            )]
        return game

    @staticmethod
    def _game_dict(row: sqlite3.Row) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        success = row["last_successful_update"]
        age = None
        if success:
            age = max(0, int((now - datetime.fromisoformat(success.replace("Z", "+00:00"))).total_seconds()))
        stale = row["status"] in LIVE_STATUSES and (
            age is None or age > row["stale_after_seconds"]
        )
        team = lambda side: {
            "id": row[f"{side}_team_id"], "name": row[f"{side}_name"],
            "record": row[f"{side}_record"], "ranking": row[f"{side}_ranking"],
            "classification": row[f"{side}_classification"], "region": row[f"{side}_region"],
            "color": row[f"{side}_color"], "logo": row[f"{side}_logo"],
        }
        return {
            "id": row["id"], "kickoff": row["kickoff"], "homeTeam": team("home"),
            "awayTeam": team("away"), "homeScore": row["home_score"],
            "awayScore": row["away_score"], "status": row["status"], "period": row["period"],
            "clock": row["clock"], "possessionTeamId": row["possession_team_id"],
            "homeTimeouts": row["home_timeouts"], "awayTimeouts": row["away_timeouts"],
            "venue": row["venue"], "source": row["source"], "confidence": row["confidence"],
            "lastFeedCheck": row["last_feed_check"],
            "lastSuccessfulUpdate": row["last_successful_update"],
            "lastScoreChange": row["last_score_change"], "stale": stale,
            "feedAgeSeconds": age, "featured": bool(row["featured"]),
        }

    def correct(self, game_id: str, updates: dict[str, Any], reason: str, actor: str) -> list[int]:
        allowed = {
            "homeScore": "home_score", "awayScore": "away_score", "status": "status",
            "period": "period", "clock": "clock", "possessionTeamId": "possession_team_id",
            "homeTimeouts": "home_timeouts", "awayTimeouts": "away_timeouts",
        }
        row = self.db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if not row:
            raise KeyError(game_id)
        candidate = {
            "id": game_id, "kickoff": row["kickoff"], "homeTeamId": row["home_team_id"],
            "awayTeamId": row["away_team_id"], "status": updates.get("status", row["status"]),
            "homeScore": updates.get("homeScore", row["home_score"]),
            "awayScore": updates.get("awayScore", row["away_score"]),
            "confidence": 1,
        }
        self._validate_game(candidate)
        ids, now = [], utcnow()
        for public, value in updates.items():
            column = allowed.get(public)
            if not column:
                raise ValueError(f"field cannot be corrected: {public}")
            old = row[column]
            if old == value:
                continue
            cur = self.db.execute("""
            INSERT INTO corrections (game_id,field,old_value,new_value,reason,corrected_by,corrected_at)
            VALUES (?,?,?,?,?,?,?)
            """, (game_id, column, json.dumps(old), json.dumps(value), reason, actor, now))
            self.db.execute(f"UPDATE games SET {column}=?, source='manual', confidence=1, "
                            "last_successful_update=? WHERE id=?", (value, now, game_id))
            ids.append(cur.lastrowid)
        self.db.commit()
        return ids

    def rollback(self, correction_id: int, actor: str) -> None:
        row = self.db.execute(
            "SELECT * FROM corrections WHERE id=? AND rolled_back_at IS NULL", (correction_id,)
        ).fetchone()
        if not row:
            raise KeyError(correction_id)
        old = json.loads(row["old_value"])
        now = utcnow()
        self.db.execute(f"UPDATE games SET {row['field']}=?, source='manual', "
                        "last_successful_update=? WHERE id=?", (old, now, row["game_id"]))
        self.db.execute("UPDATE corrections SET rolled_back_at=? WHERE id=?", (now, correction_id))
        self.db.commit()

    def health(self, provider: str, success: bool, error: str | None, latency_ms: int) -> None:
        now = utcnow()
        self.db.execute("""
        INSERT INTO provider_health(provider,last_attempt,last_success,last_error,latency_ms)
        VALUES (?,?,?,?,?)
        ON CONFLICT(provider) DO UPDATE SET last_attempt=excluded.last_attempt,
          last_success=CASE WHEN ? THEN excluded.last_success ELSE provider_health.last_success END,
          last_error=excluded.last_error, latency_ms=excluded.latency_ms
        """, (provider, now, now if success else None, error, latency_ms, success))
        self.db.commit()
