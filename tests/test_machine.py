import pandas as pd
from aoi import AOI
from machine import MachineState, advance
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")
SUP = AOI("H4", "supply", 100.0, 112.0, "h4_swing_high")


def _m15(rows):
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows], "low": [r[2] for r in rows], "close": [r[3] for r in rows]})


def _m5(rows):
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "open": [r[1] for r in rows], "high": [r[2] for r in rows],
        "low": [r[3] for r in rows], "close": [r[4] for r in rows]})


M15_TAG_SWEEP = _m15([
    ("2026-06-16T00:00Z", 100, 96, 98),
    ("2026-06-16T00:15Z", 104, 99, 102),
    ("2026-06-16T00:30Z", 110, 103, 108),
    ("2026-06-16T00:45Z", 105, 100, 102),
    ("2026-06-16T01:00Z", 103, 99, 101),
    ("2026-06-16T01:15Z", 113, 106, 107),
    ("2026-06-16T01:30Z", 108, 104, 106),
])

M5_SHIFT_ENTRY = _m5([
    ("2026-06-16T01:20Z", 107, 109, 100, 101),
    ("2026-06-16T01:25Z", 105, 106, 100, 103),
    ("2026-06-16T01:30Z", 103, 108, 102, 107),
    ("2026-06-16T01:35Z", 107, 110, 105, 109),
    ("2026-06-16T01:40Z", 109, 110, 101, 103),
    ("2026-06-16T01:45Z", 103, 104, 95, 96),
    ("2026-06-16T01:50Z", 96, 101, 95, 100),
])


def test_H5_clean_armed_sequence():
    st = advance(SUP, M15_TAG_SWEEP, M5_SHIFT_ENTRY, [SUP], BTC,
                 stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "ARMED"
    assert st.plan is not None and st.plan["stop"] == 112.0 + BTC.stop_buffer


def test_H1_premature_tag_stays_tagged():
    m15 = _m15([("2026-06-16T00:00Z", 100, 96, 98),
                ("2026-06-16T00:15Z", 104, 99, 102),
                ("2026-06-16T00:30Z", 105, 100, 103)])
    st = advance(SUP, m15, _m5([]), [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "TAGGED"


def test_H2_out_of_order_shift_does_not_arm():
    m15 = _m15([("2026-06-16T00:00Z", 100, 96, 98),
                ("2026-06-16T00:15Z", 104, 99, 102)])
    st = advance(SUP, m15, M5_SHIFT_ENTRY, [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "TAGGED"


def test_H3_stale_reset_when_sweep_times_out():
    rows = [("2026-06-16T00:00Z", 100, 96, 98), ("2026-06-16T00:15Z", 104, 99, 102)]
    for i in range(20):
        rows.append((f"2026-06-16T{1 + i // 4:02d}:{15 * (i % 4):02d}Z", 105, 101, 103))
    st = advance(SUP, _m15(rows), _m5([]), [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "STALE"


def test_H4_invalidation_on_distal_break():
    m15 = _m15([("2026-06-16T00:00Z", 100, 96, 98),
                ("2026-06-16T00:15Z", 104, 99, 102),
                ("2026-06-16T00:30Z", 120, 110, 118)])
    st = advance(SUP, m15, _m5([]), [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "INVALIDATED"
