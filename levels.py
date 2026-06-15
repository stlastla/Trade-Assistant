"""Top-down level marking + bias snapshot. Pure functions over kline DataFrames."""
from dataclasses import dataclass
from typing import List

import pandas as pd

from liquidity import swing_points
from fvg import find_fvgs, FVG
from structure import detect_structure_breaks


def prior_day_levels(daily: pd.DataFrame, now: pd.Timestamp) -> tuple:
    """(PDH, PDL): high/low of the most recent Daily candle that closed before `now`.

    Raises ValueError if no daily candle has closed on/before `now`.
    """
    closed = daily[daily["close_time"] <= now]
    if closed.empty:
        raise ValueError(f"no closed daily candle on/before {now}")
    prev = closed.iloc[-1]
    return float(prev["high"]), float(prev["low"])


@dataclass
class Level:
    source: str   # 'daily_swing_high'|'daily_swing_low'|'h4_swing_high'|'h4_swing_low'|'pdh'|'pdl'
    price: float
    side: str     # 'high' = sell-side liquidity above; 'low' = buy-side below


def _swing_levels(df: pd.DataFrame, prefix: str, n: int, left: int, right: int) -> List[Level]:
    sh, sl = swing_points(df, left, right)
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    out: List[Level] = []
    for i in sh[-n:]:
        out.append(Level(f"{prefix}_swing_high", float(hi[i]), "high"))
    for i in sl[-n:]:
        out.append(Level(f"{prefix}_swing_low", float(lo[i]), "low"))
    return out


def build_levels(daily: pd.DataFrame, h4: pd.DataFrame, now: pd.Timestamp,
                 daily_n: int, h4_n: int, left: int, right: int) -> List[Level]:
    """The marked level set: recent Daily + H4 confirmed swings, plus PDH/PDL."""
    levels: List[Level] = []
    levels += _swing_levels(daily, "daily", daily_n, left, right)
    levels += _swing_levels(h4, "h4", h4_n, left, right)
    pdh, pdl = prior_day_levels(daily, now)
    levels.append(Level("pdh", pdh, "high"))
    levels.append(Level("pdl", pdl, "low"))
    return levels


@dataclass
class Bias:
    daily_dir: str   # 'up'|'down'|'none'  (context only)
    h4_dir: str      # 'up'|'down'
    mom14_dir: str   # 'up'|'down'

    def aligned(self, direction: str) -> bool:
        """True if the proven HTF edge (H4 trend + 14d momentum) agrees with `direction`.
        `direction` is 'up' for a bullish sweep (of a low) or 'down' for bearish."""
        return self.h4_dir == direction and self.mom14_dir == direction


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def h4_trend(h4: pd.DataFrame, period: int = 50) -> str:
    e = ema(h4["close"], period)
    return "up" if h4["close"].iloc[-1] >= e.iloc[-1] else "down"


def momentum_14d(daily: pd.DataFrame, lookback: int = 14) -> str:
    c = daily["close"].to_numpy()
    if len(c) <= lookback:
        return "none"
    return "up" if c[-1] >= c[-1 - lookback] else "down"


def _daily_dir(daily: pd.DataFrame, left: int, right: int) -> str:
    breaks = detect_structure_breaks(daily, left, right)
    if not breaks:
        return "none"
    return "up" if breaks[-1]["direction"] == "up" else "down"


def bias_snapshot(daily: pd.DataFrame, h4: pd.DataFrame, left: int, right: int,
                  ema_period: int = 50, mom_lookback: int = 14) -> Bias:
    return Bias(
        daily_dir=_daily_dir(daily, left, right),
        h4_dir=h4_trend(h4, ema_period),
        mom14_dir=momentum_14d(daily, mom_lookback),
    )


def unfilled_fvgs(df: pd.DataFrame, direction: str) -> List[FVG]:
    """FVGs of `direction` that no later bar has traded back into (gap still open)."""
    fvgs = find_fvgs(df, direction)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    out: List[FVG] = []
    for f in fvgs:
        entered = any(
            highs[j] >= f.bottom and lows[j] <= f.top
            for j in range(f.index + 1, len(df))
        )
        if not entered:
            out.append(f)
    return out
