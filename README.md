# Georgia High School Scoreboard

A mobile-first, installable scoreboard for Georgia high school football. It supports a licensed
live-data feed, normalized historical storage, server-sent updates, favorites, discovery filters,
game details, feed-freshness warnings, audited manual corrections, and a permission-first community
score desk.

The hosted GitHub Pages version remains compatible with `public/scores.json`, but that file is an
offline fallback. Production live scores require the backend.

## Run locally

Python 3.12 is the only runtime dependency.

```bash
python -m backend.server --no-ingest
# open http://127.0.0.1:8080
```

The first run creates `data/scoreboard.db` and seeds it from `data/schools.json` and
`public/scores.json`.

Run tests with:

```bash
python -m unittest discover -v
```

## Connect a licensed feed

The generic adapter expects JSON shaped as:

```json
{
  "teams": [{
    "id": "stable-team-id",
    "name": "School",
    "aliases": ["Alternate name"],
    "classification": "AAAAA",
    "region": "6",
    "record": "3-0",
    "ranking": 4,
    "venue": "Stadium",
    "latitude": 34.0,
    "longitude": -84.0,
    "broadcastUrl": "https://example.com/broadcast"
  }],
  "games": [{
    "id": "stable-game-id",
    "sourceGameId": "provider-id",
    "kickoff": "2026-09-05T00:00:00Z",
    "homeTeamId": "home-id",
    "awayTeamId": "away-id",
    "homeScore": 14,
    "awayScore": 7,
    "status": "Q3",
    "period": "Q3",
    "clock": "04:32",
    "possessionTeamId": "home-id",
    "homeTimeouts": 2,
    "awayTimeouts": 3,
    "venue": "Stadium",
    "confidence": 0.98,
    "staleAfterSeconds": 120,
    "featured": true,
    "scoringEvents": [{
      "sequence": 1,
      "period": "Q1",
      "clock": "08:14",
      "teamId": "home-id",
      "description": "Touchdown",
      "homeScore": 7,
      "awayScore": 0
    }]
  }]
}
```

Configure ordered primary and failover URLs. Tokens stay on the server.

```bash
export SCORE_FEED_URLS=https://primary.example/feed,https://backup.example/feed
export SCORE_FEED_0_NAME=primary
export SCORE_FEED_0_TOKEN=...
export SCORE_FEED_1_NAME=backup
export SCOREBOARD_ADMIN_TOKEN=...
python -m backend.server
```

The scheduler checks every 30 seconds while games are active and every five minutes otherwise.
Providers are retried with backoff and then fail over in configured order. Duplicate game events
are ignored. Invalid scores, confidence values, teams, statuses, and backward game transitions are
rejected.

For a one-shot scheduled ingestion:

```bash
python scripts/ingest_scores.py
```

`scripts/refresh_scores.py` is a deprecated, low-confidence MaxPreps fallback. It runs only when
`ENABLE_SCRAPE_FALLBACK=1` and never advances the displayed update time unless a score changes.

## API

- `GET /api/v1/scoreboard` — cached board; filters: `date`, `status`, `q`, `classification`, `region`
- `GET /api/v1/games/{id}` — game, teams, and scoring timeline
- `GET /api/v1/stream` — server-sent change events
- `GET /api/v1/health` — provider and stale-live-game health
- `POST /api/v1/admin/corrections` — audited field correction
- `POST /api/v1/admin/corrections/{id}/rollback` — restore a corrected value
- `POST /api/v1/admin/ingest` — trigger ingestion

Admin routes require `Authorization: ****** The browser console is at
`/admin`. Run behind TLS and an authenticating reverse proxy in production.

## Multi-source score desk

The homepage embeds ScoreStream's public Georgia widget for immediate statewide context. Its content
stays hosted by ScoreStream and is not ingested into the custom scoreboard.

An administrator can enroll a school, booster, or media reporter at `/admin`. The reporter submits
at `/report`, or an SMS gateway can translate a trusted message into:

```http
POST /api/v1/reporters/sms
Content-Type: application/json

{"reporterId":"west-stand","secret":"…","message":"CAR 21 CAT 7 Q3 4:32"}
```

Keep the reporter secret in the gateway, validate the gateway's own webhook signature, and send this
request to the backend over TLS. Reporter assignments prevent updates to unrelated games.

Permission-approved radio can be transcribed locally with Whisper or another on-device engine. Pipe
only the resulting excerpt to the processor; it never stores the transcript:

```bash
whisper /tmp/approved-station-segment.wav --model small --output_format txt --output_dir /tmp
python scripts/process_radio_transcript.py --source gradick-radio --game GAME_ID \
  < /tmp/approved-station-segment.txt
rm /tmp/approved-station-segment.*
```

Register the station and its written permission in `/admin` first. Radio, approved official social,
and permitted video-scoreboard OCR enter as low-confidence observations. They require two matching
observations within ten minutes before changing a public score. The generic authenticated
`POST /api/v1/admin/evidence` route accepts social/OCR observations with `sourceId`, `gameId`,
`homeScore`, `awayScore`, an optional `status`/`clock`, and a stable `evidenceId`.

Starter source records live in `data/sources.json`; none of those acquisition sources is enabled.
Do not add stream URLs or enable monitoring until the broadcaster or school grants permission.

## Partnership outreach

Ask ScoreStream (`partner@scorestream.com`) about a hobby API license. For AJC Varsity, GPB,
WSB-TV, Score Atlanta, or a local radio group, request a read-only JSON feed and written display rights.
Offer visible attribution, outbound links, correction access, rate limits, and no transcript/audio
redistribution. Confirm geographic coverage, update latency, historical access, caching, pricing,
logo rights, and termination requirements before connecting a feed.

## Deployment

Build `Dockerfile`, mount persistent storage at `/data`, configure the feed and admin environment
variables, and expose port 8080 behind HTTPS. The health probe is `/api/v1/health`. A single process
is recommended because SQLite and the in-process SSE notifier are intentionally simple; move to a
managed SQL database and shared event bus before horizontal scaling.

The PWA caches its shell and recent static fallback for offline use. Favorites stay in browser local
storage. See [DATA_POLICY.md](DATA_POLICY.md) before choosing or enabling any provider.

## Current catalog

`data/schools.json` is the static starter catalog. A provider feed can continuously upsert the full
statewide catalog, including aliases, classification, region, ranking, record, venue, coordinates,
broadcast link, colors, and licensed logo path while retaining stable IDs.

## Status values

`scheduled`, `Q1`, `Q2`, `HALF`, `Q3`, `Q4`, `OT`, `FINAL`, `delayed`, `postponed`, `canceled`.

## License and affiliation

Unofficial fan project. Not affiliated with GHSA, GPB, MaxPreps, ScoreStream, or any school.
