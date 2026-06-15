import pandas as pd
import engine
from levels import Level


def _daily():
    rows = [(f"2026-05-{d:02d}", 100 + d, 90 + d, 95 + d) for d in range(1, 31)]
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows], "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "close_time": pd.to_datetime([r[0] for r in rows], utc=True) + pd.Timedelta(days=1),
    })


def _h4():
    n = 120
    return pd.DataFrame({
        "open_time": pd.to_datetime("2026-06-01", utc=True) + pd.to_timedelta(range(n), unit="h"),
        "high": [100 + (i % 7) for i in range(n)],
        "low": [90 + (i % 5) for i in range(n)],
        "close": [95 + (i % 6) for i in range(n)],
    })


def test_run_morning_pass_returns_levels_and_bias():
    now = pd.Timestamp("2026-06-06 06:00", tz="UTC")
    levels, zones, bias = engine.run_morning_pass(_daily(), _h4(), now)
    assert all(isinstance(l, Level) for l in levels)
    assert bias.h4_dir in ("up", "down")
    assert any(l.source in ("pdh", "pdl") for l in levels)
