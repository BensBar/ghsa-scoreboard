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
from .store import LIVE_STATUSES, Store

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("SCOREBOARD_DB", ROOT / "data" / "scoreboard.db"))
STATIC_ROOT = ROOT
STORE = Store(DB_PATH)
STORE.seed(ROOT / "data" / "schools.json", ROOT / "public" / "scores.json")
VERSION = threading.Condition()
CHANGE_VERSION = 0
CACHE: dict[str, tuple[float, bytes, str]] = {}


def notify_change() -> None:
    global CHANGE_VERSION
    with VERSION:
        CHANGE_VERSION += 1
        CACHE.clear()
        VERSION.notify_all()


def run_ingestion_loop() -> None:
    while True:
        result = ingest(STORE, configured_feeds())
        if result.get("changed"):
            notify_change()
        active = STORE.db.execute(
            f"SELECT 1 FROM games WHERE status IN ({','.join('?' for _ in LIVE_STATUSES)}) LIMIT 1",
            tuple(LIVE_STATUSES),
        ).fetchone()
        time.sleep(30 if active else 300)


class Handler(BaseHTTPRequestHandler):
    server_version = "GHSA-Scoreboard/2.0"

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
            return json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError) as exc:
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
            game = STORE.game(game_id)
            self._json(200, game) if game else self._json(404, {"error": "game not found"})
        elif parsed.path == "/api/v1/stream":
            self._stream()
        elif parsed.path == "/api/v1/health":
            board = STORE.scoreboard()
            stale_live = sum(g["stale"] and g["status"] in LIVE_STATUSES for g in board["games"])
            self._json(200 if not stale_live else 503, {
                "ok": not stale_live, "staleLiveGames": stale_live,
                "providers": board["providerHealth"],
            })
        elif parsed.path == "/admin":
            self._file(ROOT / "admin" / "index.html", no_store=True)
        else:
            relative = unquote(parsed.path).lstrip("/") or "index.html"
            candidate = (STATIC_ROOT / relative).resolve()
            if STATIC_ROOT not in candidate.parents and candidate != STATIC_ROOT:
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
            body = json.dumps(STORE.scoreboard(filters), separators=(",", ":")).encode()
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
                         "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._authorized():
            self._json(401, {"error": "valid admin bearer token required"})
            return
        try:
            body = self._body()
            if parsed.path == "/api/v1/admin/corrections":
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
            else:
                self._json(404, {"error": "not found"})
        except KeyError:
            self._json(404, {"error": "record not found"})
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
