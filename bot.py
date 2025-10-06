import ccxt
import pandas as pd
import requests
import schedule
import time
import signal
import sys

# ---------------- CONFIG ---------------- #
TELEGRAM_TOKEN = 'YOUR_BOT_TOKEN'
CHAT_ID = 'YOUR_CHAT_ID'
TIMEFRAME = '1h'
PERIOD = 10
MULTIPLIER = 2
CHECK_INTERVAL = 60  # seconds
# ---------------------------------------- #

# Initialize Binance API
exchange = ccxt.binance()

# Telegram messaging function
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
    try:
        requests.get(url)
    except:
        pass

# Function to run when script is terminated
def exit_handler(signum=None, frame=None):
    send_telegram("⚠️ Supertrend Alert Bot terminated unexpectedly!")
    sys.exit(0)

# Register termination signals
signal.signal(signal.SIGINT, exit_handler)
signal.signal(signal.SIGTERM, exit_handler)

# Fetch active USDT pairs
def get_active_pairs():
    markets = exchange.load_markets()
    return [symbol for symbol in markets if symbol.endswith('/USDT') and markets[symbol]['active']]

# Fetch OHLCV data
def fetch_data(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# Manual ATR calculation
def calculate_atr(df):
    df['H-L'] = df['high'] - df['low']
    df['H-Cp'] = abs(df['high'] - df['close'].shift(1))
    df['L-Cp'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H-L','H-Cp','L-Cp']].max(axis=1)
    atr = df['TR'].rolling(PERIOD).mean()
    return atr

# Supertrend calculation with .loc to avoid pandas warnings
def calculate_supertrend(df):
    atr = calculate_atr(df)
    hl2 = (df['high'] + df['low']) / 2
    upperband = hl2 + MULTIPLIER * atr
    lowerband = hl2 - MULTIPLIER * atr

    df['supertrend'] = 0.0
    for i in range(1, len(df)):
        if df['close'][i] > upperband[i-1]:
            df.loc[i, 'supertrend'] = 1
        elif df['close'][i] < lowerband[i-1]:
            df.loc[i, 'supertrend'] = -1
        else:
            df.loc[i, 'supertrend'] = df['supertrend'][i-1]
    return df

# Monitor trends and send alerts
def monitor_trends():
    active_pairs = get_active_pairs()
    for pair in active_pairs:
        try:
            print(f"Processing: {pair}")  # 🔹 Terminal output
            df = fetch_data(pair)
            df = calculate_supertrend(df)
            # Use only fully closed candle for decision (Option A)
            current_trend = df['supertrend'].iloc[-2]  # last confirmed candle
            previous_trend = df['supertrend'].iloc[-3]
            if current_trend != previous_trend:
                trend = 'GREEN' if current_trend == 1 else 'RED'
                send_telegram(f"{pair} Supertrend flipped to {trend}!")
                print(f"{pair} Supertrend flipped to {trend}!")
        except Exception as e:
            print(f"Error processing {pair}: {e}")

# Send initial startup message
send_telegram("🚀 Supertrend Alert Bot Started! Monitoring all USDT pairs...")

# Schedule monitoring
schedule.every(CHECK_INTERVAL).seconds.do(monitor_trends)

# Run the bot with crash handling
try:
    print("Monitoring active USDT pairs for Supertrend flips...")
    while True:
        schedule.run_pending()
        time.sleep(1)
except Exception as e:
    send_telegram(f"⚠️ Supertrend Alert Bot crashed! Error: {e}")
