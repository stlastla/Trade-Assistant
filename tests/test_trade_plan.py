from aoi import AOI
from trade_plan import build_plan
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def test_short_plan_uses_htf_stop_and_next_demand_target():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    target = AOI("D", "demand", 67000.0, 66880.0, "daily_swing_low")
    entry_candle = {"time": None, "low": 69800.0, "high": 70050.0}
    plan = build_plan(supply, entry_candle, [supply, target], BTC)
    assert plan["entry"] == 69800.0
    assert plan["stop"] == 70120.0 + BTC.stop_buffer
    assert plan["target"] == 67000.0
    risk = (70120.0 + BTC.stop_buffer) - 69800.0
    assert abs(plan["rr"] - (2800.0 / risk)) < 1e-6


def test_long_plan_mirrors():
    demand = AOI("D", "demand", 60000.0, 59880.0, "daily_swing_low")
    target = AOI("D", "supply", 63000.0, 63120.0, "daily_swing_high")
    entry_candle = {"time": None, "low": 59950.0, "high": 60200.0}
    plan = build_plan(demand, entry_candle, [demand, target], BTC)
    assert plan["entry"] == 60200.0
    assert plan["stop"] == 59880.0 - BTC.stop_buffer
    assert plan["target"] == 63000.0


def test_no_target_yields_none_target_and_zero_rr():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    plan = build_plan(supply, {"low": 69800.0, "high": 70050.0}, [supply], BTC)
    assert plan["target"] is None and plan["rr"] == 0.0
