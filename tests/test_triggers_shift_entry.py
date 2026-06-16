import pandas as pd
from aoi import AOI
from triggers import etf_shift, first_opposing_candle


def _m5(rows):  # rows: (open_iso, open, high, low, close)
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "open": [r[1] for r in rows], "high": [r[2] for r in rows],
        "low": [r[3] for r in rows], "close": [r[4] for r in rows],
    })


SUP = AOI("H4", "supply", 100.0, 112.0, "h4_swing_high")


def test_etf_shift_finds_down_break_after_marker():
    # Forms a confirmed fractal swing low at idx3 (low=100, lower than the 2 bars each
    # side), then a later candle CLOSES below it (96 < 100) -> a downward MSS/CHoCH.
    df = _m5([("2026-06-16T00:00Z", 110, 112, 108, 109),
              ("2026-06-16T00:05Z", 109, 110, 106, 107),
              ("2026-06-16T00:10Z", 107, 108, 104, 105),
              ("2026-06-16T00:15Z", 105, 106, 100, 103),   # swing low (100)
              ("2026-06-16T00:20Z", 103, 108, 102, 107),
              ("2026-06-16T00:25Z", 107, 110, 105, 109),   # confirms the swing low
              ("2026-06-16T00:30Z", 109, 110, 101, 103),
              ("2026-06-16T00:35Z", 103, 104, 95, 96)])    # close 96 < 100 -> down break
    after = pd.Timestamp("2026-06-16T00:00Z")
    t = etf_shift(SUP, df, after)
    assert t is not None and t > after


def test_etf_shift_none_when_no_down_break():
    df = _m5([("2026-06-16T00:00Z", 100, 110, 99, 108),
              ("2026-06-16T00:05Z", 108, 120, 107, 118),
              ("2026-06-16T00:10Z", 118, 125, 116, 124)])
    assert etf_shift(SUP, df, pd.Timestamp("2026-06-16T00:00Z")) is None


def test_first_opposing_candle_is_first_bullish_for_short():
    df = _m5([("2026-06-16T00:00Z", 110, 111, 104, 105),
              ("2026-06-16T00:05Z", 105, 106, 100, 101),
              ("2026-06-16T00:10Z", 101, 107, 100, 106),
              ("2026-06-16T00:15Z", 106, 108, 103, 104)])
    after = pd.Timestamp("2026-06-15T00:00Z")
    c = first_opposing_candle(SUP, df, after)
    assert c["time"] == pd.Timestamp("2026-06-16T00:10Z")
    assert c["low"] == 100.0 and c["high"] == 107.0
