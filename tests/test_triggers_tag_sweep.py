import pandas as pd
from aoi import AOI
from triggers import tag_time, etf_sweep


def _m15(rows):  # rows: (open_iso, high, low, close)
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows], "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
    })


SUP = AOI("H4", "supply", 100.0, 112.0, "h4_swing_high")  # band [100,112]


def test_tag_time_when_high_enters_band():
    df = _m15([("2026-06-16T00:00Z", 95, 90, 93),
              ("2026-06-16T00:15Z", 104, 98, 101)])
    assert tag_time(SUP, df) == pd.Timestamp("2026-06-16T00:15Z")


def test_tag_time_none_when_untouched():
    df = _m15([("2026-06-16T00:00Z", 95, 90, 93)])
    assert tag_time(SUP, df) is None


def test_etf_sweep_finds_bearish_sweep_after_tag_near_aoi():
    df = _m15([("2026-06-16T00:00Z", 100, 96, 98),
               ("2026-06-16T00:15Z", 104, 99, 102),
               ("2026-06-16T00:30Z", 110, 103, 108),
               ("2026-06-16T00:45Z", 105, 100, 102),
               ("2026-06-16T01:00Z", 103, 99, 101),
               ("2026-06-16T01:15Z", 113, 106, 107)])
    after = pd.Timestamp("2026-06-16T00:00Z")
    t = etf_sweep(SUP, df, after, tol=5.0)
    assert t == pd.Timestamp("2026-06-16T01:15Z")


def test_etf_sweep_none_before_after_marker():
    df = _m15([("2026-06-16T00:00Z", 100, 96, 98),
               ("2026-06-16T00:15Z", 110, 99, 102),
               ("2026-06-16T00:30Z", 113, 104, 105)])
    after = pd.Timestamp("2026-06-16T05:00Z")
    assert etf_sweep(SUP, df, after, tol=5.0) is None
