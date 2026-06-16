"""Data-source abstraction: one interface, per-provider adapters. The engine consumes
the same OHLCV frame shape regardless of where candles come from."""
import os

import pandas as pd
import requests

import fetch_data
from instruments import Instrument


class BinanceSource:
    """Crypto candles via Binance (wraps fetch_data). Identity interval map."""
    INTERVAL_MAP = {"1w": "1w", "1d": "1d", "4h": "4h", "15m": "15m", "5m": "5m"}

    def fetch_recent(self, provider_symbol, our_interval, limit):
        return fetch_data.fetch_recent_symbol(
            provider_symbol, self.INTERVAL_MAP[our_interval], limit)


TWELVEDATA_BASE = "https://api.twelvedata.com/time_series"


def _keyring_get():
    """Read the Twelve Data key from the macOS Keychain, or None if unavailable."""
    try:
        import keyring
        return keyring.get_password("trade-assistant", "twelvedata")
    except Exception:
        return None


class TwelveDataSource:
    """Forex/commodity candles via Twelve Data, normalized to the Binance frame shape."""
    INTERVAL_MAP = {"1w": "1week", "1d": "1day", "4h": "4h", "15m": "15min", "5m": "5min"}
    _DURATION = {"1w": pd.Timedelta("7D"), "1d": pd.Timedelta("1D"),
                 "4h": pd.Timedelta("4h"), "15m": pd.Timedelta("15min"),
                 "5m": pd.Timedelta("5min")}

    def _api_key(self):
        key = _keyring_get()
        if key:
            return key
        key = os.environ.get("TWELVEDATA_API_KEY")
        if key:
            return key
        raise RuntimeError(
            "No Twelve Data API key. Run set_api_key.py to store it in the Keychain, "
            "or set the TWELVEDATA_API_KEY env var.")

    def fetch_recent(self, provider_symbol, our_interval, limit):
        resp = requests.get(TWELVEDATA_BASE, params={
            "symbol": provider_symbol,
            "interval": self.INTERVAL_MAP[our_interval],
            "outputsize": limit,
            "order": "ASC",
            "timezone": "UTC",
            "apikey": self._api_key(),
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"Twelve Data error for {provider_symbol}: {data.get('message')}")
        return self._normalize(data["values"], our_interval)

    def _normalize(self, values, our_interval):
        open_time = pd.to_datetime([v["datetime"] for v in values], utc=True)
        df = pd.DataFrame({
            "open_time": open_time,
            "open": [float(v["open"]) for v in values],
            "high": [float(v["high"]) for v in values],
            "low": [float(v["low"]) for v in values],
            "close": [float(v["close"]) for v in values],
            "volume": [float(v.get("volume", 0) or 0) for v in values],
            "close_time": open_time + self._DURATION[our_interval],
        })
        return df


SOURCES = {"binance": BinanceSource(), "twelvedata": TwelveDataSource()}


def fetch_recent_for(inst: Instrument, our_interval: str, limit: int = 300):
    """Fetch recent candles for `inst` from its configured source."""
    return SOURCES[inst.source].fetch_recent(inst.provider_symbol, our_interval, limit)
