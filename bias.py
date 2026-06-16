"""Per-timeframe bias: UP / DOWN / FLAT, from EMA-50 slope and price position.

FLAT when the EMA slope is within a small fractional threshold, or when price
position relative to the EMA disagrees with the slope. (An earlier version also
vetoed to FLAT on a contradicting structure break, but a *stale* break would
override an obvious EMA trend — e.g. price 6% below a falling EMA still reading
FLAT because of one old up-break — so the structure veto was dropped.) This
replaces the flat single-`Bias` for the scoring path; the existing watcher keeps
its own bias until Phase 2.
"""
import pandas as pd

from levels import ema


def compute_bias(df: pd.DataFrame, ema_period: int = 50,
                 flat_slope_pct: float = 0.0003) -> str:
    close = df["close"]
    e = ema(close, ema_period)
    ema_last = float(e.iloc[-1])
    if ema_last == 0:
        return "FLAT"
    window = max(1, min(len(e) - 1, ema_period // 2))
    slope = (ema_last - float(e.iloc[-1 - window])) / abs(ema_last)
    if abs(slope) < flat_slope_pct:
        return "FLAT"
    slope_dir = "up" if slope > 0 else "down"
    pos_dir = "up" if float(close.iloc[-1]) >= ema_last else "down"
    if pos_dir != slope_dir:
        return "FLAT"
    return "UP" if slope_dir == "up" else "DOWN"


def bias_map(weekly: pd.DataFrame, daily: pd.DataFrame, h4: pd.DataFrame, **kw) -> dict:
    """Per-TF bias map keyed 'W'/'D'/'H4'."""
    return {"W": compute_bias(weekly, **kw),
            "D": compute_bias(daily, **kw),
            "H4": compute_bias(h4, **kw)}
