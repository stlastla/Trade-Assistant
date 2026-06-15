"""Fair Value Gap detection — pure functions, no I/O."""
from dataclasses import dataclass
from typing import List

import pandas as pd


@dataclass
class FVG:
    index: int          # position of the confirming candle (i)
    direction: str      # "bull" or "bear"
    bottom: float       # lower edge of the gap
    top: float          # upper edge of the gap
    time: pd.Timestamp  # open_time of the confirming candle


def find_fvgs(df: pd.DataFrame, direction: str) -> List[FVG]:
    """Return all 3-candle FVGs of the given direction in `df`.

    df must have columns: open_time, high, low (positional index 0..n-1).
    direction: "bull" -> low[i] > high[i-2]; "bear" -> high[i] < low[i-2].
    """
    if direction not in ("bull", "bear"):
        raise ValueError(f"direction must be 'bull' or 'bear', got {direction!r}")

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    times = df["open_time"].to_numpy()
    out: List[FVG] = []

    for i in range(2, len(df)):
        if direction == "bull" and lows[i] > highs[i - 2]:
            out.append(FVG(i, "bull", float(highs[i - 2]), float(lows[i]), pd.Timestamp(times[i])))
        elif direction == "bear" and highs[i] < lows[i - 2]:
            out.append(FVG(i, "bear", float(highs[i]), float(lows[i - 2]), pd.Timestamp(times[i])))
    return out
