def flag_window(conn, trade, settings):
    if trade["size_usd"] < settings.accumulation_minimum:
        return
    args = (trade["whale_address"], trade["condition_id"], trade["side"], trade["outcome"],
            trade["timestamp"] - settings.window_seconds, trade["timestamp"],
            settings.accumulation_minimum)
    predicate = """whale_address=? AND condition_id=? AND side=? AND outcome=?
                   AND timestamp BETWEEN ? AND ? AND size_usd>=?"""
    volume = conn.execute(f"SELECT SUM(size_usd) FROM trades WHERE {predicate}", args).fetchone()[0] or 0
    if volume >= settings.alert_usd:
        conn.execute(f"UPDATE trades SET flagged=1 WHERE {predicate}", args)
