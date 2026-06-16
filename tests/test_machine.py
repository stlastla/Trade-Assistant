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

# After the M15 sweep (01:15): a confirmed fractal swing low at 01:35 (low 100),
# then a close below it (96 < 100 = down break / shift), then a bullish candle (entry).
M5_SHIFT_ENTRY = _m5([
    ("2026-06-16T01:20Z", 110, 112, 108, 109),
    ("2026-06-16T01:25Z", 109, 110, 106, 107),
    ("2026-06-16T01:30Z", 107, 108, 104, 105),
    ("2026-06-16T01:35Z", 105, 106, 100, 103),   # swing low (100)
    ("2026-06-16T01:40Z", 103, 108, 102, 107),   # bounce
    ("2026-06-16T01:45Z", 107, 110, 105, 109),   # confirms the swing low
    ("2026-06-16T01:50Z", 109, 110, 94, 96),     # close 96 < 100 -> down break (shift)
    ("2026-06-16T01:55Z", 96, 102, 95, 101),     # bullish opposing candle -> entry
])


def test_H5_clean_armed_sequence():
    st = advance(SUP, M15_TAG_SWEEP, M5_SHIFT_ENTRY, [SUP], BTC,
                 stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "ARMED"
    assert st.plan is not None and st.plan["stop"] == 112.0 + BTC.stop_buffer


def test_H6_demand_armed_sequence():
    # Long mirror: demand band [88,100]; M15 sweeps the swing low (87<90, closes back above),
    # M5 prints an up-break (close 104 > swing high 100), then the first bearish M5 candle = entry.
    dem = AOI("H4", "demand", 100.0, 88.0, "h4_swing_low")
    m15 = _m15([("2026-06-16T00:00Z", 104, 100, 102),
                ("2026-06-16T00:15Z", 101, 96, 98),
                ("2026-06-16T00:30Z", 97, 90, 92),    # swing low 90
                ("2026-06-16T00:45Z", 100, 95, 98),
                ("2026-06-16T01:00Z", 101, 97, 99),
                ("2026-06-16T01:15Z", 94, 87, 93),     # bullish sweep of 90
                ("2026-06-16T01:30Z", 96, 92, 94)])
    m5 = _m5([("2026-06-16T01:20Z", 90, 92, 88, 91),
              ("2026-06-16T01:25Z", 91, 94, 90, 93),
              ("2026-06-16T01:30Z", 93, 96, 92, 95),
              ("2026-06-16T01:35Z", 95, 100, 94, 97),  # swing high 100
              ("2026-06-16T01:40Z", 97, 98, 92, 93),
              ("2026-06-16T01:45Z", 93, 95, 90, 91),   # confirms swing high
              ("2026-06-16T01:50Z", 91, 106, 90, 104), # close 104 > 100 -> up break (shift)
              ("2026-06-16T01:55Z", 104, 105, 98, 99)])  # bearish opposing candle -> entry
    st = advance(dem, m15, m5, [dem], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "ARMED"
    assert st.plan["stop"] == 88.0 - BTC.stop_buffer    # HTF distal - buffer (below)


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
