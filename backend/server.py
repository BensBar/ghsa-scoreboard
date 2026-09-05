from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .ingest import configured_feeds, ingest
from .score_desk import (
    Observation, authenticate_reporter, extract_radio_observations, migrate,
    parse_sms, register_reporter, register_source, submit_observation,
)
from .store import LIVE_STATUSES, Store, default_db_path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("SCOREBOARD_DB", default_db_path()))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
STATIC_ROOT = ROOT
STORE = Store(DB_PATH)
STORE.seed(ROOT / "data" / "schools.json", ROOT / "public" / "scores.json")
migrate(STORE)
for configured_source in json.loads((ROOT / "data" / "sources.json").read_text())["sources"]:
    if not STORE.db.execute(
        "SELECT 1 FROM sources WHERE id=?", (configured_source["id"],)
    ).fetchone():
        register_source(STORE, configured_source)
VERSION = threading.Condition()
DB_LOCK = threading.RLock()
CHANGE_VERSION = 0
CACHE: dict[str, tuple[float, bytes, str]] = {}
STATIC_FILES = {
    "index.html", "manifest.webmanifest", "service-worker.js", "DATA_POLICY.md",
    "data/schools.json", "public/scores.json", "admin/index.html", "admin/admin.js",
    "report/index.html", "report/report.js",
}


def notify_change() -> None:
    global CHANGE_VERSION
    with VERSION:
        CHANGE_VERSION += 1
        CACHE.clear()
        VERSION.notify_all()


def run_ingestion_loop() -> None:
    while True:
        with DB_LOCK:
            result = ingest(STORE, configured_feeds())
        if result.get("changed"):
            notify_change()
        with DB_LOCK:
            active = STORE.db.execute(
                f"SELECT 1 FROM games WHERE status IN ({','.join('?' for _ in LIVE_STATUSES)}) LIMIT 1",
                tuple(LIVE_STATUSES),
            ).fetchone()
        time.sleep(30 if active else 300)


