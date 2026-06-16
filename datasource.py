"""Data-source abstraction: one interface, per-provider adapters. The engine consumes
the same OHLCV frame shape regardless of where candles come from."""
import fetch_data
from instruments import Instrument


class BinanceSource:
    """Crypto candles via Binance (wraps fetch_data). Identity interval map."""
    INTERVAL_MAP = {"1w": "1w", "1d": "1d", "4h": "4h", "15m": "15m", "5m": "5m"}

    def fetch_recent(self, provider_symbol, our_interval, limit):
        return fetch_data.fetch_recent_symbol(
            provider_symbol, self.INTERVAL_MAP[our_interval], limit)


SOURCES = {"binance": BinanceSource()}


def fetch_recent_for(inst: Instrument, our_interval: str, limit: int = 300):
    """Fetch recent candles for `inst` from its configured source."""
    return SOURCES[inst.source].fetch_recent(inst.provider_symbol, our_interval, limit)
