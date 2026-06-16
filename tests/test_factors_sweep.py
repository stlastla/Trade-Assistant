import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_sweep
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(frame):
    return ScoringContext(daily=frame, h4=frame, etf=frame,
                          all_aois=[], bias_map={}, shift_reader=None)


def _frame_with_high_sweep():
    return pd.DataFrame({
        "high":  [100, 110, 120, 110, 105, 125, 116],
        "low":   [90,  100, 110, 100,  95, 112, 108],
        "close": [95,  108, 118, 105, 100, 118, 112],
    })


def _frame_no_sweep():
    return pd.DataFrame({
        "high":  [100, 110, 120, 110, 105, 116, 114],
        "low":   [90,  100, 110, 100,  95, 110, 108],
        "close": [95,  108, 118, 105, 100, 114, 112],
    })


def test_sweep_present_for_supply_scores_high():
    supply = AOI("H4", "supply", 116.0, 120.0, "h4_swing_high")
    assert factor_sweep(supply, _ctx(_frame_with_high_sweep()), BTC) == 1.0


def test_no_sweep_scores_zero():
    supply = AOI("H4", "supply", 116.0, 120.0, "h4_swing_high")
    assert factor_sweep(supply, _ctx(_frame_no_sweep()), BTC) == 0.0


def test_wrong_side_sweep_not_rewarded():
    demand = AOI("H4", "demand", 116.0, 112.0, "h4_swing_low")
    assert factor_sweep(demand, _ctx(_frame_with_high_sweep()), BTC) == 0.0
