"""Read/write state.json — the single source of truth shared by app, menu, and chart."""
import json
import os
from dataclasses import asdict
from typing import List

from levels import Level, Bias
from fvg import FVG


def _zone_to_dict(z: FVG) -> dict:
    return {"direction": z.direction, "bottom": z.bottom, "top": z.top,
            "time": str(z.time)}


def _aoi_to_dict(a) -> dict:
    return {"timeframe": a.timeframe, "side": a.side,
            "proximal": a.proximal, "distal": a.distal, "source": a.source,
            "gate": a.gate, "score": a.score, "label": a.label,
            "breakdown": a.breakdown, "state": a.state, "plan": a.plan}


def build_state(price: float, levels: List[Level], zones: List[FVG], bias: Bias,
                fired: list, last_alert: dict, updated_at: str, aois=None,
                bias_tf=None) -> dict:
    return {
        "price": price,
        "levels": [asdict(l) for l in levels],
        "zones": [_zone_to_dict(z) for z in zones],
        "bias": asdict(bias) if bias is not None else None,
        "bias_tf": bias_tf or {},   # per-TF confluence bias {W,D,H4} for the chart panel
        "fired": list(fired),
        "last_alert": last_alert,
        "updated_at": updated_at,
        "aois": [_aoi_to_dict(a) for a in (aois or [])],
    }


def save_state(payload: dict, path: str) -> None:
    """Write atomically (temp file + os.replace) so concurrent readers never see a partial file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)
