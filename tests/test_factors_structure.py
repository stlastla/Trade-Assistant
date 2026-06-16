import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_structure
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(h4):
    return ScoringContext(daily=h4, h4=h4, etf=h4, all_aois=[], bias_map={})


def _h4_with_open_bull_fvg():
    return pd.DataFrame({
        "open_time": pd.to_datetime(
            ["2026-06-14T00:00Z", "2026-06-14T04:00Z", "2026-06-14T08:00Z",
             "2026-06-14T12:00Z", "2026-06-14T16:00Z"], utc=True),
        "high": [110, 113, 130, 132, 134],
        "low":  [108, 111, 115, 120, 122],
        "close":[109, 112, 128, 130, 132],
    })


def test_D1_fvg_at_demand_aoi_scores_positive():
    aoi = AOI("H4", "demand", 115.0, 110.0, "h4_swing_low")
    assert factor_structure(aoi, _ctx(_h4_with_open_bull_fvg()), BTC) == 1.0


def test_D2_bare_level_scores_zero():
    aoi = AOI("H4", "demand", 90.0, 85.0, "h4_swing_low")
    assert factor_structure(aoi, _ctx(_h4_with_open_bull_fvg()), BTC) == 0.0


def test_D3_mitigated_fvg_not_rewarded():
    df = _h4_with_open_bull_fvg().copy()
    df.loc[4, "low"] = 109
    aoi = AOI("H4", "demand", 115.0, 110.0, "h4_swing_low")
    assert factor_structure(aoi, _ctx(df), BTC) == 0.0
