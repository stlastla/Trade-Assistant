# tests/test_fvg.py
import pandas as pd
from fvg import find_fvgs, FVG


def _df(rows):
    # rows: list of (high, low). open/close/volume unused by detection.
    return pd.DataFrame(
        {
            "open_time": pd.to_datetime(range(len(rows)), unit="h", utc=True),
            "high": [r[0] for r in rows],
            "low": [r[1] for r in rows],
        }
    )


def test_detects_single_bullish_fvg():
    # candle0 high=10; candle2 low=11 > 10 -> bullish gap [10, 11] at i=2
    df = _df([(10, 8), (12, 9), (13, 11)])
    fvgs = find_fvgs(df, "bull")
    assert len(fvgs) == 1
    f = fvgs[0]
    assert isinstance(f, FVG)
    assert f.index == 2
    assert f.direction == "bull"
    assert f.bottom == 10
    assert f.top == 11


def test_detects_single_bearish_fvg():
    # candle0 low=20; candle2 high=18 < 20 -> bearish gap [18, 20] at i=2
    df = _df([(22, 20), (19, 16), (18, 14)])
    fvgs = find_fvgs(df, "bear")
    assert len(fvgs) == 1
    f = fvgs[0]
    assert f.index == 2
    assert f.direction == "bear"
    assert f.bottom == 18
    assert f.top == 20


def test_no_fvg_when_no_gap():
    df = _df([(10, 8), (11, 9), (10, 9)])  # low[2]=9 not > high[0]=10
    assert find_fvgs(df, "bull") == []


def test_bullish_detector_ignores_bearish_gaps():
    df = _df([(22, 20), (19, 16), (18, 14)])  # this is a bearish gap
    assert find_fvgs(df, "bull") == []


def test_carries_confirmation_time():
    df = _df([(10, 8), (12, 9), (13, 11)])
    f = find_fvgs(df, "bull")[0]
    assert f.time == df.loc[2, "open_time"]


def test_too_short_returns_empty():
    for n in (0, 1, 2):
        assert find_fvgs(_df([(10, 8)] * n), "bull") == []


def test_detects_multiple_bullish_fvgs():
    # gap at i=2 (low 11 > high 10) and again at i=4 (low 14 > high 13)
    df = _df([(10, 8), (12, 9), (13, 11), (14, 10), (16, 14)])
    fvgs = find_fvgs(df, "bull")
    assert len(fvgs) == 2
    assert fvgs[0].index == 2
    assert fvgs[1].index == 4
