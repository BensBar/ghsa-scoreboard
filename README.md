# GHSA Football Scoreboard

Live (auto-refreshing) scoreboard for pinned Georgia high school football teams, plus a statewide **Top games** section.

**Live site:** https://bensbar.github.io/ghsa-scoreboard/

## Pinned schools

| ID | Display name | MaxPreps |
| --- | --- | --- |
| `chattahoochee` | Chattahoochee | [Cougars](https://www.maxpreps.com/ga/alpharetta/chattahoochee-cougars/football/) |
| `johns-creek` | Johns Creek | [Gladiators](https://www.maxpreps.com/ga/johns-creek/johns-creek-gladiators/football/) |
| `carrollton` | Carrollton | [Trojans](https://www.maxpreps.com/ga/carrollton/carrollton-trojans/football/) |
| `central-of-carrollton` | **Central of Carrollton** | [Lions](https://www.maxpreps.com/ga/carrollton/central-lions/football/) |

> **Central of Carrollton** is Central High School (Central, Carroll / Central-Carrollton Lions) — **not** Carrollton High School Trojans.

School metadata (MaxPreps + GPB links) lives in [`data/schools.json`](data/schools.json).

## This week’s seed (Fri Sep 4, 2026)

Pinned kickoffs (ET):

- **Chattahoochee** vs Forsyth Central — home, 7:30 PM
- **Johns Creek** vs Mountain View — home, 7:30 PM
- **Carrollton** at Catholic (Baton Rouge, LA) — away, ~8:00 PM ET
- **Central of Carrollton** at East Paulding — away, 7:30 PM

Top games seeded from Week 3 notables (Buford @ Mallard Creek NC, Gainesville @ East St. Louis, Creekside @ St. Joe’s NJ, Jefferson @ Peach County, Warner Robins @ Northside WR).

## Data schema (`public/scores.json`)

```json
{
  "updatedAt": "2026-09-04T23:40:00Z",
  "pinned": [
    {
      "id": "chattahoochee",
      "name": "Chattahoochee",
      "opponent": "Forsyth Central",
      "homeScore": null,
      "awayScore": null,
      "status": "scheduled",
      "kickoff": "2026-09-04T23:30:00Z",
      "isHome": true
    }
  ],
  "topGames": []
}
```

- `status`: `scheduled` | `Q1` | `Q2` | `Q3` | `Q4` | `HALF` | `FINAL` | `OT`
- `homeScore` / `awayScore`: stadium home/away (null until known)
- `isHome`: whether the named school is the home team

The UI polls `public/scores.json` every **45 seconds**.

## Deploy (GitHub Pages)

Static site — no build step. Workflow: [`.github/workflows/pages.yml`](.github/workflows/pages.yml)

Pages source should be **GitHub Actions**. After the first successful run:

https://bensbar.github.io/ghsa-scoreboard/

## Score refresh Action

[`.github/workflows/refresh-scores.yml`](.github/workflows/refresh-scores.yml) runs `scripts/refresh_scores.py` on a Friday-night cron + `workflow_dispatch`.

**Reality check:** MaxPreps / ghsa.net pages are JS-heavy and scrape-fragile. The script is a best-effort skeleton: it fetches schedule URLs from `data/schools.json`, tries light parsing, and always rewrites `updatedAt`. If parsing fails, **manually edit** `public/scores.json` (or improve the scraper) and push — the site will pick it up on the next poll / Pages deploy.

```bash
python scripts/refresh_scores.py
```

## Local preview

```bash
cd ghsa-scoreboard
python -m http.server 8080
# open http://localhost:8080
```

## License / affiliation

Unofficial fan project. Not affiliated with GHSA, MaxPreps, or the schools listed.
