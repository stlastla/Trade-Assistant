"""Build the ARMED trade plan: entry, HTF-wide stop, next-opposing-AOI target, R:R."""
from typing import List, Optional

from aoi import AOI
from instruments import Instrument


def _next_opposing(aoi: AOI, aois: List[AOI]) -> Optional[float]:
    """Nearest opposing-side AOI proximal in the profit direction (demand below a supply,
    supply above a demand)."""
    want = "demand" if aoi.side == "supply" else "supply"
    cands = []
    for o in aois:
        if o is aoi or o.side != want:
            continue
        if aoi.side == "supply" and o.proximal < aoi.proximal:
            cands.append(o.proximal)
        elif aoi.side == "demand" and o.proximal > aoi.proximal:
            cands.append(o.proximal)
    if not cands:
        return None
    return max(cands) if aoi.side == "supply" else min(cands)


def build_plan(aoi: AOI, entry_candle: dict, aois: List[AOI], inst: Instrument) -> dict:
    """entry below the opposing candle (short) / above it (long); stop at the HTF distal
    edge ± stop_buffer; target the next opposing AOI; R:R off the HTF stop."""
    if aoi.side == "supply":
        entry = entry_candle["low"]
        stop = aoi.distal + inst.stop_buffer
    else:
        entry = entry_candle["high"]
        stop = aoi.distal - inst.stop_buffer
    target = _next_opposing(aoi, aois)
    risk = abs(entry - stop)
    rr = abs(entry - target) / risk if (target is not None and risk > 0) else 0.0
    return {"entry": entry, "stop": stop, "target": target, "rr": rr}
