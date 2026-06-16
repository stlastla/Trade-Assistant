"""Bias gate: hard pass / no-trade. Checks the AOI's own timeframe AND higher only.

A lower-timeframe move into the AOI is never consulted (spec §2): the up-leg into
an HTF supply is the pullback/delivery leg, not a bias conflict.
"""
from aoi import AOI

# AOI timeframe -> [own, higher...] in ascending order
_TF_CHAIN = {"H4": ["H4", "D", "W"], "D": ["D", "W"]}


def bias_gate(aoi: AOI, bias_map: dict) -> str:
    want = "UP" if aoi.side == "demand" else "DOWN"
    chain = _TF_CHAIN[aoi.timeframe]
    own = bias_map.get(chain[0])
    if own != want:                       # own-TF FLAT or opposite
        return "no-trade"
    for tf in chain[1:]:                  # strictly higher TFs
        b = bias_map.get(tf)
        if b is not None and b != "FLAT" and b != want:
            return "no-trade"             # higher-TF conflict
    return "pass"
