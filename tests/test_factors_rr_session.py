import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_rr, factor_session
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(all_aois):
    f = pd.DataFrame({"high": [1.0], "low": [1.0], "close": [1.0]})
    return ScoringContext(daily=f, h4=f, etf=f, all_aois=all_aois, bias_map={})


def test_F1_healthy_room_scores_positive():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    target = AOI("D", "demand", 67000.0, 66880.0, "daily_swing_low")
    assert factor_rr(supply, _ctx([supply, target]), BTC) > 0.0


def test_F2_boxed_in_scores_zero():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    target = AOI("D", "demand", 69950.0, 69900.0, "daily_swing_low")
    assert factor_rr(supply, _ctx([supply, target]), BTC) == 0.0


def test_F_no_target_is_neutral():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    assert factor_rr(supply, _ctx([supply]), BTC) == 0.0


def test_session_neutral_without_session_info():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    assert factor_session(supply, _ctx([supply]), BTC) == 0.0
