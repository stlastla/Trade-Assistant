from aoi import AOI
import state


def test_aoi_carries_state_and_plan_in_state_json():
    a = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    a.gate, a.label = "pass", "A+"
    a.state = "ARMED"
    a.plan = {"entry": 69800.0, "stop": 70180.0, "target": 67000.0, "rr": 2.5}
    payload = state.build_state(price=69000.0, levels=[], zones=[], bias=None,
                                fired=[], last_alert={}, updated_at="x", aois=[a])
    d = payload["aois"][0]
    assert d["state"] == "ARMED"
    assert d["plan"]["rr"] == 2.5


def test_aoi_state_defaults_when_unset():
    a = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    payload = state.build_state(price=1.0, levels=[], zones=[], bias=None,
                                fired=[], last_alert={}, updated_at="x", aois=[a])
    assert payload["aois"][0]["state"] == "WATCHING"
    assert payload["aois"][0]["plan"] is None
