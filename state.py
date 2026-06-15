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


def build_state(price: float, levels: List[Level], zones: List[FVG], bias: Bias,
                fired: list, last_alert: dict, updated_at: str) -> dict:
    return {
        "price": price,
        "levels": [asdict(l) for l in levels],
        "zones": [_zone_to_dict(z) for z in zones],
        "bias": asdict(bias),
        "fired": list(fired),
        "last_alert": last_alert,
        "updated_at": updated_at,
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
