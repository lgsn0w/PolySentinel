import logging
import re
import sqlite3
import time

from flask import Flask, jsonify, render_template

from .config import ROOT, Settings
from .queries import roster, stats
from .storage import Store


def create_app(settings=None, store=None):
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    store = store or Store((settings or Settings()).database)
    app.extensions["sentinel_store"] = store

    for page in ("home", "insider", "about", "disclaimer", "dev", "documentation"):
        route = "/" if page == "home" else "/" + page
        app.add_url_rule(route, page, lambda page=page: render_template(page + ".html"))

    @app.get("/healthz")
    def health():
        with store.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        state = store.state()
        fresh = state["status"] == "ok" and state["last_success"] is not None and time.time() - state["last_success"] < 90
        return jsonify(status="ok", scanner={**state, "fresh": fresh})

    @app.get("/api/stats")
    def dashboard():
        started = time.perf_counter()
        with store.connection() as conn:
            conn.execute("BEGIN")
            payload = stats(conn)
        payload["latency"] = round((time.perf_counter() - started) * 1000, 2)
        return jsonify(payload)

    @app.get("/api/insider_data")
    def insiders():
        started = time.perf_counter()
        with store.connection() as conn:
            conn.execute("BEGIN")
            data = roster(conn)
            scanner = dict(conn.execute("SELECT last_success,last_trade,status FROM scanner_state WHERE id=1").fetchone())
        return jsonify(roster=data, scanner=scanner, timestamp=int(time.time() * 1000),
                       latency=round((time.perf_counter() - started) * 1000, 2))

    @app.get("/api/whale/<address>")
    def history(address):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            return jsonify(error="Invalid wallet address"), 400
        with store.connection() as conn:
            data = conn.execute("""SELECT * FROM trades WHERE whale_address=? AND flagged=1
                ORDER BY timestamp DESC,trade_id LIMIT 50""", (address.lower(),)).fetchall()
        return jsonify(history=[dict(r) for r in data])

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.error("Database operation failed", exc_info=error)
        return jsonify(error="Data temporarily unavailable"), 503

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if response.mimetype == "application/json":
            response.headers["Cache-Control"] = "no-store"
        return response

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return app
