"""Live sweep+reclaim detection against the marked level set, with the HTF gate."""
from typing import List, Optional

from levels import Level, Bias


def detect_level_sweep(bar: dict, level: Level) -> Optional[str]:
    """'bullish' if `bar` swept a low and closed back above it; 'bearish' for a high; else None.

    `bar` is a mapping with 'high','low','close' (one closed M15 candle)."""
    if level.side == "low" and bar["low"] < level.price and bar["close"] > level.price:
        return "bullish"
    if level.side == "high" and bar["high"] > level.price and bar["close"] < level.price:
        return "bearish"
    return None


def level_key(level: Level) -> str:
    """Stable de-dupe key. Price is normalized to 2 decimals so the key does not depend
    on the caller's numeric type (int vs float vs numpy) or float noise from level math."""
    return f"{level.source}:{float(level.price):.2f}"


def scan(bar: dict, levels: List[Level], bias: Bias, fired: set,
         require_alignment: bool = True, counter_trend_mode: str = "silent") -> List[dict]:
    """Check `bar` against every not-yet-fired level. Returns emitted triggers and adds
    their keys to `fired` (mutated in place).

    A trigger is emitted when:
      - aligned with the HTF bias, OR
      - counter-trend AND (alignment not required OR counter_trend_mode == 'fyi').
    Silent counter-trend sweeps are dropped and NOT marked fired.

    Each trigger: {level, direction('bullish'/'bearish'), aligned(bool), key}.
    """
    triggers: List[dict] = []
    for lvl in levels:
        key = level_key(lvl)
        if key in fired:
            continue
        swept = detect_level_sweep(bar, lvl)
        if swept is None:
            continue
        direction = "up" if swept == "bullish" else "down"
        aligned = bias.aligned(direction)
        if not aligned and require_alignment and counter_trend_mode == "silent":
            continue
        triggers.append({"level": lvl, "direction": swept, "aligned": aligned, "key": key})
        fired.add(key)
    return triggers
