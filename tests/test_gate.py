from gate import bias_gate
from aoi import AOI

SUPPLY_D = AOI("D", "supply", 71050.0, 71170.0, "daily_swing_high")
DEMAND_D = AOI("D", "demand", 60000.0, 59880.0, "daily_swing_low")


def test_A1_flat_own_tf_is_no_trade():
    assert bias_gate(DEMAND_D, {"W": "UP", "D": "FLAT"}) == "no-trade"


def test_A2a_counter_htf_trend_is_no_trade():
    assert bias_gate(SUPPLY_D, {"W": "UP", "D": "UP"}) == "no-trade"


def test_A2b_pullback_into_htf_aoi_passes():
    assert bias_gate(SUPPLY_D, {"W": "DOWN", "D": "DOWN"}) == "pass"
    assert bias_gate(SUPPLY_D, {"D": "DOWN"}) == "pass"


def test_A2c_aligned_continuation_passes():
    assert bias_gate(DEMAND_D, {"W": "UP", "D": "UP"}) == "pass"


def test_higher_tf_flat_does_not_block():
    assert bias_gate(SUPPLY_D, {"W": "FLAT", "D": "DOWN"}) == "pass"


def test_h4_aoi_checks_h4_d_w():
    h4_supply = AOI("H4", "supply", 64000.0, 64120.0, "h4_swing_high")
    assert bias_gate(h4_supply, {"H4": "DOWN", "D": "DOWN", "W": "DOWN"}) == "pass"
    assert bias_gate(h4_supply, {"H4": "DOWN", "D": "UP"}) == "no-trade"
