"""Detectors for the trigger state machine. Pure functions over kline frames.

Short case (supply AOI): tag = price enters the band; sweep = a bearish liquidity
run of a swing high at/near the AOI; shift = a downward MSS/CHoCH; entry = the first
bullish (opposing) candle of the rejected rally. Long case mirrors every comparison.
"""
from typing import Optional

import pandas as pd

from aoi import AOI, band_lo_hi
from liquidity import detect_sweeps
from structure import detect_structure_breaks


def tag_time(aoi: AOI, m15: pd.DataFrame) -> Optional[pd.Timestamp]:
    """open_time of the first M15 candle whose range overlaps the AOI band, else None."""
    lo, hi = band_lo_hi(aoi)
    for t, h, l in zip(m15["open_time"], m15["high"], m15["low"]):
        if h >= lo and l <= hi:
            return pd.Timestamp(t)
    return None


def etf_sweep(aoi: AOI, m15: pd.DataFrame, after: pd.Timestamp, tol: float) -> Optional[pd.Timestamp]:
    """open_time of the first directionally-relevant sweep after `after` whose swept
    level sits within `tol` of the AOI band. Supply wants a bearish sweep (swept high),
    demand a bullish sweep (swept low)."""
    want = "bearish" if aoi.side == "supply" else "bullish"
    lo, hi = band_lo_hi(aoi)
    times = m15["open_time"].to_numpy()
    for s in detect_sweeps(m15):
        t = pd.Timestamp(times[s["index"]])
        if t <= after or s["direction"] != want:
            continue
        if (lo - tol) <= s["level"] <= (hi + tol):
            return t
    return None


def etf_shift(aoi: AOI, m5: pd.DataFrame, after: pd.Timestamp) -> Optional[pd.Timestamp]:
    """open_time of the first MSS/CHoCH after `after` in the trade direction (down for a
    supply/short, up for a demand/long). Pluggable: a RelicusRoad Signal Line reader could
    replace detect_structure_breaks here."""
    want = "down" if aoi.side == "supply" else "up"
    times = m5["open_time"].to_numpy()
    for b in detect_structure_breaks(m5):
        t = pd.Timestamp(times[b["index"]])
        if t > after and b["direction"] == want:
            return t
    return None


def first_opposing_candle(aoi: AOI, m5: pd.DataFrame, after: pd.Timestamp) -> Optional[dict]:
    """First opposing candle after `after`: a bullish candle for a short (entry triggers
    below its low), a bearish candle for a long (entry above its high). Returns
    {time, low, high} or None."""
    want_bull = aoi.side == "supply"
    for t, o, h, l, c in zip(m5["open_time"], m5["open"], m5["high"], m5["low"], m5["close"]):
        if pd.Timestamp(t) <= after:
            continue
        if (c > o) == want_bull:
            return {"time": pd.Timestamp(t), "low": float(l), "high": float(h)}
    return None
