"""Market-structure-break detection (BOS / MSS-CHoCH). Pure, descriptive."""
from typing import Dict, List, Optional

import pandas as pd

from liquidity import swing_points


def detect_structure_breaks(df: pd.DataFrame, left: int = 2, right: int = 2) -> List[Dict]:
    """Detect closes that break the most recent CONFIRMED swing high/low.

    Bullish break: close > most-recent confirmed swing-high level (not already broken).
    Bearish break: close < most-recent confirmed swing-low level.
    Each break is labelled 'BOS' (break of structure) if it agrees with the current
    structure direction, or 'MSS' (market-structure shift / CHoCH) if it flips it. The
    first break of all is labelled 'MSS'. A swing is eligible only `right` bars after it
    forms (no look-ahead). A given swing level fires at most once.
    Returns list of {index, direction('up'/'down'), kind('BOS'/'MSS'), level, swing_index}.
    """
    hi = df['high'].to_numpy()
    lo = df['low'].to_numpy()
    cl = df['close'].to_numpy()
    sh, sl = swing_points(df, left, right)
    out: List[Dict] = []
    last_sh: Optional[int] = None
    last_sl: Optional[int] = None
    broken_sh: Optional[int] = None
    broken_sl: Optional[int] = None
    pi_h = pi_l = 0
    sdir = 0  # current structure direction: +1 up, -1 down, 0 none
    for t in range(len(df)):
        while pi_h < len(sh) and sh[pi_h] + right < t:
            last_sh = sh[pi_h]; pi_h += 1
        while pi_l < len(sl) and sl[pi_l] + right < t:
            last_sl = sl[pi_l]; pi_l += 1
        if last_sh is not None and last_sh != broken_sh and cl[t] > hi[last_sh]:
            kind = 'BOS' if sdir == 1 else 'MSS'
            out.append({'index': t, 'direction': 'up', 'kind': kind,
                        'level': float(hi[last_sh]), 'swing_index': last_sh})
            broken_sh = last_sh
            sdir = 1
            continue
        if last_sl is not None and last_sl != broken_sl and cl[t] < lo[last_sl]:
            kind = 'BOS' if sdir == -1 else 'MSS'
            out.append({'index': t, 'direction': 'down', 'kind': kind,
                        'level': float(lo[last_sl]), 'swing_index': last_sl})
            broken_sl = last_sl
            sdir = -1
    return out
