"""Confluence factors. Each factor(aoi, ctx, inst) -> normalized contribution.

Contributions are in [0, 1] except factor_shift, which may be negative (a shift
against the trade direction is a penalty). Missing data degrades to neutral (0.0);
factors never raise.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pandas as pd

from aoi import AOI, band_lo_hi
from instruments import Instrument, to_units
from liquidity import detect_sweeps
from levels import unfilled_fvgs
from structure import detect_structure_breaks


@dataclass
class ScoringContext:
    daily: pd.DataFrame
    h4: pd.DataFrame
    etf: pd.DataFrame                       # entry timeframe (e.g. M15) for shift
    all_aois: List[AOI]                     # for clustering + R:R
    bias_map: dict
    shift_reader: Optional[Callable] = None # (aoi, ctx) -> 'up'|'down'|None
    sweep_lookback: int = 10                # bars back to credit a sweep


def _aoi_frame(aoi: AOI, ctx: ScoringContext) -> pd.DataFrame:
    return ctx.daily if aoi.timeframe == "D" else ctx.h4


def factor_sweep(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """1.0 if a directionally-relevant prior swing was run within `sweep_lookback`
    bars (a swept high fuels a supply/short, a swept low fuels a demand/long)."""
    frame = _aoi_frame(aoi, ctx)
    sweeps = detect_sweeps(frame)
    if not sweeps:
        return 0.0
    want = "bearish" if aoi.side == "supply" else "bullish"  # bearish = swept a high
    last_idx = len(frame) - 1
    for s in sweeps:
        if s["direction"] == want and last_idx - s["index"] <= ctx.sweep_lookback:
            return 1.0
    return 0.0


def factor_cluster(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """Reward AOIs whose proximal sits within `cluster_band` (in instrument units)
    of other AOIs' proximals. 0 if isolated; ramps with neighbour count."""
    neighbours = 0
    for other in ctx.all_aois:
        if other is aoi:
            continue
        if to_units(abs(other.proximal - aoi.proximal), inst) <= inst.cluster_band:
            neighbours += 1
    if neighbours == 0:
        return 0.0
    return min(neighbours / 2.0, 1.0)


def _overlaps(a_lo, a_hi, b_lo, b_hi) -> bool:
    return a_hi >= b_lo and a_lo <= b_hi


def factor_structure(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """1.0 if an UNMITIGATED FVG (matching the AOI side) overlaps the AOI band.

    demand <- bull FVG, supply <- bear FVG. Mitigated gaps are excluded by
    unfilled_fvgs, so they score 0."""
    frame = _aoi_frame(aoi, ctx)
    direction = "bull" if aoi.side == "demand" else "bear"
    a_lo, a_hi = band_lo_hi(aoi)
    for f in unfilled_fvgs(frame, direction):
        if _overlaps(a_lo, a_hi, f.bottom, f.top):
            return 1.0
    return 0.0
