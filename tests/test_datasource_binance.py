import pandas as pd
import datasource
from instruments import get_instrument


def test_fetch_recent_for_binance_dispatches_with_provider_symbol(monkeypatch):
    seen = {}

    def _fake(symbol, interval, limit):
        seen.update(symbol=symbol, interval=interval, limit=limit)
        return pd.DataFrame({"open_time": [], "open": [], "high": [], "low": [],
                             "close": [], "volume": [], "close_time": []})

    import fetch_data
    monkeypatch.setattr(fetch_data, "fetch_recent_symbol", _fake)
    btc = get_instrument("BTCUSDT")
    datasource.fetch_recent_for(btc, "15m", 200)
    assert seen == {"symbol": "BTCUSDT", "interval": "15m", "limit": 200}
