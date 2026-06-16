import pandas as pd
from bias import compute_bias, bias_map


def _rising():
    return pd.DataFrame({"high": [c + 1 for c in range(80)],
                         "low": [c - 1 for c in range(80)],
                         "close": [float(c) for c in range(80)]})


def _falling():
    return pd.DataFrame({"high": [101 - c for c in range(80)],
                         "low": [99 - c for c in range(80)],
                         "close": [100.0 - c for c in range(80)]})


def _flat():
    return pd.DataFrame({"high": [100.5] * 80, "low": [99.5] * 80,
                         "close": [100.0] * 80})


def test_compute_bias_up_down_flat():
    assert compute_bias(_rising()) == "UP"
    assert compute_bias(_falling()) == "DOWN"
    assert compute_bias(_flat()) == "FLAT"


def test_flat_when_position_and_slope_disagree():
    # EMA still sloping up over the window, but the final bar plunges below the EMA,
    # so position(down) != slope(up) -> FLAT (the second FLAT condition).
    closes = [float(c) for c in range(79)] + [10.0]
    df = pd.DataFrame({"high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
                       "close": closes})
    assert compute_bias(df) == "FLAT"


def test_falling_ema_not_vetoed_by_stale_up_break():
    # Price ramps UP (creating an up structure break), then falls hard so the EMA
    # slopes down and price ends well below it. Must read DOWN, not FLAT — the old
    # structure-contradiction veto would have wrongly returned FLAT here.
    closes = [float(c) for c in range(40)] + [float(c) for c in range(40, -40, -1)]
    df = pd.DataFrame({"high": [c + 1 for c in closes],
                       "low": [c - 1 for c in closes],
                       "close": closes})
    assert compute_bias(df) == "DOWN"


def test_bias_map_keys():
    m = bias_map(_rising(), _rising(), _falling())
    assert set(m) == {"W", "D", "H4"}
    assert m["W"] == "UP" and m["H4"] == "DOWN"
