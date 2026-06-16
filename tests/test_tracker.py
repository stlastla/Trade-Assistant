import pandas as pd
from aoi import AOI
from tracker import Tracker
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _m15(rows):
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows], "low": [r[2] for r in rows], "close": [r[3] for r in rows]})


def _passed(side, prox, dist, src, label="valid"):
    a = AOI("H4", side, prox, dist, src)
    a.gate, a.label = "pass", label
    return a


EMPTY_M5 = pd.DataFrame({"open_time": pd.to_datetime([], utc=True),
                         "open": [], "high": [], "low": [], "close": []})


def test_advance_all_emits_event_on_transition_and_carries_state():
    aoi = _passed("supply", 100.0, 112.0, "h4_swing_high")
    tagged = _m15([("2026-06-16T00:00Z", 95, 90, 93), ("2026-06-16T00:15Z", 104, 99, 102)])
    tr = Tracker()
    ev1 = tr.advance_all([aoi], tagged, EMPTY_M5, BTC, 12, 12)
    assert len(ev1) == 1 and ev1[0][1].state == "TAGGED"
    ev2 = tr.advance_all([aoi], tagged, EMPTY_M5, BTC, 12, 12)
    assert ev2 == []


def test_no_trade_aois_are_skipped():
    aoi = _passed("supply", 100.0, 112.0, "h4_swing_high")
    aoi.gate = "no-trade"
    tr = Tracker()
    assert tr.advance_all([aoi], _m15([("2026-06-16T00:00Z", 104, 99, 102)]), EMPTY_M5, BTC, 12, 12) == []


def test_disappeared_aoi_is_dropped_and_reset_clears():
    aoi = _passed("supply", 100.0, 112.0, "h4_swing_high")
    tr = Tracker()
    tr.advance_all([aoi], _m15([("2026-06-16T00:15Z", 104, 99, 102)]), EMPTY_M5, BTC, 12, 12)
    assert len(tr.states) == 1
    tr.advance_all([], EMPTY_M5, EMPTY_M5, BTC, 12, 12)
    assert tr.states == {}
    tr.advance_all([aoi], _m15([("2026-06-16T00:15Z", 104, 99, 102)]), EMPTY_M5, BTC, 12, 12)
    tr.reset()
    assert tr.states == {}
