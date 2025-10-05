import ccxt
import pandas as pd
import requests
import schedule
import time
import math
from datetime import datetime, timedelta
import threading

# ---------------- CONFIG ---------------- #
TELEGRAM_TOKEN = '8388160667:AAEDpYqtOVyjywdY4RVMmbPR3aVB6NKWmQo'  # 🔹 Replace
CHAT_ID = '704102822'           # 🔹 Replace

TIMEFRAME = '1h'
PERIOD = 10
MULTIPLIER = 2
TOP_N = 800
CHECK_INTERVAL = 3600       # seconds (1h)
BATCH_SLEEP = 0.12
HEARTBEAT_INTERVAL = 10 * 60   # 10 minutes
# ---------------------------------------- #

exchange = ccxt.binance({'enableRateLimit': True})

# Global state
bot_running = False
last_trends = {}
last_heartbeat = datetime.utcnow() - timedelta(seconds=HEARTBEAT_INTERVAL)

# Telegram messaging
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"[telegram error] {e}")

# ---------------- Supertrend functions ---------------- #
def fetch_ohlcv_df(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open','high','low','close','volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def calculate_atr_series(df):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=PERIOD, min_periods=PERIOD).mean()
    return atr

def calculate_supertrend_df(df):
    df = df.copy().reset_index(drop=True)
    atr = calculate_atr_series(df)
    hl2 = (df['high'] + df['low']) / 2
    upperband = hl2 + MULTIPLIER*atr
    lowerband = hl2 - MULTIPLIER*atr
    df['supertrend'] = 0.0
    for i in range(1, len(df)):
        if pd.isna(upperband.iat[i-1]):
            df.loc[i,'supertrend'] = df.loc[i-1,'supertrend']
            continue
        if df['close'].iat[i] > upperband.iat[i-1]:
            df.loc[i,'supertrend'] = 1.0
        elif df['close'].iat[i] < lowerband.iat[i-1]:
            df.loc[i,'supertrend'] = -1.0
        else:
            df.loc[i,'supertrend'] = df.loc[i-1,'supertrend']
    return df

# ---------------- Top pairs ---------------- #
def get_top_usdt_pairs(n=TOP_N):
    markets = exchange.load_markets()
    usdt_pairs = [s for s, m in markets.items() if s.endswith('/USDT') and m.get('active', True)]
    tickers = exchange.fetch_tickers(usdt_pairs)
    pair_vols = []
    for s in usdt_pairs:
        t = tickers.get(s)
        vol = float(t.get('quoteVolume', 0.0)) if t else 0.0
        pair_vols.append((s, vol))
    pair_vols.sort(key=lambda x:x[1], reverse=True)
    top_pairs = [p for p,_ in pair_vols][:n]
    return top_pairs

# ---------------- Monitoring ---------------- #
def initialize_trends(pairs):
    global last_trends
    print("Initializing trends...")
    for idx, s in enumerate(pairs,1):
        try:
            df = fetch_ohlcv_df(s)
            df = calculate_supertrend_df(df)
            trend = int(df['supertrend'].iloc[-2]) if len(df)>=3 else 0
            last_trends[s] = trend
        except:
            last_trends[s] = 0
        time.sleep(BATCH_SLEEP)

def monitor_top_pairs(pairs):
    global last_trends, last_heartbeat, bot_running
    while bot_running:
        for idx, s in enumerate(pairs,1):
            if not bot_running:
                return
            try:
                print(f"Processing ({idx}/{len(pairs)}): {s}", end='\r', flush=True)
                df = fetch_ohlcv_df(s)
                df = calculate_supertrend_df(df)
                if len(df)<3:
                    continue
                current_trend = int(df['supertrend'].iloc[-2])
                prev_trend = last_trends.get(s, current_trend)
                if current_trend != prev_trend:
                    last_trends[s] = current_trend
                    trend_str = 'GREEN' if current_trend==1 else 'RED' if current_trend==-1 else 'NEUTRAL'
                    msg = f"{s} Supertrend flipped to {trend_str}!"
                    send_telegram(msg)
                    print("\n"+msg)
                time.sleep(BATCH_SLEEP)
            except Exception as e:
                error_msg = f"[error] {s}: {e}"
                print("\n"+error_msg)
                send_telegram(error_msg)
        # Heartbeat every 10 min
        now = datetime.utcnow()
        if (now - last_heartbeat).total_seconds() >= HEARTBEAT_INTERVAL:
            last_heartbeat = now
            hb_msg = f"💓 Bot heartbeat — scanned {len(pairs)} pairs at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            print("\n"+hb_msg)
            send_telegram(hb_msg)
        time.sleep(CHECK_INTERVAL)

# ---------------- Telegram polling ---------------- #
OFFSET = 0
def telegram_polling():
    global OFFSET, bot_running
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={OFFSET}&timeout=20"
            r = requests.get(url, timeout=25).json()
            for result in r['result']:
                OFFSET = result['update_id'] + 1
                msg = result['message']['text'].lower()
                chat = result['message']['chat']['id']
                if msg == '/start' and not bot_running:
                    bot_running = True
                    send_telegram("🚀 Supertrend Alert Bot Started! Monitoring all USDT pairs...")
                    print("🚀 Bot Started")
                    pairs = get_top_usdt_pairs()
                    initialize_trends(pairs)
                    threading.Thread(target=monitor_top_pairs, args=(pairs,), daemon=True).start()
                elif msg == '/stop' and bot_running:
                    bot_running = False
                    send_telegram("🛑 Supertrend Alert Bot Stopped by user.")
                    print("🛑 Bot Stopped")
        except Exception as e:
            print(f"[telegram polling error]: {e}")
            time.sleep(5)

# ---------------- Main ---------------- #
if __name__ == "__main__":
    print("🤖 Telegram command-driven Supertrend Bot is running...")
    send_telegram("🤖 Bot is online. Use /start to begin monitoring, /stop to stop.")
    telegram_polling()
