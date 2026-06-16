"""Confluence scoring core: bias gate (hard) + weighted factors -> score + label."""
import copy

from aoi import AOI
from gate import bias_gate
from factors import (ScoringContext, factor_sweep, factor_cluster, factor_structure,
                     factor_shift, factor_rr, factor_session)
from instruments import Instrument

FACTORS = [
    ("sweep", factor_sweep),
    ("cluster", factor_cluster),
    ("structure", factor_structure),
    ("shift", factor_shift),
    ("rr", factor_rr),
    ("session", factor_session),
]


def _label(score: float, breakdown: dict, inst: Instrument) -> str:
    th = inst.label_thresholds
    # Hard rule: A+ requires a liquidity sweep present (no combination of other
    # factors can lift a no-sweep AOI to A+ — the anti-chase guard).
    if score >= th["A+"] and breakdown.get("sweep", 0.0) > 0.0:
        return "A+"
    if score >= th["valid"]:
        return "valid"
    return "weak"


def score_aoi(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> AOI:
    """Score a copy of the AOI: sets gate, score, breakdown, label. Returns the copy.

    A copy is returned so the caller's original AOI object is not mutated, allowing
    the same source AOI to be scored under different contexts independently.
    """
    out = copy.copy(aoi)
    gate = bias_gate(out, ctx.bias_map)
    out.gate = gate
    if gate == "no-trade":
        out.score = 0.0
        out.breakdown = {}
        out.label = "no-trade"
        return out
    breakdown = {}
    score = 0.0
    for name, fn in FACTORS:
        contrib = fn(out, ctx, inst)
        breakdown[name] = contrib
        score += inst.factor_weights[name] * contrib
    out.score = score
    out.breakdown = breakdown
    out.label = _label(score, breakdown, inst)
    return out
