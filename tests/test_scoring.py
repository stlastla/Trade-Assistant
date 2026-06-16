import pandas as pd
from aoi import AOI
from factors import ScoringContext
from scoring import score_aoi, FACTORS
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(bias_map, **over):
    f = pd.DataFrame({"high": [1.0], "low": [1.0], "close": [1.0]})
    base = dict(daily=f, h4=f, etf=f, all_aois=[], bias_map=bias_map, shift_reader=None)
    base.update(over)
    return ScoringContext(**base)


def test_factors_registry_has_all_six():
    assert {name for name, _ in FACTORS} == {
        "sweep", "cluster", "structure", "shift", "rr", "session"}


def test_A1_flat_bias_is_no_trade():
    aoi = AOI("D", "demand", 100.0, 95.0, "daily_swing_low")
    out = score_aoi(aoi, _ctx({"D": "FLAT"}), BTC)
    assert out.label == "no-trade" and out.gate == "no-trade"


def test_Aplus_requires_sweep(monkeypatch):
    import scoring
    aoi = AOI("D", "supply", 100.0, 112.0, "daily_swing_high")
    monkeypatch.setattr(scoring, "FACTORS", [
        ("sweep", lambda a, c, i: 0.0),
        ("cluster", lambda a, c, i: 1.0),
        ("structure", lambda a, c, i: 1.0),
        ("shift", lambda a, c, i: 1.0),
        ("rr", lambda a, c, i: 1.0),
        ("session", lambda a, c, i: 1.0),
    ])
    out = score_aoi(aoi, _ctx({"D": "DOWN"}), BTC)
    assert out.label != "A+"


def test_B1_beats_B2_and_A1_ordering(monkeypatch):
    import scoring
    supply = AOI("D", "supply", 100.0, 112.0, "daily_swing_high")
    demand_flat = AOI("D", "demand", 100.0, 95.0, "daily_swing_low")

    monkeypatch.setattr(scoring, "FACTORS", [
        ("sweep", lambda a, c, i: 1.0), ("cluster", lambda a, c, i: 0.5),
        ("structure", lambda a, c, i: 1.0), ("shift", lambda a, c, i: 1.0),
        ("rr", lambda a, c, i: 1.0), ("session", lambda a, c, i: 0.0)])
    b1 = score_aoi(supply, _ctx({"D": "DOWN", "W": "DOWN"}), BTC)

    monkeypatch.setattr(scoring, "FACTORS", [
        ("sweep", lambda a, c, i: 0.0), ("cluster", lambda a, c, i: 0.5),
        ("structure", lambda a, c, i: 1.0), ("shift", lambda a, c, i: 0.0),
        ("rr", lambda a, c, i: 0.0), ("session", lambda a, c, i: 0.0)])
    b2 = score_aoi(supply, _ctx({"D": "DOWN", "W": "DOWN"}), BTC)

    a1 = score_aoi(demand_flat, _ctx({"D": "FLAT"}), BTC)

    order = {"A+": 3, "valid": 2, "weak": 1, "no-trade": 0}
    assert order[b1.label] > order[b2.label] > order[a1.label]
    assert b1.label == "A+" and b2.label == "weak" and a1.label == "no-trade"