class Handler(BaseHTTPRequestHandler):
    server_version = "GHSA-Scoreboard/2.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _json(self, status: int, payload: object, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64_000:
                raise ValueError("invalid request size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            return body
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc

    def _authorized(self) -> bool:
        configured = os.getenv("SCOREBOARD_ADMIN_TOKEN")
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return bool(configured and supplied and hmac.compare_digest(configured, supplied))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/scoreboard":
            self._scoreboard(parse_qs(parsed.query))
        elif parsed.path.startswith("/api/v1/games/"):
            game_id = unquote(parsed.path.removeprefix("/api/v1/games/"))
            with DB_LOCK:
                game = STORE.game(game_id)
            self._json(200, game) if game else self._json(404, {"error": "game not found"})
        elif parsed.path == "/api/v1/stream":
            self._stream()
        elif parsed.path == "/api/v1/health":
            with DB_LOCK:
                board = STORE.scoreboard()
            stale_live = sum(g["stale"] and g["status"] in LIVE_STATUSES for g in board["games"])
            self._json(200 if not stale_live else 503, {
                "ok": not stale_live, "staleLiveGames": stale_live,
                "providers": board["providerHealth"],
            })
        elif parsed.path in {"/admin", "/admin/"}:
            self._file(ROOT / "admin" / "index.html", no_store=True)
        elif parsed.path in {"/report", "/report/"}:
            self._file(ROOT / "report" / "index.html", no_store=True)
        elif parsed.path == "/api/v1/sources":
            with DB_LOCK:
                sources = [dict(row) for row in STORE.db.execute(
                    "SELECT id,name,kind,homepage_url,permission_status,attribution "
                    "FROM sources WHERE enabled=1 ORDER BY name"
                )]
            self._json(200, {"sources": sources})
        else:
            relative = unquote(parsed.path).lstrip("/") or "index.html"
            candidate = (STATIC_ROOT / relative).resolve()
            parts = Path(relative).parts
            allowed = (
                ".." not in parts and
                (relative in STATIC_FILES or (parts and parts[0] == "assets"))
            )
            if (
                not allowed or
                (STATIC_ROOT not in candidate.parents and candidate != STATIC_ROOT)
            ):
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._file(candidate)

    def _scoreboard(self, query: dict[str, list[str]]) -> None:
        filters = {key: values[0][:100] for key, values in query.items() if values}
        cache_key = json.dumps(filters, sort_keys=True)
        cached = CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < 10:
            body, etag = cached[1], cached[2]
        else:
            with DB_LOCK:
                board = STORE.scoreboard(filters)
            body = json.dumps(board, separators=(",", ":")).encode()
            etag = f'"{hashlib.sha256(body).hexdigest()[:24]}"'
            CACHE[cache_key] = (time.monotonic(), body, etag)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=10, stale-while-revalidate=20")
        self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        observed = CHANGE_VERSION
        try:
            for _ in range(30):
                with VERSION:
                    VERSION.wait_for(lambda: CHANGE_VERSION != observed, timeout=20)
                    current = CHANGE_VERSION
                if current != observed:
                    observed = current
                    event = f"event: scoreboard\ndata: {{\"version\":{observed}}}\n\n"
                else:
                    event = ": keepalive\n\n"
                self.wfile.write(event.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _file(self, path: Path, no_store: bool = False) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if no_store else "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
                         "frame-src https://scorestream.com")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        reporter_route = parsed.path in {
            "/api/v1/reporters/score", "/api/v1/reporters/sms",
        }
        if not reporter_route and not self._authorized():
            self._json(401, {"error": "valid admin bearer token required"})
            return
        try:
            body = self._body()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        with DB_LOCK:
            self._do_post(parsed, reporter_route, body)

    def _do_post(self, parsed, reporter_route: bool, body: dict) -> None:
        try:
            if reporter_route:
                reporter = authenticate_reporter(
                    STORE, str(body.get("reporterId", "")), str(body.get("secret", ""))
                )
                if parsed.path.endswith("/sms"):
                    observation = parse_sms(STORE, str(body.get("message", "")), reporter)
                else:
                    game = STORE.db.execute(
                        "SELECT * FROM games WHERE id=?", (str(body.get("gameId", "")),)
                    ).fetchone()
                    if not game:
                        raise KeyError(body.get("gameId"))
                    if not ({game["home_team_id"], game["away_team_id"]} & set(reporter["teamIds"])):
                        raise PermissionError("reporter is not assigned to this game")
                    observation = Observation(
                        game["id"], f"reporter:{reporter['id']}",
                        int(body["homeScore"]), int(body["awayScore"]),
                        body.get("status"), body.get("clock"), 0.98,
                    )
                result = submit_observation(STORE, observation)
                if result["published"]:
                    notify_change()
                self._json(202, result)
            elif parsed.path == "/api/v1/admin/corrections":
                if not str(body.get("reason", "")).strip():
                    raise ValueError("reason is required")
                ids = STORE.correct(
                    str(body.get("gameId", "")), body.get("updates") or {},
                    str(body.get("reason", "")).strip(), str(body.get("actor", "admin"))[:80],
                )
                notify_change()
                self._json(201, {"correctionIds": ids})
            elif parsed.path.startswith("/api/v1/admin/corrections/") and parsed.path.endswith("/rollback"):
                correction_id = int(parsed.path.split("/")[-2])
                STORE.rollback(correction_id, str(body.get("actor", "admin"))[:80])
                notify_change()
                self._json(200, {"rolledBack": correction_id})
            elif parsed.path == "/api/v1/admin/ingest":
                result = ingest(STORE, configured_feeds())
                if result.get("changed"):
                    notify_change()
                self._json(200, result)
            elif parsed.path == "/api/v1/admin/sources":
                register_source(STORE, body)
                self._json(201, {"sourceId": body["id"]})
            elif parsed.path == "/api/v1/admin/reporters":
                register_reporter(
                    STORE, str(body["id"]), str(body["name"]),
                    [str(value) for value in body.get("teamIds", [])], str(body["secret"]),
                )
                self._json(201, {"reporterId": body["id"]})
            elif parsed.path == "/api/v1/admin/radio-observations":
                observations = extract_radio_observations(
                    STORE, str(body["sourceId"]), str(body["transcript"]),
                    str(body["gameId"]),
                )
                results = [submit_observation(STORE, observation) for observation in observations]
                if any(result["published"] for result in results):
                    notify_change()
                self._json(202, {"extracted": len(observations), "results": results})
            elif parsed.path == "/api/v1/admin/evidence":
                source = STORE.db.execute(
                    "SELECT * FROM sources WHERE id=? AND enabled=1 "
                    "AND permission_status='granted'", (str(body["sourceId"]),)
                ).fetchone()
                if not source or source["kind"] not in {"social", "ocr", "media"}:
                    raise PermissionError("evidence source is not permission-approved")
                observation = Observation(
                    str(body["gameId"]), source["id"], int(body["homeScore"]),
                    int(body["awayScore"]), body.get("status"), body.get("clock"),
                    min(float(body.get("confidence", 0.35)), 0.6),
                    hashlib.sha256(str(body.get("evidenceId", "")).encode()).hexdigest(),
                )
                result = submit_observation(STORE, observation)
                if result["published"]:
                    notify_change()
                self._json(202, result)
            else:
                self._json(404, {"error": "not found"})
        except KeyError:
            self._json(404, {"error": "record not found"})
        except PermissionError as exc:
            self._json(403, {"error": str(exc)})
        except (TypeError, ValueError) as exc:
            self._json(400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the GHSA live scoreboard")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()
    if not args.no_ingest and configured_feeds():
        threading.Thread(target=run_ingestion_loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"GHSA Scoreboard listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
