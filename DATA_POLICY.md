# Score data policy

This is an unofficial scoreboard and is not affiliated with GHSA.

## Sources and licensing

The production service accepts a contracted JSON feed through `SCORE_FEED_URLS`. Before enabling
a provider, the operator must obtain written confirmation covering:

- permission to display and redistribute live scores;
- Georgia statewide and out-of-state opponent coverage;
- update interval, latency target, uptime, and support;
- current-season and historical data access;
- permitted display of team names, logos, rankings, and statistics;
- pricing, request limits, caching, attribution, and termination terms.

GPB, GHSA, ScoreStream, and commercial sports-data vendors are candidates for direct evaluation.
No permission, pricing, coverage, or service level is assumed by this repository. Record the signed
provider terms outside the public repository before deployment. MaxPreps scraping is an explicitly
enabled, low-confidence emergency fallback and must comply with its applicable terms.

## Freshness

“Last score change” identifies when score data changed. “Feed checked” identifies the most recent
provider request. The primary “Updated” label uses the last successful data update, never a request
time. Live games are marked **delayed feed** when their last successful update exceeds the configured
staleness threshold.

## Corrections

Authorized operators can use `/admin` to correct a game. Every changed field records its previous
and new values, reason, operator, and time. Corrections can be rolled back through the admin API.

## Privacy and analytics

Favorites remain in the browser. This version does not create accounts or collect behavioral
analytics. Browser notification delivery is intentionally deferred until a production push provider
and privacy policy are selected.
