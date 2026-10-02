import logging
from ipaddress import ip_address
import re
import sqlite3
import time

from flask import Flask, g, jsonify, render_template, request
from urllib.parse import urlsplit

from .config import ROOT, Settings
from .queries import roster, stats
from .storage import Store
from .funding import queue, read_report
from .classification import queue_classification
from .localization import PT, localize_html


def create_app(settings=None, store=None):
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    settings = settings or Settings()
    store = store or Store(settings.database)
    app.extensions["sentinel_store"] = store

    @app.before_request
    def language():
        selected = request.args.get("lang")
        saved = request.cookies.get("sentinel_language")
        g.language = "en"
        if selected in ("en", "pt-BR"):
            g.language = selected
        elif saved in ("en", "pt-BR"):
            g.language = saved

    @app.context_processor
    def language_context():
        return {
            "language": g.language,
            "translations": PT if g.language == "pt-BR" else {},
        }

    for page in ("home", "insider", "about", "disclaimer", "dev", "documentation"):
        route = "/" if page == "home" else "/" + page
        app.add_url_rule(route, page, lambda page=page: render_template(page + ".html"))

    @app.get("/funding")
    @app.get("/transfers")
    def funding_page():
        return render_template("funding.html")

    @app.route("/api/funding/<address>", methods=["GET", "POST"])
    def funding_report(address):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            return jsonify(error="Invalid wallet address"), 400
        address = address.lower()
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if (
                not request.is_json
                or (origin and origin != request.host_url.rstrip("/"))
                or request.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                return jsonify(error="Same-origin JSON requests only"), 403
            try:
                peer = ip_address(request.remote_addr or "")
                local_peer = peer.is_loopback or bool(
                    getattr(peer, "ipv4_mapped", None) and peer.ipv4_mapped.is_loopback
                )
            except ValueError:
                local_peer = False
            if not local_peer or urlsplit(request.host_url).hostname not in (
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                return (
                    jsonify(
                        error="Investigations are local-only. Public hosting requires authentication."
                    ),
                    403,
                )
            if not settings.etherscan_key:
                return (
                    jsonify(
                        error="Configure ETHERSCAN_API_KEY with Polygon access and restart both processes.",
                        status="no_key",
                    ),
                    503,
                )
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or body.get("action", "investigate") not in (
                "investigate",
                "classify",
            ):
                return jsonify(error="Invalid investigation action"), 400
            status, accepted = (
                queue_classification(store, address)
                if body.get("action") == "classify"
                else queue(store, address)
            )
            if status == "no_evidence":
                return (
                    jsonify(
                        error="Investigate transfers first; no saved evidence to classify.",
                        status=status,
                    ),
                    409,
                )
            code = 202 if status in ("queued", "running") else 429
            errors = {
                "cooldown": "Wait ten minutes between requests for this wallet.",
                "busy": "The investigation queue is full (ten jobs).",
                "daily_limit": "The daily investigation budget is exhausted (30 requests per 24 hours).",
            }
            return (
                jsonify(status=status, accepted=accepted, error=errors.get(status)),
                code,
            )
        result = read_report(store, address)
        result["configured"] = bool(settings.etherscan_key)
        response = jsonify(result)
        if request.args.get("download") == "1":
            response.headers["Content-Disposition"] = (
                f'attachment; filename="funding-{address}.json"'
            )
        return response

    @app.get("/healthz")
    def health():
        with store.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        state = store.state()
        fresh = (
            state["status"] == "ok"
            and state["last_success"] is not None
            and time.time() - state["last_success"] < 90
        )
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
            scanner = dict(
                conn.execute(
                    "SELECT last_success,last_trade,status FROM scanner_state WHERE id=1"
                ).fetchone()
            )
        return jsonify(
            roster=data,
            scanner=scanner,
            timestamp=int(time.time() * 1000),
            latency=round((time.perf_counter() - started) * 1000, 2),
        )

    @app.get("/api/whale/<address>")
    def history(address):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            return jsonify(error="Invalid wallet address"), 400
        with store.connection() as conn:
            data = conn.execute(
                """SELECT * FROM trades WHERE whale_address=? AND flagged=1
                ORDER BY timestamp DESC,trade_id LIMIT 50""",
                (address.lower(),),
            ).fetchall()
        return jsonify(history=[dict(r) for r in data])

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.error("Database operation failed", exc_info=error)
        return jsonify(error="Data temporarily unavailable"), 503

    @app.after_request
    def headers(response):
        if response.mimetype == "text/html":
            response.set_data(
                localize_html(response.get_data(as_text=True), g.language)
            )
            response.headers["Content-Language"] = g.language
            response.headers["Cache-Control"] = "no-store"
            if request.args.get("lang") in ("en", "pt-BR"):
                response.set_cookie(
                    "sentinel_language",
                    g.language,
                    max_age=31536000,
                    samesite="Lax",
                    httponly=True,
                    secure=request.is_secure,
                )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if response.mimetype == "application/json":
            response.headers["Cache-Control"] = "no-store"
        return response

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return app
