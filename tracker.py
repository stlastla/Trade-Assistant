"""Holds per-AOI machine state across the 5-min ticks. Matches fresh scored AOIs by
aoi_key, advances each, and emits (aoi, new_state, prior_state_name) on transitions."""
from typing import List

from aoi import AOI, aoi_key
from machine import MachineState, advance


class Tracker:
    def __init__(self):
        self.states = {}   # aoi_key -> MachineState

    def reset(self):
        self.states = {}

    def advance_all(self, scored_aois: List[AOI], m15, m5, inst,
                    stale_sweep_bars: int, stale_shift_bars: int) -> list:
        tradeable = [a for a in scored_aois if a.gate == "pass"]
        events = []
        live = set()
        for aoi in tradeable:
            k = aoi_key(aoi)
            live.add(k)
            prior = self.states.get(k, MachineState())
            new = advance(aoi, m15, m5, tradeable, inst, stale_sweep_bars, stale_shift_bars)
            self.states[k] = new
            if new.state != prior.state:
                events.append((aoi, new, prior.state))
        for k in list(self.states):
            if k not in live:
                del self.states[k]
        return events
