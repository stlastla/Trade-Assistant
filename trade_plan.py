"""Build the ARMED trade plan: entry, HTF-wide stop, next-opposing-AOI target, R:R."""
from typing import List

from aoi import AOI, next_opposing_proximal
from instruments import Instrument


def build_plan(aoi: AOI, entry_candle: dict, aois: List[AOI], inst: Instrument) -> dict:
    """entry below the opposing candle (short) / above it (long); stop at the HTF distal
    edge ± stop_buffer; target the next opposing AOI; R:R off the HTF stop."""
    if aoi.side == "supply":
        entry = entry_candle["low"]
        stop = aoi.distal + inst.stop_buffer
    else:
        entry = entry_candle["high"]
        stop = aoi.distal - inst.stop_buffer
    target = next_opposing_proximal(aoi, aois)
    risk = abs(entry - stop)
    rr = abs(entry - target) / risk if (target is not None and risk > 0) else 0.0
    return {"entry": entry, "stop": stop, "target": target, "rr": rr}
