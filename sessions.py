"""Trading-session gating for forex/commodity symbols (UTC)."""
import pandas as pd


def in_forex_session(now: pd.Timestamp, window: tuple) -> bool:
    """True if `now` (tz-aware UTC) is a weekday within the half-open [start, end) hours.

    `window` is `(start_hour, end_hour)` and assumes `start < end` (no overnight window).
    `now` must be tz-aware (a naive local time would silently misgate)."""
    if now.tzinfo is None:
        raise ValueError("now must be tz-aware (UTC)")
    if now.weekday() >= 5:          # 5 = Sat, 6 = Sun
        return False
    return window[0] <= now.hour < window[1]
