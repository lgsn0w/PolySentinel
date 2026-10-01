# PolySentinel

PolySentinel monitors political markets on Polymarket and highlights unusual trading activity. Flags are based on observed trade volume; they do not establish insider knowledge, identity, or misconduct.

![Dashboard](static/dashboard.png)

The screenshots show the original interface and may differ from the current version.

## Run locally

Requires Python 3.10+ and Node.js 20+ for frontend tests.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe server.py
```

In another terminal:

```powershell
.\.venv\Scripts\python.exe PolyInsideScanner.py
```

Open http://127.0.0.1:5000. Both processes must use the same `SENTINEL_DB` path. Relative paths resolve against the repository directory. The web server initializes an empty database independently of the scanner.

Public Polymarket data requires no API key. Optional funding enrichment uses `ETHERSCAN_API_KEY` in `.env`, with the Etherscan V2 API and Polygon chain ID 137. Existing PolygonScan keys are not interchangeable with Etherscan keys. Missing credentials leave funding information unknown. API errors preserve previously fetched information.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SENTINEL_DB` | `data/sentinel.sqlite3` | Unified SQLite database |
| `POLL_SECONDS` | `15` | Scanner polling interval |
| `LOOKBACK_SECONDS` | `600` | History requested for a new database |
| `ETHERSCAN_API_KEY` | empty | Optional funding lookup |

## Docker

```sh
docker compose up --build -d
docker compose logs -f scanner
```

Compose runs the scanner and Gunicorn web server separately, sharing a named database volume. The dashboard port binds to localhost. To deploy publicly, configure HTTPS and a reverse proxy for the Gunicorn service. The built-in Flask server is for local development.

## Data and detection

The scanner paginates active events, refreshes its political market map hourly, and requests public taker trades worth at least $10. Each qualifying trade is persisted immediately. Unknown conditions are looked up by condition ID in both open and closed markets. Unavailable classifications enter a durable pending queue and are retried in rotating batches, even after falling outside the trade overlap. Known non-political conditions are excluded. Conditions that the API never resolves remain pending and can grow the database; they are not silently deleted. A rolling, inclusive 600-second window flags individual trades worth at least $500 when their combined value reaches $3,000 for the same wallet, market, side, and outcome. Late arrivals re-evaluate affected windows; persisted trades survive restarts.

Trade insertion, detection flags, and progress commit in one transaction. Failed validation, incomplete pagination, and failed writes do not advance progress. Subsequent polls overlap the persisted cursor by 120 seconds. Events use Gamma keyset pagination filtered by political tags; trades use Data API V2 cursor pagination with unchanged filters across pages. The global trade feed ignores server-side time bounds, so the client walks newest-first until it crosses its own history cutoff. Repeated cursors, inconsistent pagination, or an exhausted request budget produce an error rather than silently skipping history.

Trade identity combines transaction hash, wallet, token, market, side, outcome, timestamp, size, and price. The public API does not expose a fill index: genuinely distinct fills with every identity field identical cannot be distinguished and will collapse into one record. Delayed records older than the overlap can require a larger replay window. The global V2 feed exposes the current and previous calendar month, so it cannot recover arbitrarily old outages. The source is a public taker-trade feed, not a complete audited ledger or a guarantee of exchange-wide volume. Empty outcomes explicitly marked with outcome index 999 are retained as unlabeled, with separate detection groups for each token.

Wallet enrichment runs separately from ingestion. A reported funding source describes an observed incoming normal transaction among the first ten transactions, not proven ultimate funding provenance. Failed enrichment is retried after an hour.

Dashboard sentiment counts BUY Yes and SELL No as bullish, BUY No and SELL Yes as bearish; other outcomes are excluded from those counts. These are activity classifications, not forecasts. The velocity chart uses 48 half-hour buckets with explicit timestamps. Flagged and other activity are disjoint subsets of the same persisted data. "LIVE" requires a successful scanner poll within 90 seconds and an OK scanner status.

## Existing databases

The original `whale_hunter.db` and `insider_intel.db` are preserved locally but excluded from future commits. The refactored application uses a new database and does not automatically import legacy aggregates. Legacy records lack reliable individual trade identity and can overlap; importing them into the new ledger would risk double counting. Keep these files as historical snapshots. Existing Git history still contains them.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.cjs
```

Tests cover replay, timestamp ties, distinct fills in one transaction, restarts, delayed trades, window boundaries, isolation between markets and sides, transaction rollback, malformed upstream data, pagination, wallet enrichment, dashboard totals, chart timestamps, API errors, frontend rendering, and startup recovery. They run offline without credentials.

`/healthz` checks web/database availability and reports scanner state separately. A healthy web server does not imply a running scanner. `/api/stats`, `/api/insider_data`, and `/api/whale/<address>` provide dashboard data. Database failures return HTTP 503; malformed wallet addresses return HTTP 400.

## Structure

- `polysentinel/config.py`: environment configuration.
- `polysentinel/clients.py`: validated public API requests and optional enrichment.
- `polysentinel/storage.py`: SQLite schema and connection lifecycle.
- `polysentinel/scanner.py`: normalization, transactional ingestion, polling, enrichment.
- `polysentinel/detection.py`: volume window flags.
- `polysentinel/queries.py`: dashboard queries.
- `polysentinel/web.py`: Flask app factory and routes.
- `PolyInsideScanner.py` and `server.py`: executable entry points.
