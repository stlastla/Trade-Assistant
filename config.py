"""Shared configuration constants for the BTC Watcher."""

SYMBOL = "BTCUSDT"
INTERVALS = ("1w", "1d", "4h", "15m", "5m")
BINANCE_BASE = "https://api.binance.com/api/v3/klines"

# Earliest BTCUSDT data on Binance (2017-08-17) in ms.
START_MS = 1502928000000

# Where fetch_data caches full-history CSVs.
DATA_DIR = "data"
