import pandas as pd
import pytest
import datasource


SAMPLE = {
    "values": [
        {"datetime": "2026-06-16 09:30:00", "open": "2300.0", "high": "2305.0",
         "low": "2299.0", "close": "2304.0", "volume": "10"},
        {"datetime": "2026-06-16 09:45:00", "open": "2304.0", "high": "2306.0",
         "low": "2301.0", "close": "2302.0", "volume": "8"},
    ],
    "status": "ok",
}


def _src(monkeypatch, payload=SAMPLE):
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return payload
    captured = {}
    def _fake_get(url, params=None, timeout=None):
        captured.update(params); captured["url"] = url
        return _Resp()
    monkeypatch.setattr(datasource.requests, "get", _fake_get)
    src = datasource.TwelveDataSource()
    monkeypatch.setattr(src, "_api_key", lambda: "KEY")
    return src, captured


def test_normalizes_and_maps_interval_symbol(monkeypatch):
    src, captured = _src(monkeypatch)
    df = src.fetch_recent("XAU/USD", "15m", 2)
    assert captured["symbol"] == "XAU/USD" and captured["interval"] == "15min"
    assert captured["order"] == "ASC" and captured["outputsize"] == 2
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume", "close_time"]
    assert str(df["open_time"].dt.tz) == "UTC"
    assert df["high"].iloc[0] == 2305.0
    assert (df["close_time"].iloc[0] - df["open_time"].iloc[0]) == pd.Timedelta("15min")


def test_status_error_raises(monkeypatch):
    src, _ = _src(monkeypatch, {"status": "error", "message": "bad symbol"})
    with pytest.raises(RuntimeError):
        src.fetch_recent("XAU/USD", "15m", 2)


def test_api_key_keychain_then_env_then_error(monkeypatch):
    src = datasource.TwelveDataSource()
    monkeypatch.setattr(datasource, "_keyring_get", lambda: "FROM_KC")
    assert src._api_key() == "FROM_KC"
    monkeypatch.setattr(datasource, "_keyring_get", lambda: None)
    monkeypatch.setenv("TWELVEDATA_API_KEY", "FROM_ENV")
    assert src._api_key() == "FROM_ENV"
    monkeypatch.setattr(datasource, "_keyring_get", lambda: None)
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        src._api_key()
