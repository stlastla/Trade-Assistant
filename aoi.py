"""Areas of Interest as bands [proximal, distal] with timeframe + side.

proximal = the edge price reaches first; distal = the far / stop-side edge.
Supply: distal is ABOVE (proximal < distal). Demand: distal is BELOW (proximal > distal).
"""
from dataclasses import dataclass, field
from typing import List

from levels import Level, build_levels, unfilled_fvgs
from fvg import FVG
from instruments import Instrument


@dataclass
class AOI:
    timeframe: str            # 'D' | 'H4'
    side: str                 # 'supply' | 'demand'
    proximal: float
    distal: float
    source: str
    origin: dict = field(default_factory=dict)
    # scoring results, filled by scoring.py
    score: float = 0.0
    label: str = "unscored"
    gate: str = ""
    breakdown: dict = field(default_factory=dict)


def aoi_key(aoi: "AOI") -> str:
    """Stable id used to carry machine state across ticks (price rounded to 1dp)."""
    return f"{aoi.source}:{round(float(aoi.proximal), 1)}"


def band_lo_hi(aoi: AOI) -> tuple:
    """(low_edge, high_edge) of the band regardless of side."""
    return (min(aoi.proximal, aoi.distal), max(aoi.proximal, aoi.distal))


def _level_timeframe(source: str) -> str:
    return "H4" if source.startswith("h4") else "D"


def level_to_aoi(level: Level, inst: Instrument) -> AOI:
    tf = _level_timeframe(level.source)
    if level.side == "high":   # supply: stop above the high
        return AOI(tf, "supply", level.price, level.price + inst.aoi_band, level.source)
    return AOI(tf, "demand", level.price, level.price - inst.aoi_band, level.source)


def fvgs_to_aois(fvgs: List[FVG], timeframe: str) -> List[AOI]:
    tf = timeframe.lower()
    out: List[AOI] = []
    for f in fvgs:
        if f.direction == "bull":   # demand: price drops in from above -> proximal = top
            out.append(AOI(timeframe, "demand", f.top, f.bottom, f"{tf}_fvg_bull",
                           {"fvg_top": f.top, "fvg_bottom": f.bottom}))
        else:                       # bear = supply: price rises in from below -> proximal = bottom
            out.append(AOI(timeframe, "supply", f.bottom, f.top, f"{tf}_fvg_bear",
                           {"fvg_top": f.top, "fvg_bottom": f.bottom}))
    return out


def build_aois(daily, h4, now, inst: Instrument,
               daily_n: int, h4_n: int, left: int, right: int) -> List[AOI]:
    """All AOIs for scoring: banded swing/PDH/PDL levels + unmitigated H4 FVG zones."""
    levels = build_levels(daily, h4, now, daily_n, h4_n, left, right)
    aois = [level_to_aoi(l, inst) for l in levels]
    aois += fvgs_to_aois(unfilled_fvgs(h4, "bull") + unfilled_fvgs(h4, "bear"), "H4")
    return aois


def next_opposing_proximal(aoi: AOI, aois: List[AOI]):
    """Nearest opposing-side AOI proximal in the profit direction (a demand below a
    supply, a supply above a demand), or None. Shared by the R:R factor and trade_plan."""
    want = "demand" if aoi.side == "supply" else "supply"
    cands = [o.proximal for o in aois
             if o is not aoi and o.side == want
             and ((aoi.side == "supply" and o.proximal < aoi.proximal)
                  or (aoi.side == "demand" and o.proximal > aoi.proximal))]
    if not cands:
        return None
    return max(cands) if aoi.side == "supply" else min(cands)
