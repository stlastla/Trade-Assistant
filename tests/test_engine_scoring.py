import pandas as pd
import engine
from aoi import AOI


def _frame(n, base, step):
    return pd.DataFrame({
        "open_time": pd.to_datetime("2026-01-01", utc=True) + pd.to_timedelta(range(n), unit="h"),
        "high": [base + step * i + 1 for i in range(n)],
        "low":  [base + step * i - 1 for i in range(n)],
        "close":[float(base + step * i) for i in range(n)],
        "close_time": pd.to_datetime("2026-01-01", utc=True) + pd.to_timedelta(range(1, n + 1), unit="h"),
    })


def test_score_pass_returns_scored_aois():
    weekly = _frame(60, 100, 1)
    daily = _frame(60, 100, 1)
    h4 = _frame(120, 100, 1)
    etf = _frame(120, 100, 1)
    now = daily["close_time"].iloc[-1]
    scored = engine.score_pass(weekly, daily, h4, etf, now, symbol="BTCUSDT")
    assert all(isinstance(a, AOI) for a in scored)
    assert all(a.label in ("A+", "valid", "weak", "no-trade") for a in scored)
    assert all(a.gate in ("pass", "no-trade") for a in scored)
