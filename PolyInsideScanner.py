import os
import requests
import time
import sqlite3
from datetime import datetime

# ==========================================
# CONFIGURAÇÃO DO SISTEMA
# ==========================================
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
DB_MAIN = "whale_hunter.db"
DB_INSIDER = "insider_intel.db"

# --- AUTENTICAÇÃO ---
POLYGONSCAN_API_KEY = os.getenv("POLYGONSCAN_API_KEY")

if not POLYGONSCAN_API_KEY:
    print("AVISO: POLYGONSCAN_API_KEY não encontrada!")

# --- LIMITES DO PIPELINE (THRESHOLDS) ---
# Pipeline A: Ingestão de Alta Frequência (Fluxo Visual/Varejo)
# Objetivo: Capturar o ritmo do mercado e o sentimento do varejo para visualização
STREAM_MIN_SIZE = 10  # Limite mínimo para persistência (USD)
STREAM_NOISE_FLOOR = 9  # Descartar "poeira" (dust) abaixo deste valor

# Pipeline B: Detecção Institucional (Baleias/Forense)
# Objetivo: Identificar padrões de acumulação e implantação de grande capital
INSIDER_MIN_SIZE = 1000  # Valor mínimo para entrada no banco de dados forense
ACCUMULATION_FLOOR = 500  # Valor mínimo para iniciar a agregação em buckets
LADDER_WINDOW = 600  # Janela de tempo (segundos) para lógica de agregação
INSIDER_TRIGGER = 3000  # Gatilho para marcar carteira como "Ponto de Interesse"
CRITICAL_TRIGGER = 5000  # Gatilho de alerta imediato para anomalias significativas

# Whitelist de Entidades Conhecidas para identificação de fonte de fundos
KNOWN_WALLETS = {
    "0xa9d1e08c7793af67e9d92fe3028ac693eb80b7d0": "Coinbase",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance Hot Wallet",
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b438": "Tornado Cash",
    "0x88a14b5da995328831f2479e0004e57879102c48": "Uniswap",
    "0x4a14347083b80e5216ca31350a2d21702ac3650d": "Wintermute"
}


