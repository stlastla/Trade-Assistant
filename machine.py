"""Per-AOI trigger state machine. `advance` re-derives the furthest state reached from
the current M15/M5 frames; the tracker diffs prior vs new to emit stage events.

States: WATCHING -> TAGGED -> SWEPT -> SHIFTED -> ARMED  (+ INVALIDATED, STALE).
Ordering is strict: a shift before a sweep cannot advance (we only look for the shift on
bars after the sweep). Short case; long mirrors via the detectors.
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from aoi import AOI
from triggers import tag_time, etf_sweep, etf_shift, first_opposing_candle
from trade_plan import build_plan


@dataclass
class MachineState:
    state: str = "WATCHING"
    tag_time: Optional[pd.Timestamp] = None
    swept_time: Optional[pd.Timestamp] = None
    shift_time: Optional[pd.Timestamp] = None
    plan: Optional[dict] = None


def _distal_broken(aoi: AOI, m15: pd.DataFrame, after: pd.Timestamp) -> bool:
    """Price closed beyond the HTF distal edge (a real break, not a wick) on a bar at or
    after `after` — i.e. once the setup has begun (post-tag), not in stale history before
    price ever reached the zone."""
    sub = m15[m15["open_time"] >= after]
    closes = sub["close"].to_numpy()
    if aoi.side == "supply":
        return bool((closes > aoi.distal).any())
    return bool((closes < aoi.distal).any())


def _bars_after(frame: pd.DataFrame, t: pd.Timestamp) -> int:
    return int((frame["open_time"] > t).sum())


def advance(aoi: AOI, m15: pd.DataFrame, m5: pd.DataFrame, aois, inst,
            stale_sweep_bars: int, stale_shift_bars: int) -> MachineState:
    tagged = tag_time(aoi, m15)
    if tagged is None:
        return MachineState("WATCHING")

    if _distal_broken(aoi, m15, tagged):   # distal broken AFTER the setup began
        return MachineState("INVALIDATED", tag_time=tagged)

    swept = etf_sweep(aoi, m15, tagged, tol=inst.stop_buffer)
    if swept is None:
        if _bars_after(m15, tagged) > stale_sweep_bars:
            return MachineState("STALE", tag_time=tagged)
        return MachineState("TAGGED", tag_time=tagged)

    shifted = etf_shift(aoi, m5, swept)
    if shifted is None:
        if _bars_after(m5, swept) > stale_shift_bars:
            return MachineState("STALE", tag_time=tagged, swept_time=swept)
        return MachineState("SWEPT", tag_time=tagged, swept_time=swept)

    entry = first_opposing_candle(aoi, m5, shifted)
    if entry is None:
        return MachineState("SHIFTED", tag_time=tagged, swept_time=swept, shift_time=shifted)

    plan = build_plan(aoi, entry, aois, inst)
    return MachineState("ARMED", tag_time=tagged, swept_time=swept, shift_time=shifted, plan=plan)
