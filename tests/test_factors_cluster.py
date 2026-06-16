import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_cluster
from instruments import get_instrument

XAU = get_instrument("XAUUSD")
EUR = get_instrument("EURUSD")


def _ctx(aois):
    f = pd.DataFrame({"high": [1.0], "low": [1.0], "close": [1.0]})
    return ScoringContext(daily=f, h4=f, etf=f, all_aois=aois, bias_map={})


def test_C1_xau_tight_cluster_scores_positive():
    a = AOI("H4", "supply", 2412.0, 2415.0, "h4_swing_high")
    others = [a,
              AOI("D", "supply", 2413.0, 2416.0, "pdh"),
              AOI("D", "supply", 2411.0, 2414.0, "daily_swing_high")]
    assert factor_cluster(a, _ctx(others), XAU) > 0.0


def test_C2_xau_false_cluster_no_bonus():
    a = AOI("H4", "supply", 2405.0, 2408.0, "h4_swing_high")
    others = [a,
              AOI("D", "supply", 2412.0, 2415.0, "pdh"),
              AOI("D", "supply", 2419.0, 2422.0, "daily_swing_high")]
    assert factor_cluster(a, _ctx(others), XAU) == 0.0


def test_C3_eur_cluster_in_pips():
    a = AOI("H4", "demand", 1.08500, 1.08420, "h4_swing_low")
    others = [a,
              AOI("D", "demand", 1.08530, 1.08450, "pdl"),
              AOI("D", "demand", 1.08470, 1.08390, "daily_swing_low")]
    assert factor_cluster(a, _ctx(others), EUR) > 0.0


def test_C3_eur_unit_guard_beyond_band_does_not_cluster():
    # 10 pips apart (> EUR cluster_band of 8). With to_units this is NOT a cluster (0.0);
    # a buggy raw-price comparison (0.0010 <= 8.0) would wrongly cluster -> this FAILS
    # if to_units is dropped. The real unit-bug guard.
    a = AOI("H4", "demand", 1.08500, 1.08420, "h4_swing_low")
    others = [a, AOI("D", "demand", 1.08600, 1.08520, "pdl")]  # +10 pips
    assert factor_cluster(a, _ctx(others), EUR) == 0.0
