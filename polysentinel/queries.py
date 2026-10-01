import time


def stats(conn, now=None):
    now = int(time.time()) if now is None else now
    first_bucket = (now // 1800 - 47) * 1800
    conviction = conn.execute("""SELECT market_question,MAX(bet_link) AS link,COUNT(*) AS count,
        AVG(size_usd) AS avg_size FROM trades GROUP BY condition_id ORDER BY avg_size DESC LIMIT 5""").fetchall()
    whales = conn.execute("""SELECT t.whale_address,t.market_question,SUM(t.size_usd) AS total_size,
        w.funding_source,MAX(t.bet_link) AS bet_link FROM trades t JOIN wallets w ON w.address=t.whale_address
        GROUP BY t.whale_address,t.condition_id ORDER BY total_size DESC LIMIT 10""").fetchall()
    feed = conn.execute("""SELECT t.*,w.funding_source FROM trades t JOIN wallets w ON w.address=t.whale_address
        ORDER BY timestamp DESC,trade_id LIMIT 20""").fetchall()
    velocity = dict(conn.execute("""SELECT (timestamp/1800)*1800 AS bucket,SUM(size_usd) FROM trades
        WHERE timestamp>=? AND timestamp<=? GROUP BY bucket""", (first_bucket, now)).fetchall())
    sentiment = conn.execute("""SELECT
        SUM(CASE WHEN (side='BUY' AND lower(outcome)='yes') OR (side='SELL' AND lower(outcome)='no') THEN 1 ELSE 0 END) AS bulls,
        SUM(CASE WHEN (side='BUY' AND lower(outcome)='no') OR (side='SELL' AND lower(outcome)='yes') THEN 1 ELSE 0 END) AS bears,
        AVG(size_usd) AS avg_size FROM (SELECT * FROM trades ORDER BY timestamp DESC,trade_id LIMIT 100)""").fetchone()
    split = conn.execute("""SELECT SUM(CASE WHEN flagged=1 THEN size_usd ELSE 0 END) AS whale,
        SUM(CASE WHEN flagged=0 THEN size_usd ELSE 0 END) AS retail FROM trades""").fetchone()
    scanner = dict(conn.execute("SELECT last_success,last_trade,status FROM scanner_state WHERE id=1").fetchone())
    timestamps = [first_bucket + i * 1800 for i in range(48)]
    return {"conviction_plays": [dict(r) for r in conviction], "largest_whales": [dict(r) for r in whales],
            "feed": [dict(r) for r in feed], "volume_chart": {k: split[k] or 0 for k in split.keys()},
            "velocity_chart": [velocity.get(ts, 0) for ts in timestamps], "velocity_timestamps": timestamps,
            "sentiment": {k: sentiment[k] or 0 for k in sentiment.keys()}, "scanner": scanner,
            "timestamp": now * 1000}


def roster(conn):
    rows = conn.execute("""WITH market_totals AS (
        SELECT whale_address,market_question,SUM(size_usd) AS volume,
            ROW_NUMBER() OVER(PARTITION BY whale_address ORDER BY SUM(size_usd) DESC,condition_id) AS rank
        FROM trades WHERE flagged=1 GROUP BY whale_address,condition_id
    ), totals AS (
        SELECT whale_address,SUM(size_usd) AS total_scanned_volume,MAX(timestamp) AS last_active_ts,
            MAX(size_usd) AS max_bet FROM trades WHERE flagged=1 GROUP BY whale_address
    ) SELECT w.address,w.funding_source,w.account_created_ts,t.total_scanned_volume,t.last_active_ts,
        t.max_bet,m.market_question AS top_market FROM totals t JOIN wallets w ON w.address=t.whale_address
        LEFT JOIN market_totals m ON m.whale_address=t.whale_address AND m.rank=1
        ORDER BY t.last_active_ts DESC,w.address LIMIT 50""").fetchall()
    return [dict(r) for r in rows]
