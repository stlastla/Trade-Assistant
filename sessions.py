"""Trading-session gating for forex/commodity symbols (UTC)."""
import pandas as pd


def in_forex_session(now: pd.Timestamp, window) -> bool:
    """True if `now` (tz-aware UTC) is a weekday within [window[0], window[1]) hours."""
    if now.weekday() >= 5:          # 5 = Sat, 6 = Sun
        return False
    return window[0] <= now.hour < window[1]
