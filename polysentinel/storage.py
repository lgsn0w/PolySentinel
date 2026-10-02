from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
 address TEXT PRIMARY KEY, funding_source TEXT NOT NULL DEFAULT 'Unknown',
 account_created_ts INTEGER, portfolio_value REAL, enriched_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trades (
 trade_id TEXT PRIMARY KEY, whale_address TEXT NOT NULL REFERENCES wallets(address),
 timestamp INTEGER NOT NULL, condition_id TEXT NOT NULL, market_question TEXT NOT NULL,
 category TEXT NOT NULL, side TEXT NOT NULL, outcome TEXT NOT NULL, position TEXT NOT NULL,
 size_usd REAL NOT NULL CHECK(size_usd >= 0), bet_link TEXT NOT NULL, tx_hash TEXT NOT NULL,
 flagged INTEGER NOT NULL DEFAULT 0 CHECK(flagged IN (0,1))
);
CREATE INDEX IF NOT EXISTS trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS trades_wallet ON trades(whale_address,timestamp);
CREATE INDEX IF NOT EXISTS trades_window ON trades(whale_address,condition_id,side,outcome,timestamp);
CREATE INDEX IF NOT EXISTS trades_cotiming ON trades(condition_id,side,outcome,timestamp);
CREATE TABLE IF NOT EXISTS pending_trades (
 trade_id TEXT PRIMARY KEY, condition_id TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pending_condition ON pending_trades(condition_id);
CREATE TABLE IF NOT EXISTS scanner_state (
 id INTEGER PRIMARY KEY CHECK(id=1), cursor INTEGER NOT NULL DEFAULT 0,
 last_success INTEGER, last_trade INTEGER, status TEXT NOT NULL DEFAULT 'starting'
);
INSERT OR IGNORE INTO scanner_state(id) VALUES(1);
CREATE TABLE IF NOT EXISTS funding_reports (
 address TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'queued',
 requested_at INTEGER NOT NULL, started_at INTEGER, checked_at INTEGER,
 generation INTEGER NOT NULL DEFAULT 1, report TEXT
);
CREATE INDEX IF NOT EXISTS funding_queue ON funding_reports(status,requested_at);
CREATE TABLE IF NOT EXISTS funding_requests (
 id INTEGER PRIMARY KEY, address TEXT NOT NULL, requested_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS funding_requests_time ON funding_requests(requested_at);
CREATE TABLE IF NOT EXISTS funding_edges (
 root TEXT NOT NULL REFERENCES funding_reports(address), edge_id TEXT NOT NULL,
 sender TEXT NOT NULL, receiver TEXT NOT NULL, contract TEXT NOT NULL,
 amount TEXT NOT NULL, timestamp INTEGER NOT NULL, tx_hash TEXT NOT NULL,
 kind TEXT NOT NULL, depth INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(root,edge_id)
);
CREATE INDEX IF NOT EXISTS funding_sender ON funding_edges(sender,contract,receiver);
CREATE INDEX IF NOT EXISTS funding_receiver ON funding_edges(receiver,contract,sender);
CREATE TABLE IF NOT EXISTS receipt_cache (
 tx_hash TEXT PRIMARY KEY, checked_at INTEGER NOT NULL, status TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classification_jobs (
 address TEXT PRIMARY KEY REFERENCES funding_reports(address), status TEXT NOT NULL,
 requested_at INTEGER NOT NULL, started_at INTEGER, checked_at INTEGER,
 generation INTEGER NOT NULL DEFAULT 1, result TEXT
);
CREATE INDEX IF NOT EXISTS classification_queue ON classification_jobs(status,requested_at);
PRAGMA user_version=3;
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError("Unsupported database schema version")
            conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def state(self):
        with self.connection() as conn:
            return dict(
                conn.execute("SELECT * FROM scanner_state WHERE id=1").fetchone()
            )

    def set_status(self, status):
        with self.connection() as conn:
            conn.execute("UPDATE scanner_state SET status=? WHERE id=1", (status,))
