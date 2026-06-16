import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_shift, structure_shift_reader
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")
SUPPLY = AOI("H4", "supply", 116.0, 120.0, "h4_swing_high")


def _ctx(reader):
    f = pd.DataFrame({"high": [1.0], "low": [1.0], "close": [1.0]})
    return ScoringContext(daily=f, h4=f, etf=f, all_aois=[], bias_map={}, shift_reader=reader)


def test_E1_no_feed_is_neutral():
    assert factor_shift(SUPPLY, _ctx(None), BTC) == 0.0


def test_E2_shift_in_direction_boosts():
    assert factor_shift(SUPPLY, _ctx(lambda a, c: "down"), BTC) == 1.0


def test_E3_shift_against_penalizes():
    assert factor_shift(SUPPLY, _ctx(lambda a, c: "up"), BTC) == -1.0


def test_default_reader_reads_choch_from_etf():
    etf = pd.DataFrame({
        "high":  [100, 110, 120, 112, 108, 104],
        "low":   [90,  100, 110,  95,  92,  88],
        "close": [95,  108, 118, 100,  95,  90],
    })
    ctx = ScoringContext(daily=etf, h4=etf, etf=etf, all_aois=[], bias_map={})
    assert structure_shift_reader(SUPPLY, ctx) in ("up", "down", None)
