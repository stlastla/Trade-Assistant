from levels import Level, Bias
from fvg import FVG
import pandas as pd
import state


def test_build_and_save_state_roundtrips(tmp_path):
    path = tmp_path / "state.json"
    levels = [Level("pdl", 100.0, "low"), Level("pdh", 110.0, "high")]
    zones = [FVG(2, "bull", 100.0, 105.0, pd.Timestamp("2026-06-14T08:00Z"))]
    bias = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")

    payload = state.build_state(
        price=104.0, levels=levels, zones=zones, bias=bias,
        fired=["pdl:100.0"], last_alert={"text": "swept PDL", "time": "09:25"},
        updated_at="2026-06-14T09:25:00Z",
    )
    state.save_state(payload, str(path))
    loaded = state.load_state(str(path))

    assert loaded["price"] == 104.0
    assert loaded["bias"]["h4_dir"] == "up"
    assert loaded["levels"][0]["source"] == "pdl"
    assert loaded["zones"][0]["direction"] == "bull"
    assert loaded["fired"] == ["pdl:100.0"]
    assert loaded["last_alert"]["text"] == "swept PDL"


def test_load_state_missing_returns_empty(tmp_path):
    assert state.load_state(str(tmp_path / "nope.json")) == {}
