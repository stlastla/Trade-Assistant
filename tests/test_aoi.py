import pandas as pd
from aoi import AOI, level_to_aoi, fvgs_to_aois, band_lo_hi
from levels import Level
from fvg import FVG
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def test_supply_level_band_has_distal_above():
    aoi = level_to_aoi(Level("daily_swing_high", 70000.0, "high"), BTC)
    assert aoi.side == "supply" and aoi.timeframe == "D"
    assert aoi.proximal == 70000.0
    assert aoi.distal == 70000.0 + BTC.aoi_band
    lo, hi = band_lo_hi(aoi)
    assert lo == 70000.0 and hi == 70000.0 + BTC.aoi_band


def test_demand_level_band_has_distal_below():
    aoi = level_to_aoi(Level("h4_swing_low", 60000.0, "low"), BTC)
    assert aoi.side == "demand" and aoi.timeframe == "H4"
    assert aoi.proximal == 60000.0
    assert aoi.distal == 60000.0 - BTC.aoi_band


def test_pdh_pdl_are_daily():
    assert level_to_aoi(Level("pdh", 1.0, "high"), BTC).timeframe == "D"
    assert level_to_aoi(Level("pdl", 1.0, "low"), BTC).timeframe == "D"


def test_fvgs_to_aois_maps_direction_to_side():
    bull = FVG(2, "bull", 100.0, 105.0, pd.Timestamp("2026-06-14T08:00Z"))
    bear = FVG(2, "bear", 110.0, 115.0, pd.Timestamp("2026-06-14T08:00Z"))
    aois = fvgs_to_aois([bull, bear], "H4")
    by_side = {a.side: a for a in aois}
    assert by_side["demand"].source == "h4_fvg_bull"
    assert by_side["supply"].source == "h4_fvg_bear"
    assert by_side["demand"].proximal == 105.0 and by_side["demand"].distal == 100.0
    # bear FVG = supply: price rises in from below -> proximal = bottom, distal = top
    assert by_side["supply"].proximal == 110.0 and by_side["supply"].distal == 115.0
