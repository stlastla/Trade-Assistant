"""Download and cache Binance BTCUSDT klines to CSV."""
import os
import time
from typing import List

import pandas as pd
import requests

import config

_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def klines_to_df(rows: List[list]) -> pd.DataFrame:
    """Convert raw Binance kline rows into a typed DataFrame."""
    df = pd.DataFrame(
        {
            "open_time": pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
            "open": [float(r[1]) for r in rows],
            "high": [float(r[2]) for r in rows],
            "low": [float(r[3]) for r in rows],
            "close": [float(r[4]) for r in rows],
            "volume": [float(r[5]) for r in rows],
            "close_time": pd.to_datetime([r[6] for r in rows], unit="ms", utc=True),
        }
    )
    return df[_COLS]


def read_cached_csv(path: str) -> pd.DataFrame:
    """Load a cached kline CSV, forcing tz-aware UTC datetime columns.

    pandas read_csv parse_dates does not reliably parse the microsecond+tz
    close_time format, so parse both time columns explicitly.
    """
    df = pd.read_csv(path)
    df["open_time"] = pd.to_datetime(df["open_time"], format="ISO8601", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], format="ISO8601", utc=True)
    return df


def _csv_path(interval: str) -> str:
    return os.path.join(config.DATA_DIR, f"{config.SYMBOL.lower()}_{interval}.csv")


def download(interval: str, force: bool = False) -> pd.DataFrame:
    """Download full history for `interval`, caching to CSV.

    Returns the loaded DataFrame. If the cache exists and force is False,
    loads from disk instead of hitting the network.
    """
    path = _csv_path(interval)
    if os.path.exists(path) and not force:
        return read_cached_csv(path)

    os.makedirs(config.DATA_DIR, exist_ok=True)
    all_rows: List[list] = []
    start = config.START_MS
    while True:
        resp = requests.get(
            config.BINANCE_BASE,
            params={
                "symbol": config.SYMBOL,
                "interval": interval,
                "startTime": start,
                "limit": 1000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_rows.extend(batch)
        last_open = batch[-1][0]
        if len(batch) < 1000:
            break
        start = last_open + 1
        time.sleep(0.25)  # be polite to the API

    df = klines_to_df(all_rows)
    df.to_csv(path, index=False)
    print(f"{interval}: {len(df)} candles -> {path}")
    return df


def fetch_recent_symbol(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    """Most recent `limit` Binance klines for an arbitrary symbol (no caching)."""
    resp = requests.get(
        config.BINANCE_BASE,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return klines_to_df(resp.json())


def fetch_recent(interval: str, limit: int = 300) -> pd.DataFrame:
    """Most recent `limit` klines for `config.SYMBOL` (back-compat wrapper)."""
    return fetch_recent_symbol(config.SYMBOL, interval, limit)
