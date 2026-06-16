from aoi import AOI
import state


def test_build_state_includes_scored_aois():
    a = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    a.gate, a.score, a.label = "pass", 0.82, "A+"
    a.breakdown = {"sweep": 1.0, "cluster": 0.5}
    payload = state.build_state(
        price=69000.0, levels=[], zones=[], bias=None,
        fired=[], last_alert={}, updated_at="2026-06-16T07:00:00Z", aois=[a])
    assert payload["aois"][0]["label"] == "A+"
    assert payload["aois"][0]["side"] == "supply"
    assert payload["aois"][0]["breakdown"]["sweep"] == 1.0
    assert payload["aois"][0]["proximal"] == 70000.0


def test_build_state_aois_defaults_empty():
    payload = state.build_state(
        price=1.0, levels=[], zones=[], bias=None,
        fired=[], last_alert={}, updated_at="x")
    assert payload["aois"] == []
    assert payload["bias_tf"] == {}


def test_build_state_includes_bias_tf():
    payload = state.build_state(
        price=1.0, levels=[], zones=[], bias=None,
        fired=[], last_alert={}, updated_at="x",
        bias_tf={"W": "DOWN", "D": "DOWN", "H4": "UP"})
    assert payload["bias_tf"]["D"] == "DOWN" and payload["bias_tf"]["H4"] == "UP"