class WhaleSentinel:
    def __init__(self):
        self.market_cache = {}
        self.politics_ids = set()
        self.ladder_buckets = {}
        self.last_seen_ts = int(time.time())
        self.initialize_databases()

    def get_db_connection(self, db_path):
        """
        Cria uma conexão SQLite robusta com WAL ativado.
        O timeout de 30s previne erros de 'database locked' durante leituras do servidor.
        """
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def initialize_databases(self):
        """Inicializa o esquema (schema) para ambas as camadas de persistência se não existirem."""

        # Inicializa Banco Principal (Stream)
        conn = self.get_db_connection(DB_MAIN)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS whales (
                address TEXT PRIMARY KEY, 
                first_seen INTEGER, 
                last_seen INTEGER, 
                total_volume REAL DEFAULT 0, 
                funding_source TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                whale_address TEXT, 
                timestamp INTEGER, 
                market_question TEXT, 
                category TEXT, 
                position TEXT, 
                size_usd REAL, 
                bet_link TEXT, 
                tx_hash TEXT, 
                processed_by_analyst BOOLEAN DEFAULT 0, 
                FOREIGN KEY(whale_address) REFERENCES whales(address)
            )
        ''')
        conn.commit()
        conn.close()

        # Inicializa Banco Insider (Forense)
        conn = self.get_db_connection(DB_INSIDER)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS intel_whales (
                address TEXT PRIMARY KEY, 
                funding_source TEXT, 
                account_created_ts INTEGER, 
                portfolio_value REAL, 
                total_scanned_volume REAL DEFAULT 0, 
                last_active_ts INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS intel_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                whale_address TEXT, 
                timestamp INTEGER, 
                market_question TEXT, 
                position TEXT, 
                size_usd REAL, 
                FOREIGN KEY(whale_address) REFERENCES intel_whales(address)
            )
        ''')
        conn.commit()
        conn.close()

    def get_wallet_intel(self, wallet):
        """
        Executa análise forense em um endereço de carteira específico.
        Agrega dados da Gamma API, Data API e PolygonScan.
        """
        intel = {"source": "Desconhecido", "created": 0, "portfolio": 0}

        # A. ANÁLISE DE PERFIL (Gamma API)
        try:
            r = requests.get(f"{GAMMA_API}/users/{wallet}", timeout=4)
            if r.status_code == 200:
                data = r.json()
                joined_str = data.get('createdAt')
                if joined_str:
                    dt = datetime.fromisoformat(joined_str.replace('Z', '+00:00'))
                    intel['created'] = int(dt.timestamp())
        except Exception:
            pass

        # B. VALUATION DO PORTFÓLIO (Data API)
        try:
            pv = requests.get(f"{DATA_API}/value?user={wallet}", timeout=4).json()
            val = float(pv.get('value', 0))
            if val == 0:
                # Fallback para agregação de posições se o endpoint principal falhar
                pos = requests.get(f"{DATA_API}/positions?user={wallet}&sizeThreshold=1", timeout=4).json()
                for p in pos: val += float(p.get('currentValue', 0))
            intel['portfolio'] = val
        except Exception:
            pass

        # C. RASTREAMENTO DE FONTE DE FUNDOS (PolygonScan)
        try:
            url = "https://api.polygonscan.com/api"
            params = {
                "module": "account", "action": "txlist", "address": wallet,
                "startblock": 0, "endblock": 99999999, "page": 1, "offset": 1,
                "sort": "asc", "apikey": POLYGONSCAN_API_KEY
            }
            time.sleep(0.2)  # Respeitando limite de taxa (rate limit)
            r = requests.get(url, params=params, timeout=5).json()

            if r['status'] == '1' and len(r['result']) > 0:
                first_tx = r['result'][0]
                if intel['created'] == 0:
                    intel['created'] = int(first_tx['timeStamp'])

                funder = first_tx['from'].lower()

                # Correspondência heurística contra hot wallets conhecidas
                if funder in KNOWN_WALLETS:
                    intel['source'] = KNOWN_WALLETS[funder]
                elif "binance" in str(first_tx).lower():
                    intel['source'] = "Binance"
                elif "coinbase" in str(first_tx).lower():
                    intel['source'] = "Coinbase"
                else:
                    intel['source'] = "Carteira Privada"
        except Exception:
            pass

        return intel

    def map_markets(self):
        """Faz cache dos mercados políticos ativos para otimizar buscas em tempo de execução."""
        print(">> [Sistema] Inicializando Mapa de Mercados...")
        try:
            params = {"limit": 5000, "active": "true", "closed": "false"}
            response = requests.get(f"{GAMMA_API}/events", params=params, timeout=15).json()

            for event in response:
                tags = [t.get('slug').lower() for t in event.get('tags', [])]
                if 'politics' in tags or 'us-election' in tags:
                    for market in event.get('markets', []):
                        c_id = market.get('conditionId')
                        if c_id:
                            self.market_cache[c_id] = {
                                "q": market.get('question'),
                                "c": event.get('slug'),
                                "url": f"https://polymarket.com/event/{event.get('slug')}"
                            }
                            self.politics_ids.add(c_id)
            print(f">> [Sistema] Monitorando {len(self.politics_ids)} mercados políticos.")
        except Exception:
            print("!! [Erro] Falha ao mapear mercados.")

    def save_whale(self, b, is_insider):
        """Persiste os dados da aposta na camada de banco de dados apropriada."""
        value = b['value']

        # --- CAMINHO 1: MODO INSIDER/FORENSE ---
        if is_insider:
            print(f">> 🐳 INSIDER DETECTADO (${value:,.0f}). Iniciando Análise Forense.")
            intel = self.get_wallet_intel(b['wallet'])

            try:
                conn = self.get_db_connection(DB_INSIDER)
                c = conn.cursor()
                c.execute(
                    '''INSERT OR IGNORE INTO intel_whales (address, funding_source, account_created_ts, portfolio_value) VALUES (?, ?, ?, ?)''',
                    (b['wallet'], intel['source'], intel['created'], intel['portfolio']))
                c.execute(
                    '''UPDATE intel_whales SET total_scanned_volume = total_scanned_volume + ?, last_active_ts = ?, portfolio_value = ? WHERE address = ?''',
                    (b['value'], b['last_ts'], intel['portfolio'], b['wallet']))
                c.execute(
                    '''INSERT INTO intel_bets (whale_address, timestamp, market_question, position, size_usd) VALUES (?, ?, ?, ?, ?)''',
                    (b['wallet'], b['last_ts'], b['question'], b['position'], b['value']))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"!! [Erro] Falha na gravação do DB Insider: {e}")

        else:
            # --- CAMINHO 2: MODO STREAM GERAL ---
            # Ingestão leve - Sem chamadas de API externas
            intel = {"source": "Varejo", "created": int(time.time()), "portfolio": 0}

        # --- PERSISTÊNCIA GLOBAL (Stream Visual) ---
        try:
            conn = self.get_db_connection(DB_MAIN)
            c = conn.cursor()
            c.execute(
                '''INSERT OR IGNORE INTO whales (address, first_seen, last_seen, funding_source) VALUES (?, ?, ?, ?)''',
                (b['wallet'], intel['created'], b['last_ts'], intel['source']))
            c.execute(
                '''UPDATE whales SET last_seen=?, total_volume=total_volume+?, funding_source=? WHERE address=?''',
                (b['last_ts'], b['value'], intel['source'], b['wallet']))
            c.execute(
                '''INSERT INTO bets (whale_address, timestamp, market_question, category, position, size_usd, bet_link) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (b['wallet'], b['last_ts'], b['question'], b['category'], b['position'], b['value'], b['link']))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def process_ladders(self):
        """Avalia os buckets de agregação contra janelas de tempo e limites de valor."""
        now = int(time.time())
        removals = []

        for key, b in self.ladder_buckets.items():
            if now - b['last_ts'] > LADDER_WINDOW:
                # Janela expirada. Verificar contra os limites (thresholds).
                if b['value'] >= INSIDER_TRIGGER:
                    self.save_whale(b, is_insider=True)
                elif b['value'] >= STREAM_MIN_SIZE:
                    self.save_whale(b, is_insider=False)
                removals.append(key)

        for k in removals:
            del self.ladder_buckets[k]

    def watch(self):
        """Loop principal de eventos para monitoramento do mercado em tempo real."""
        print(f">> MOTOR SENTINEL ONLINE (Taxa de Atualização: 15s)")
        print(f">> Limite Stream: >${STREAM_MIN_SIZE} | Limite Forense: >${INSIDER_MIN_SIZE}")

        self.last_seen_ts = int(time.time())

        while True:
            self.process_ladders()
            active = len(self.ladder_buckets)
            print(f"\rEscaneando... | Agregações Ativas: {active}   ", end="", flush=True)

            try:
                trades = requests.get(f"{DATA_API}/trades?limit=50", timeout=10).json()
                trades.reverse()  # Processar do mais antigo para o mais novo

                new_max_ts = self.last_seen_ts

                for t in trades:
                    ts = int(t['timestamp'])
                    if ts <= self.last_seen_ts: continue
                    if ts > new_max_ts: new_max_ts = ts

                    usd = float(t['size']) * float(t['price'])
                    if usd < STREAM_NOISE_FLOOR: continue

                    cid = t.get('conditionId')
                    if cid not in self.politics_ids: continue

                    wallet = t.get('proxyWallet') or t.get('taker')
                    side = f"{t['side']} {t['outcome']}"
                    key = f"{wallet}_{cid}_{side}"

                    # --- LÓGICA DE DUPLO PIPELINE ---

                    # 1. PIPELINE STREAM (Instantâneo > $20)
                    # Ingestão direta para feedback visual, ignorando a lógica de agregação
                    if usd >= STREAM_MIN_SIZE and usd < ACCUMULATION_FLOOR:
                        md = self.market_cache.get(cid, {})
                        temp_b = {
                            "wallet": wallet,
                            "question": md.get("q", "..."),
                            "category": md.get("c", "Politics"),
                            "link": md.get("url", "#"),
                            "position": side,
                            "value": usd,
                            "last_ts": ts
                        }
                        self.save_whale(temp_b, is_insider=False)
                        continue

                    # 2. PIPELINE INSIDER (Acumulação > $500)
                    # Agregação em bucket para detectar ordens fracionadas (split orders)
                    if usd >= ACCUMULATION_FLOOR:
                        if key not in self.ladder_buckets:
                            md = self.market_cache.get(cid, {})
                            self.ladder_buckets[key] = {
                                "wallet": wallet,
                                "question": md.get("q"),
                                "category": md.get("c"),
                                "link": md.get("url"),
                                "position": side,
                                "value": 0,
                                "last_ts": ts
                            }

                        b = self.ladder_buckets[key]
                        b['value'] += usd
                        b['last_ts'] = ts

                        # GATILHO DE LIMITE CRÍTICO
                        if b['value'] >= CRITICAL_TRIGGER:
                            self.save_whale(b, is_insider=True)
                            del self.ladder_buckets[key]

                self.last_seen_ts = new_max_ts
                time.sleep(15)

            except KeyboardInterrupt:
                print("\n>> Encerrando Motor Sentinel...")
                break
            except Exception as e:
                # Logar erro mas manter o motor rodando
                # print(f"Erro: {e}")
                time.sleep(15)


if __name__ == "__main__":
    bot = WhaleSentinel()
    bot.map_markets()
    bot.watch()