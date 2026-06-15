import pandas as pd
from liquidity import swing_points, detect_sweeps, reaction_from_level, near_band


def test_swing_points():
    df = pd.DataFrame({
        'high': [1, 2, 5, 2, 1, 3, 1],
        'low':  [1, 0, 3, 2, 0, 2, 1],
    })
    sh, sl = swing_points(df, left=2, right=2)
    assert sh == [2]   # high=5 strictly highest 2 bars each side
    assert sl == [4]   # low=0 strictly lowest 2 bars each side


def test_detect_bearish_sweep():
    # swing high at index 2 (high=5); bar 5 spikes above (6) then closes back below (4).
    df = pd.DataFrame({
        'high':  [1, 2, 5, 2, 1, 6, 1],
        'low':   [1, 0, 3, 2, 0, 2, 0],
        'close': [1, 2, 4, 2, 1, 4, 1],
    })
    sw = detect_sweeps(df, left=2, right=2)
    assert len(sw) == 1
    e = sw[0]
    assert e['index'] == 5 and e['direction'] == 'bearish'
    assert e['level'] == 5 and e['swing_index'] == 2


def test_detect_bullish_sweep():
    # swing low at index 2 (low=0); bar 5 spikes below (-1) then closes back above (2).
    df = pd.DataFrame({
        'high':  [5, 4, 3, 4, 5, 3, 5],
        'low':   [4, 3, 0, 2, 3, -1, 3],
        'close': [4, 3, 1, 3, 4, 2, 4],
    })
    sw = detect_sweeps(df, left=2, right=2)
    assert len(sw) == 1
    e = sw[0]
    assert e['index'] == 5 and e['direction'] == 'bullish'
    assert e['level'] == 0 and e['swing_index'] == 2


def test_no_sweep_when_no_rejection():
    # bar 5 spikes above the swing high (6) AND closes above it (7) -> continuation, not a sweep.
    df = pd.DataFrame({
        'high':  [1, 2, 5, 2, 1, 6, 1],
        'low':   [1, 0, 3, 2, 0, 2, 0],
        'close': [1, 2, 4, 2, 1, 7, 1],
    })
    assert detect_sweeps(df, left=2, right=2) == []


def test_reaction_from_level_resistance_bounce():
    # level 100, atr 2, thresh 1 -> bounce(=down) if low<=98 before high>=102
    df = pd.DataFrame({'high': [100, 100, 100], 'low': [99, 97, 97], 'close': [99, 98, 98]})
    a = pd.Series([2.0, 2.0, 2.0])
    assert reaction_from_level(df, 0, 100.0, 'resistance', a, horizon=5) == 'bounce'


def test_reaction_from_level_support_break():
    df = pd.DataFrame({'high': [100, 101, 101], 'low': [99, 97, 97], 'close': [100, 98, 98]})
    a = pd.Series([2.0, 2.0, 2.0])
    assert reaction_from_level(df, 0, 100.0, 'support', a, horizon=5) == 'break'


def test_near_band():
    df = pd.DataFrame({'up1': [110.0], 'dn1': [90.0]})
    a = pd.Series([4.0])
    # extreme 109 within 0.5*ATR(=2) of up1(110) -> 'up1'; extreme 105 not within 2 of either -> None
    assert near_band(df, 0, ['up1', 'dn1'], a, extreme=109.0, tol_atr=0.5) == 'up1'
    assert near_band(df, 0, ['up1', 'dn1'], a, extreme=105.0, tol_atr=0.5) is None
