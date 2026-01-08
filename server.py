from flask import Flask, jsonify, render_template
from flask_cors import CORS
import sqlite3
import logging
import time

app = Flask(__name__)
CORS(app)

# Silenciar logs não críticos do werkzeug para manter o console limpo
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# Configuração dos Bancos de Dados
DB_MAIN = "whale_hunter.db"
DB_INSIDER = "insider_intel.db"

def get_db_connection(db_path):
    """
    Estabelece uma conexão robusta com o SQLite com WAL ativado.
    WAL (Write-Ahead Logging) melhora a concorrência, permitindo leituras
    e escritas simultâneas sem bloquear o banco.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)  # Timeout aumentado para lidar com locks concorrentes
    conn.execute("PRAGMA journal_mode=WAL;")       # Ativa o Write-Ahead Logging
    conn.execute("PRAGMA synchronous=NORMAL;")     # Otimiza a sincronização para performance
    conn.row_factory = sqlite3.Row
    return conn

def get_main_db():
    return get_db_connection(DB_MAIN)

def get_insider_db():
    return get_db_connection(DB_INSIDER)


# --- ROTAS (FRONTEND) ---

@app.route("/")
def index():
    return render_template("home.html")


@app.route("/insider")
def insider():
    return render_template("insider.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/disclaimer")
def disclaimer():
    return render_template("disclaimer.html")


@app.route('/dev')
def dev():
    return render_template('dev.html')


# --- API: DASHBOARD ---

@app.route("/api/stats")
def stats():
    start_time = time.time()

    try:
        # 1. OPERAÇÕES NO BANCO PRINCIPAL (STREAM)
        # Inicializa o contexto de conexão
        conn = get_main_db()
        cur = conn.cursor()

        # Recupera Jogadas de Alta Convicção (Comportamento de aposta repetida)
        cur.execute("""
            SELECT
                market_question,
                MAX(bet_link) AS link,
                COUNT(*) AS count,
                AVG(size_usd) AS avg_size
            FROM bets
            GROUP BY market_question
            HAVING count >= 1
            ORDER BY avg_size DESC
            LIMIT 5
        """)
        conviction = [dict(r) for r in cur.fetchall()]

        # Recupera Atividade Agregada de Baleias (Maiores volumes por carteira)
        cur.execute("""
            SELECT
                b.whale_address,
                b.market_question,
                SUM(b.size_usd) AS total_size,
                w.funding_source,
                b.bet_link
            FROM bets b
            JOIN whales w ON b.whale_address = w.address
            GROUP BY b.whale_address, b.market_question
            ORDER BY total_size DESC
            LIMIT 10
        """)
        whales = [dict(r) for r in cur.fetchall()]

        # Feed de Ticker em Tempo Real (Últimas apostas)
        cur.execute("""
            SELECT b.*, w.funding_source
            FROM bets b
            JOIN whales w ON b.whale_address = w.address
            ORDER BY b.timestamp DESC
            LIMIT 20
        """)
        feed = [dict(r) for r in cur.fetchall()]

        # Cálculo do Gráfico de Velocidade (Janela de 24h / Buckets de 30min)
        current_ts = int(time.time())
        twenty_four_hours_ago = current_ts - 86400
        bucket_size = 1800  # Resolução de 30 minutos

        cur.execute("""
            SELECT
                (timestamp / ?) * ? AS bucket,
                SUM(size_usd) AS volume
            FROM bets
            WHERE timestamp > ?
            GROUP BY bucket
            ORDER BY bucket ASC
        """, (bucket_size, bucket_size, twenty_four_hours_ago))

        velocity_rows = [dict(r) for r in cur.fetchall()]
        velocity_map = {row["bucket"]: row["volume"] for row in velocity_rows}

        # Preenche buckets vazios com zero para continuidade do gráfico
        chart_data = []
        num_points = 48  # 24 horas * 2 pontos/hora

        for i in range(num_points):
            t = current_ts - (bucket_size * (num_points - 1 - i))
            bucket = (t // bucket_size) * bucket_size
            chart_data.append(velocity_map.get(bucket, 0))

        # Análise de Sentimento (Razão Bull/Bear baseada em atividade recente)
        cur.execute("""
            SELECT
                SUM(CASE WHEN position LIKE '%Yes%' THEN 1 ELSE 0 END) AS bull_count,
                SUM(CASE WHEN position LIKE '%No%' THEN 1 ELSE 0 END) AS bear_count,
                AVG(size_usd) AS avg_bet
            FROM (
                SELECT position, size_usd
                FROM bets
                ORDER BY timestamp DESC
                LIMIT 100
            )
        """)
        sent_data = cur.fetchone()
        sentiment = {
            "bulls": sent_data["bull_count"] or 0,
            "bears": sent_data["bear_count"] or 0,
            "avg_size": sent_data["avg_bet"] or 0,
        }

        # Calcula o Volume Total do Mercado monitorado
        cur.execute("SELECT SUM(size_usd) FROM bets")
        total_market_vol = cur.fetchone()[0] or 0
        conn.close()

        # 2. OPERAÇÕES NO BANCO INSIDER (FORENSE)
        # Cruzamento de dados com informações verificadas de insiders
        conn_in = get_insider_db()
        cur_in = conn_in.cursor()
        cur_in.execute("SELECT SUM(size_usd) FROM intel_bets")
        verified_whale_vol = cur_in.fetchone()[0] or 0
        conn_in.close()

        retail_vol = max(0, total_market_vol - verified_whale_vol)
        volume_split = {
            "whale": verified_whale_vol,
            "retail": retail_vol,
        }

        latency = round((time.time() - start_time) * 1000, 2)

        return jsonify({
            "conviction_plays": conviction,
            "largest_whales": whales,
            "feed": feed,
            "volume_chart": volume_split,
            "velocity_chart": chart_data,
            "sentiment": sentiment,
            "latency": latency,
        })

    except Exception as e:
        return jsonify({"error": str(e)})


# --- API: DADOS INSIDER ---

@app.route("/api/insider_data")
def insider_data():
    start_time = time.time()

    try:
        conn = get_insider_db()
        cur = conn.cursor()

        # Recupera lista de carteiras monitoradas por ordem de atividade
        cur.execute("""
            SELECT
                address,
                total_scanned_volume,
                last_active_ts,
                funding_source,
                account_created_ts
            FROM intel_whales
            ORDER BY last_active_ts DESC
            LIMIT 50
        """)
        roster = [dict(r) for r in cur.fetchall()]

        # Enriquece a lista com o principal mercado de atuação e a maior aposta
        for r in roster:
            cur.execute("""
                SELECT market_question
                FROM intel_bets
                WHERE whale_address = ?
                GROUP BY market_question
                ORDER BY SUM(size_usd) DESC
                LIMIT 1
            """, (r["address"],))
            top = cur.fetchone()
            r["top_market"] = top["market_question"] if top else "Analisando..."

            cur.execute("""
                SELECT MAX(size_usd) AS big_bet
                FROM intel_bets
                WHERE whale_address = ?
            """, (r["address"],))
            mb = cur.fetchone()
            r["max_bet"] = mb["big_bet"] if mb["big_bet"] else 0

        conn.close()

        latency = round((time.time() - start_time) * 1000, 2)
        return jsonify({"roster": roster, "latency": latency})

    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/whale/<address>")
def whale_history(address):
    try:
        conn = get_insider_db()
        cur = conn.cursor()

        # Histórico detalhado de apostas para uma carteira específica
        cur.execute("""
            SELECT *
            FROM intel_bets
            WHERE whale_address = ?
            ORDER BY timestamp DESC
            LIMIT 50
        """, (address,))
        history = [dict(r) for r in cur.fetchall()]
        conn.close()

        return jsonify({"history": history})

    except Exception:
        return jsonify({"history": []})


if __name__ == "__main__":
    print(">> Servidor Online na Porta 5000")
    # Em produção, debug deve ser False para evitar vulnerabilidades de execução de código
    app.run(host="0.0.0.0", port=5000, debug=False)