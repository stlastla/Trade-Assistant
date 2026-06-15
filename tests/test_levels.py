import pytest
import pandas as pd
from levels import prior_day_levels, Level, build_levels, Bias, ema, h4_trend, momentum_14d, bias_snapshot, unfilled_fvgs


def _daily(rows):
    # rows: list of (open_iso, high, low, close)
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "close_time": pd.to_datetime([r[0] for r in rows], utc=True) + pd.Timedelta(days=1),
    })


def test_prior_day_levels_picks_last_closed_bar():
    df = _daily([
        ("2026-06-12", 100, 90, 95),
        ("2026-06-13", 110, 92, 108),   # yesterday (closed)
        ("2026-06-14", 109, 100, 104),  # today, still open
    ])
    now = pd.Timestamp("2026-06-14 09:00", tz="UTC")
    pdh, pdl = prior_day_levels(df, now)
    assert pdh == 110.0
    assert pdl == 92.0


def test_level_is_a_simple_record():
    lvl = Level(source="pdh", price=110.0, side="high")
    assert (lvl.source, lvl.price, lvl.side) == ("pdh", 110.0, "high")


def test_build_levels_collects_swings_and_prior_day():
    # H4 with a clear swing high at idx 2 (high=5) and swing low at idx 4 (low=0)
    h4 = pd.DataFrame({
        "high": [1, 2, 5, 2, 1, 3, 1, 2],
        "low":  [1, 0, 3, 2, 0, 2, 1, 1],
        "close":[1, 2, 4, 2, 1, 3, 1, 2],
    })
    daily = _daily([
        ("2026-06-12", 100, 90, 95),
        ("2026-06-13", 110, 92, 108),
        ("2026-06-14", 109, 100, 104),
    ])
    now = pd.Timestamp("2026-06-14 09:00", tz="UTC")

    levels = build_levels(daily, h4, now, daily_n=5, h4_n=5, left=2, right=2)
    sources = {l.source for l in levels}
    assert "pdh" in sources and "pdl" in sources
    assert "h4_swing_high" in sources and "h4_swing_low" in sources
    prices = {(l.source, l.price) for l in levels}
    assert ("pdh", 110.0) in prices and ("pdl", 92.0) in prices
    assert all(l.side in ("high", "low") for l in levels)


def test_ema_matches_pandas_ewm():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = ema(s, 3)
    assert abs(out.iloc[-1] - s.ewm(span=3, adjust=False).mean().iloc[-1]) < 1e-9


def test_h4_trend_up_when_close_above_ema():
    h4 = pd.DataFrame({"close": [float(x) for x in range(1, 80)]})
    assert h4_trend(h4, period=50) == "up"


def test_momentum_14d_sign():
    daily = pd.DataFrame({"close": [100.0] * 14 + [120.0]})
    assert momentum_14d(daily) == "up"
    daily_dn = pd.DataFrame({"close": [120.0] * 14 + [100.0]})
    assert momentum_14d(daily_dn) == "down"


def test_bias_alignment_gate_uses_h4_and_momentum():
    bull = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")
    assert bull.aligned("up") is True
    assert bull.aligned("down") is False

    mixed = Bias(daily_dir="up", h4_dir="up", mom14_dir="down")
    assert mixed.aligned("up") is False


def test_unfilled_fvgs_excludes_entered_gaps():
    df = pd.DataFrame({
        "open_time": pd.to_datetime(
            ["2026-06-14T00:00Z", "2026-06-14T04:00Z", "2026-06-14T08:00Z",
             "2026-06-14T12:00Z", "2026-06-14T16:00Z"], utc=True),
        "high": [10, 12, 20, 19, 16],
        "low":  [8, 11, 15, 14, 9],
        "close":[9, 11, 18, 16, 12],
    })
    out = unfilled_fvgs(df, "bull")
    assert out == []


def test_prior_day_levels_raises_when_no_closed_bar():
    df = _daily([("2026-06-14", 109, 100, 104)])  # only today, not yet closed
    now = pd.Timestamp("2026-06-14 09:00", tz="UTC")
    with pytest.raises(ValueError):
        prior_day_levels(df, now)


def test_momentum_14d_none_on_short_history():
    daily = pd.DataFrame({"close": [100.0, 101.0, 102.0]})  # fewer than 14+1 bars
    assert momentum_14d(daily) == "none"


def test_unfilled_fvgs_keeps_open_gap():
    # bull FVG forms at i=2 (low[2]=15 > high[0]=10); gap is bottom=10, top=15.
    # high[1]=20 prevents a second FVG at i=3 (low[3]=18 is NOT > high[1]=20).
    # Later lows (18, 20) stay strictly above top=15, so the gap is never entered.
    df = pd.DataFrame({
        "open_time": pd.to_datetime(
            ["2026-06-14T00:00Z", "2026-06-14T04:00Z", "2026-06-14T08:00Z",
             "2026-06-14T12:00Z", "2026-06-14T16:00Z"], utc=True),
        "high": [10, 20, 22, 24, 26],
        "low":  [8, 11, 15, 18, 20],   # later lows stay > 15 (above the gap top)
        "close":[9, 18, 20, 22, 24],
    })
    out = unfilled_fvgs(df, "bull")
    assert len(out) == 1
    assert out[0].direction == "bull"
