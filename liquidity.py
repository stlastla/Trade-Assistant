"""Liquidity-grab (stop-hunt) detection + reaction helpers. Pure, descriptive."""
from typing import Dict, List, Optional, Tuple

import pandas as pd


def swing_points(df: pd.DataFrame, left: int = 2, right: int = 2) -> Tuple[List[int], List[int]]:
    """Fractal swing highs/lows. A swing high at i: high[i] strictly greater than every
    high in the `left` bars before and `right` bars after. Mirror for swing lows.
    Returns (swing_high_indices, swing_low_indices). Confirmed only `right` bars later."""
    hi = df['high'].to_numpy()
    lo = df['low'].to_numpy()
    n = len(df)
    sh, sl = [], []
    for i in range(left, n - right):
        if hi[i] > hi[i - left:i].max() and hi[i] > hi[i + 1:i + 1 + right].max():
            sh.append(i)
        if lo[i] < lo[i - left:i].min() and lo[i] < lo[i + 1:i + 1 + right].min():
            sl.append(i)
    return sh, sl


def detect_sweeps(df: pd.DataFrame, left: int = 2, right: int = 2) -> List[Dict]:
    """Detect single-bar liquidity sweeps of the most recent CONFIRMED swing level.

    bearish: bar high > recent swing-high level AND bar close < that level (swept buy-stops
             above a high, then rejected back below). Mirror for bullish on a swing low.
    A swing is 'confirmed' only `right` bars after it forms, so only swings whose confirmation
    precedes the current bar are eligible (no look-ahead). One event per bar (bearish checked
    first). Returns list of {index, direction, level, swing_index}.
    """
    hi = df['high'].to_numpy()
    lo = df['low'].to_numpy()
    cl = df['close'].to_numpy()
    sh, sl = swing_points(df, left, right)
    out: List[Dict] = []
    last_sh: Optional[int] = None
    last_sl: Optional[int] = None
    pi_h = pi_l = 0
    for t in range(len(df)):
        while pi_h < len(sh) and sh[pi_h] + right < t:
            last_sh = sh[pi_h]; pi_h += 1
        while pi_l < len(sl) and sl[pi_l] + right < t:
            last_sl = sl[pi_l]; pi_l += 1
        if last_sh is not None and hi[t] > hi[last_sh] and cl[t] < hi[last_sh]:
            out.append({'index': t, 'direction': 'bearish',
                        'level': float(hi[last_sh]), 'swing_index': last_sh})
            continue
        if last_sl is not None and lo[t] < lo[last_sl] and cl[t] > lo[last_sl]:
            out.append({'index': t, 'direction': 'bullish',
                        'level': float(lo[last_sl]), 'swing_index': last_sl})
    return out


def reaction_from_level(df: pd.DataFrame, i: int, level: float, side: str,
                        atr_series: pd.Series, horizon: int, thresh_atr: float = 1.0) -> str:
    """Forward reaction relative to a scalar price level (bars i+1..i+horizon).
    side='support': bounce = price gets thresh*ATR ABOVE level before thresh*ATR below.
    side='resistance': bounce = thresh*ATR BELOW before ABOVE. Else 'break'/'none'."""
    a = atr_series.to_numpy()[i]
    if a != a or a == 0:
        return 'none'
    hi = df['high'].to_numpy()
    lo = df['low'].to_numpy()
    up = level + thresh_atr * a
    dn = level - thresh_atr * a
    end = min(len(df), i + 1 + horizon)
    for j in range(i + 1, end):
        up_hit = hi[j] >= up
        dn_hit = lo[j] <= dn
        if side == 'support':
            if up_hit:
                return 'bounce'
            if dn_hit:
                return 'break'
        else:
            if dn_hit:
                return 'bounce'
            if up_hit:
                return 'break'
    return 'none'


def near_band(df: pd.DataFrame, i: int, band_cols: List[str], atr_series: pd.Series,
              extreme: float, tol_atr: float = 0.5) -> Optional[str]:
    """Return the band column whose level at bar i is within tol_atr*ATR of `extreme`
    (nearest if several), else None."""
    a = atr_series.to_numpy()[i]
    if a != a or a == 0:
        return None
    best = None
    best_d = tol_atr * a
    for c in band_cols:
        lvl = df[c].to_numpy()[i]
        d = abs(extreme - lvl)
        if d <= best_d:
            best_d = d
            best = c
    return best
