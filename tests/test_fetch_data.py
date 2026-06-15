# tests/test_fetch_data.py
import pandas as pd
from fetch_data import klines_to_df


def test_klines_to_df_parses_binance_rows():
    # Binance kline row format (12 fields); we use [0..5] + close_time[6].
    rows = [
        [1502928000000, "100.0", "110.0", "90.0", "105.0", "12.5",
         1502941199999, "0", 0, "0", "0", "0"],
        [1502942400000, "105.0", "120.0", "104.0", "118.0", "8.0",
         1502956799999, "0", 0, "0", "0", "0"],
    ]
    df = klines_to_df(rows)
    assert list(df.columns) == [
        "open_time", "open", "high", "low", "close", "volume", "close_time"
    ]
    assert df.loc[0, "open"] == 100.0
    assert df.loc[1, "high"] == 120.0
    assert str(df.loc[0, "open_time"].tz) == "UTC"
    assert df.loc[0, "open_time"] == pd.Timestamp("2017-08-17 00:00:00", tz="UTC")
    # numeric dtypes
    assert df["close"].dtype == float


def test_fetch_recent_builds_df_from_api(monkeypatch):
    import fetch_data

    sample = [
        [1700000000000, "100", "110", "90", "105", "12.5", 1700000899999],
        [1700000900000, "105", "120", "104", "118", "8.0", 1700001799999],
    ]

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return sample

    def _fake_get(url, params=None, timeout=None):
        assert params["symbol"] == "BTCUSDT"
        assert params["interval"] == "15m"
        assert params["limit"] == 2
        return _Resp()

    monkeypatch.setattr(fetch_data.requests, "get", _fake_get)
    df = fetch_data.fetch_recent("15m", limit=2)

    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume", "close_time"]
    assert len(df) == 2
    assert df["high"].iloc[1] == 120.0
    assert str(df["open_time"].dt.tz) == "UTC"


def test_cache_roundtrip_preserves_utc(tmp_path):
    from fetch_data import read_cached_csv
    rows = [
        [1502928000000, "100.0", "110.0", "90.0", "105.0", "12.5",
         1502941199999, "0", 0, "0", "0", "0"],
    ]
    df = klines_to_df(rows)
    path = tmp_path / "cache.csv"
    df.to_csv(path, index=False)
    reloaded = read_cached_csv(str(path))
    # both datetime columns must come back tz-aware UTC (close_time has microseconds)
    assert str(reloaded["open_time"].dtype) == "datetime64[ns, UTC]"
    assert str(reloaded["close_time"].dtype) == "datetime64[ns, UTC]"
    assert reloaded.loc[0, "open_time"] == df.loc[0, "open_time"]
    assert reloaded.loc[0, "close_time"] == df.loc[0, "close_time"]
    assert reloaded.loc[0, "open"] == 100.0
