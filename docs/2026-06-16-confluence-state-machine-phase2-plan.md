# Confluence Trigger State Machine Phase 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-AOI trigger state machine (`WATCHING→TAGGED→SWEPT→SHIFTED→ARMED`, + `INVALIDATED`/`STALE`) that enforces tag→sweep→shift ordering and fires grade-stamped entry alerts, layered on the Phase 1 scorer.

**Architecture:** New pure modules — `triggers.py` (detectors), `machine.py` (`advance` re-derives the furthest state reached from the M15/M5 frames), `trade_plan.py` (entry/stop/target/RR) — plus one stateful `tracker.py` that holds `{aoi_key → MachineState}` across the 5-min ticks, diffs prior→new to emit stage events, and resets each morning. The app wires fetch(M15,M5) → score_pass → tracker → grade-gated notifications → state.json. The existing sweep watcher is untouched.

**Tech Stack:** Python 3.9+, pandas. pytest. Pure detectors/machine tested with synthetic M15/M5 fixtures (the source spec's H1–H5).

**Spec:** `docs/2026-06-16-confluence-state-machine-phase2-design.md`

**Repo & conventions:** Work in the **Trade Assistant** repo. Flat layout, flat imports, tests in `tests/test_<module>.py`, pure functions + docstrings. Run with `./venv/bin/python -m pytest`.

**Reused interfaces (already in the repo — do not change):**
- `aoi.AOI(timeframe, side('supply'|'demand'), proximal, distal, source, origin, score, label, gate, breakdown)`; `aoi.band_lo_hi(aoi) -> (lo, hi)`.
- `liquidity.detect_sweeps(df) -> [{index, direction('bearish'|'bullish'), level, swing_index}]` (`bearish` = swept a swing HIGH then closed back below).
- `structure.detect_structure_breaks(df) -> [{index, direction('up'|'down'), kind, level, swing_index}]`.
- `engine.score_pass(weekly, daily, h4, etf, now, symbol) -> [AOI]` (scored; `gate` is `"pass"`/`"no-trade"`).
- `state.build_state(...)`; `fetch_data.fetch_recent(interval, limit)`.
- Kline frames have columns `open_time, open, high, low, close, close_time` (UTC).

---

### Task 1: `aoi.aoi_key` — stable per-AOI identity

**Files:** Modify `aoi.py`; Test `tests/test_aoi_key.py`

- [ ] **Step 1: Write the failing test**

```python
from aoi import AOI, aoi_key


def test_aoi_key_is_stable_and_distinct():
    a = AOI("D", "supply", 70000.004, 70120.0, "daily_swing_high")
    b = AOI("D", "supply", 70000.001, 70120.0, "daily_swing_high")
    c = AOI("D", "demand", 60000.0, 59880.0, "daily_swing_low")
    assert aoi_key(a) == "daily_swing_high:70000.0"   # rounded, type-independent
    assert aoi_key(a) == aoi_key(b)                    # within rounding = same level
    assert aoi_key(c) == "daily_swing_low:60000.0"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_aoi_key.py -v`
Expected: FAIL — `ImportError: cannot import name 'aoi_key'`.

- [ ] **Step 3: Add `aoi_key` to `aoi.py`**

```python
def aoi_key(aoi: "AOI") -> str:
    """Stable id used to carry machine state across ticks (price rounded to 1dp)."""
    return f"{aoi.source}:{round(float(aoi.proximal), 1)}"
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_aoi_key.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add aoi.py tests/test_aoi_key.py
git commit -m "feat: aoi_key stable identity for cross-tick machine state"
```

---

### Task 2: `triggers.py` — `tag_time` and `etf_sweep`

**Files:** Create `triggers.py`; Test `tests/test_triggers_tag_sweep.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
from aoi import AOI
from triggers import tag_time, etf_sweep


def _m15(rows):  # rows: (open_iso, high, low, close)
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows], "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
    })


SUP = AOI("H4", "supply", 100.0, 112.0, "h4_swing_high")  # band [100,112]


def test_tag_time_when_high_enters_band():
    df = _m15([("2026-06-16T00:00Z", 95, 90, 93),     # below band
              ("2026-06-16T00:15Z", 104, 98, 101)])   # high 104 enters [100,112]
    assert tag_time(SUP, df) == pd.Timestamp("2026-06-16T00:15Z")


def test_tag_time_none_when_untouched():
    df = _m15([("2026-06-16T00:00Z", 95, 90, 93)])
    assert tag_time(SUP, df) is None


def test_etf_sweep_finds_bearish_sweep_after_tag_near_aoi():
    # swing high at idx2 (high=110, inside band); bar5 spikes to 113 then closes back below
    df = _m15([("2026-06-16T00:00Z", 100, 96, 98),
               ("2026-06-16T00:15Z", 104, 99, 102),
               ("2026-06-16T00:30Z", 110, 103, 108),
               ("2026-06-16T00:45Z", 105, 100, 102),
               ("2026-06-16T01:00Z", 103, 99, 101),
               ("2026-06-16T01:15Z", 113, 106, 107)])  # sweep of the 110 high
    after = pd.Timestamp("2026-06-16T00:00Z")
    t = etf_sweep(SUP, df, after, tol=5.0)
    assert t == pd.Timestamp("2026-06-16T01:15Z")


def test_etf_sweep_none_before_after_marker():
    df = _m15([("2026-06-16T00:00Z", 100, 96, 98),
               ("2026-06-16T00:15Z", 110, 99, 102),
               ("2026-06-16T00:30Z", 113, 104, 105)])
    after = pd.Timestamp("2026-06-16T05:00Z")   # everything is before -> none
    assert etf_sweep(SUP, df, after, tol=5.0) is None
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_triggers_tag_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triggers'`.

- [ ] **Step 3: Create `triggers.py`**

```python
"""Detectors for the trigger state machine. Pure functions over kline frames.

Short case (supply AOI): tag = price enters the band; sweep = a bearish liquidity
run of a swing high at/near the AOI; shift = a downward MSS/CHoCH; entry = the first
bullish (opposing) candle of the rejected rally. Long case mirrors every comparison.
"""
from typing import Optional

import pandas as pd

from aoi import AOI, band_lo_hi
from liquidity import detect_sweeps
from structure import detect_structure_breaks


def tag_time(aoi: AOI, m15: pd.DataFrame) -> Optional[pd.Timestamp]:
    """open_time of the first M15 candle whose range overlaps the AOI band, else None."""
    lo, hi = band_lo_hi(aoi)
    for t, h, l in zip(m15["open_time"], m15["high"], m15["low"]):
        if h >= lo and l <= hi:
            return pd.Timestamp(t)
    return None


def etf_sweep(aoi: AOI, m15: pd.DataFrame, after: pd.Timestamp, tol: float) -> Optional[pd.Timestamp]:
    """open_time of the first directionally-relevant sweep after `after` whose swept
    level sits within `tol` of the AOI band. Supply wants a bearish sweep (swept high),
    demand a bullish sweep (swept low)."""
    want = "bearish" if aoi.side == "supply" else "bullish"
    lo, hi = band_lo_hi(aoi)
    times = m15["open_time"].to_numpy()
    for s in detect_sweeps(m15):
        t = pd.Timestamp(times[s["index"]])
        if t <= after or s["direction"] != want:
            continue
        if (lo - tol) <= s["level"] <= (hi + tol):
            return t
    return None
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_triggers_tag_sweep.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add triggers.py tests/test_triggers_tag_sweep.py
git commit -m "feat: tag_time + etf_sweep detectors"
```

---

### Task 3: `triggers.py` — `etf_shift` and `first_opposing_candle`

**Files:** Modify `triggers.py`; Test `tests/test_triggers_shift_entry.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
from aoi import AOI
from triggers import etf_shift, first_opposing_candle


def _m5(rows):  # rows: (open_iso, open, high, low, close)
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "open": [r[1] for r in rows], "high": [r[2] for r in rows],
        "low": [r[3] for r in rows], "close": [r[4] for r in rows],
    })


SUP = AOI("H4", "supply", 100.0, 112.0, "h4_swing_high")


def test_etf_shift_finds_down_break_after_marker():
    # rising then a decisive lower close breaks a recent swing low -> 'down' break
    df = _m5([("2026-06-16T00:00Z", 100, 110, 99, 108),
              ("2026-06-16T00:05Z", 108, 120, 107, 118),
              ("2026-06-16T00:10Z", 118, 122, 110, 112),
              ("2026-06-16T00:15Z", 112, 113, 100, 101),
              ("2026-06-16T00:20Z", 101, 102, 92, 94),
              ("2026-06-16T00:25Z", 94, 96, 88, 90)])
    after = pd.Timestamp("2026-06-16T00:00Z")
    t = etf_shift(SUP, df, after)
    assert t is not None and t > after


def test_etf_shift_none_when_no_down_break():
    df = _m5([("2026-06-16T00:00Z", 100, 110, 99, 108),
              ("2026-06-16T00:05Z", 108, 120, 107, 118),
              ("2026-06-16T00:10Z", 118, 125, 116, 124)])
    assert etf_shift(SUP, df, pd.Timestamp("2026-06-16T00:00Z")) is None


def test_first_opposing_candle_is_first_bullish_for_short():
    df = _m5([("2026-06-16T00:00Z", 110, 111, 104, 105),   # bearish
              ("2026-06-16T00:05Z", 105, 106, 100, 101),   # bearish
              ("2026-06-16T00:10Z", 101, 107, 100, 106),   # bullish <- entry candle
              ("2026-06-16T00:15Z", 106, 108, 103, 104)])
    after = pd.Timestamp("2026-06-15T00:00Z")
    c = first_opposing_candle(SUP, df, after)
    assert c["time"] == pd.Timestamp("2026-06-16T00:10Z")
    assert c["low"] == 100.0 and c["high"] == 107.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_triggers_shift_entry.py -v`
Expected: FAIL — `ImportError: cannot import name 'etf_shift'`.

- [ ] **Step 3: Add to `triggers.py`**

```python
def etf_shift(aoi: AOI, m5: pd.DataFrame, after: pd.Timestamp) -> Optional[pd.Timestamp]:
    """open_time of the first MSS/CHoCH after `after` in the trade direction (down for a
    supply/short, up for a demand/long). Pluggable: a RelicusRoad Signal Line reader could
    replace detect_structure_breaks here."""
    want = "down" if aoi.side == "supply" else "up"
    times = m5["open_time"].to_numpy()
    for b in detect_structure_breaks(m5):
        t = pd.Timestamp(times[b["index"]])
        if t > after and b["direction"] == want:
            return t
    return None


def first_opposing_candle(aoi: AOI, m5: pd.DataFrame, after: pd.Timestamp) -> Optional[dict]:
    """First opposing candle after `after`: a bullish candle for a short (entry triggers
    below its low), a bearish candle for a long (entry above its high). Returns
    {time, low, high} or None."""
    want_bull = aoi.side == "supply"
    for t, o, h, l, c in zip(m5["open_time"], m5["open"], m5["high"], m5["low"], m5["close"]):
        if pd.Timestamp(t) <= after:
            continue
        if (c > o) == want_bull:
            return {"time": pd.Timestamp(t), "low": float(l), "high": float(h)}
    return None
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_triggers_shift_entry.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add triggers.py tests/test_triggers_shift_entry.py
git commit -m "feat: etf_shift + first_opposing_candle detectors"
```

---

### Task 4: `trade_plan.py` — entry / HTF stop / target / R:R

**Files:** Create `trade_plan.py`; Test `tests/test_trade_plan.py`

- [ ] **Step 1: Write the failing test**

```python
from aoi import AOI
from trade_plan import build_plan
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def test_short_plan_uses_htf_stop_and_next_demand_target():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    target = AOI("D", "demand", 67000.0, 66880.0, "daily_swing_low")
    entry_candle = {"time": None, "low": 69800.0, "high": 70050.0}
    plan = build_plan(supply, entry_candle, [supply, target], BTC)
    assert plan["entry"] == 69800.0                       # below the bullish candle
    assert plan["stop"] == 70120.0 + BTC.stop_buffer      # HTF distal + buffer (above)
    assert plan["target"] == 67000.0                      # next opposing AOI
    # rr = (69800-67000) / (stop-69800)
    risk = (70120.0 + BTC.stop_buffer) - 69800.0
    assert abs(plan["rr"] - (2800.0 / risk)) < 1e-6


def test_long_plan_mirrors():
    demand = AOI("D", "demand", 60000.0, 59880.0, "daily_swing_low")
    target = AOI("D", "supply", 63000.0, 63120.0, "daily_swing_high")
    entry_candle = {"time": None, "low": 59950.0, "high": 60200.0}
    plan = build_plan(demand, entry_candle, [demand, target], BTC)
    assert plan["entry"] == 60200.0                       # above the bearish candle
    assert plan["stop"] == 59880.0 - BTC.stop_buffer      # HTF distal - buffer (below)
    assert plan["target"] == 63000.0


def test_no_target_yields_none_target_and_zero_rr():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    plan = build_plan(supply, {"low": 69800.0, "high": 70050.0}, [supply], BTC)
    assert plan["target"] is None and plan["rr"] == 0.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_trade_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trade_plan'`.

- [ ] **Step 3: Create `trade_plan.py`**

```python
"""Build the ARMED trade plan: entry, HTF-wide stop, next-opposing-AOI target, R:R."""
from typing import List, Optional

from aoi import AOI
from instruments import Instrument


def _next_opposing(aoi: AOI, aois: List[AOI]) -> Optional[float]:
    """Nearest opposing-side AOI proximal in the profit direction (demand below a supply,
    supply above a demand)."""
    want = "demand" if aoi.side == "supply" else "supply"
    cands = []
    for o in aois:
        if o is aoi or o.side != want:
            continue
        if aoi.side == "supply" and o.proximal < aoi.proximal:
            cands.append(o.proximal)
        elif aoi.side == "demand" and o.proximal > aoi.proximal:
            cands.append(o.proximal)
    if not cands:
        return None
    return max(cands) if aoi.side == "supply" else min(cands)


def build_plan(aoi: AOI, entry_candle: dict, aois: List[AOI], inst: Instrument) -> dict:
    """entry below the opposing candle (short) / above it (long); stop at the HTF distal
    edge ± stop_buffer; target the next opposing AOI; R:R off the HTF stop."""
    if aoi.side == "supply":
        entry = entry_candle["low"]
        stop = aoi.distal + inst.stop_buffer
    else:
        entry = entry_candle["high"]
        stop = aoi.distal - inst.stop_buffer
    target = _next_opposing(aoi, aois)
    risk = abs(entry - stop)
    rr = abs(entry - target) / risk if (target is not None and risk > 0) else 0.0
    return {"entry": entry, "stop": stop, "target": target, "rr": rr}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_trade_plan.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add trade_plan.py tests/test_trade_plan.py
git commit -m "feat: trade_plan (entry/HTF-stop/target/RR)"
```

---

### Task 5: `machine.py` — `MachineState` + `advance` (the spec's H1–H5)

**Files:** Create `machine.py`; Test `tests/test_machine.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
from aoi import AOI
from machine import MachineState, advance
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")
# AOI band [100, 112]; distal 112. Use small prices; stop_buffer won't matter for state.
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


# M15 series: tags the band then sweeps the 110 high at 01:15 (spike 113 close 107)
M15_TAG_SWEEP = _m15([
    ("2026-06-16T00:00Z", 100, 96, 98),
    ("2026-06-16T00:15Z", 104, 99, 102),   # tag (enters band)
    ("2026-06-16T00:30Z", 110, 103, 108),  # swing high 110
    ("2026-06-16T00:45Z", 105, 100, 102),
    ("2026-06-16T01:00Z", 103, 99, 101),
    ("2026-06-16T01:15Z", 113, 106, 107),  # sweep of 110, close back below
    ("2026-06-16T01:30Z", 108, 104, 106),
])

# M5 series after the sweep: a down MSS, then a bullish (opposing) candle for entry
M5_SHIFT_ENTRY = _m5([
    ("2026-06-16T01:20Z", 107, 109, 100, 101),
    ("2026-06-16T01:25Z", 101, 103, 92, 93),   # down break / shift
    ("2026-06-16T01:30Z", 93, 99, 92, 98),     # bullish opposing candle -> entry
    ("2026-06-16T01:35Z", 98, 100, 95, 96),
])


def test_H5_clean_armed_sequence():
    st = advance(SUP, M15_TAG_SWEEP, M5_SHIFT_ENTRY, [SUP], BTC,
                 stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "ARMED"
    assert st.plan is not None and st.plan["stop"] == 112.0 + BTC.stop_buffer


def test_H1_premature_tag_stays_tagged():
    # tagged but never sweeps; within timeout -> TAGGED, no arm
    m15 = _m15([("2026-06-16T00:00Z", 100, 96, 98),
                ("2026-06-16T00:15Z", 104, 99, 102),   # tag only
                ("2026-06-16T00:30Z", 105, 100, 103)])
    st = advance(SUP, m15, _m5([]), [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "TAGGED"


def test_H2_out_of_order_shift_does_not_arm():
    # M5 shift exists but the M15 never sweeps -> cannot pass SWEPT, so never ARMED
    m15 = _m15([("2026-06-16T00:00Z", 100, 96, 98),
                ("2026-06-16T00:15Z", 104, 99, 102)])   # tag, no sweep
    st = advance(SUP, m15, M5_SHIFT_ENTRY, [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "TAGGED"   # not SHIFTED/ARMED


def test_H3_stale_reset_when_sweep_times_out():
    # tagged at 00:15, no sweep, and many bars pass -> STALE
    rows = [("2026-06-16T00:00Z", 100, 96, 98), ("2026-06-16T00:15Z", 104, 99, 102)]
    for i in range(20):  # 20 bars after the tag, none sweeping
        rows.append((f"2026-06-16T{1 + i // 4:02d}:{15 * (i % 4):02d}Z", 105, 101, 103))
    st = advance(SUP, _m15(rows), _m5([]), [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "STALE"


def test_H4_invalidation_on_distal_break():
    # price closes above the distal edge (112) -> INVALIDATED
    m15 = _m15([("2026-06-16T00:00Z", 100, 96, 98),
                ("2026-06-16T00:15Z", 104, 99, 102),
                ("2026-06-16T00:30Z", 120, 110, 118)])  # close 118 > distal 112
    st = advance(SUP, m15, _m5([]), [SUP], BTC, stale_sweep_bars=12, stale_shift_bars=12)
    assert st.state == "INVALIDATED"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_machine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'machine'`.

- [ ] **Step 3: Create `machine.py`**

```python
"""Per-AOI trigger state machine. `advance` re-derives the furthest state reached from
the current M15/M5 frames; the tracker diffs prior vs new to emit stage events.

States: WATCHING -> TAGGED -> SWEPT -> SHIFTED -> ARMED  (+ INVALIDATED, STALE).
Ordering is strict: a shift before a sweep cannot advance (we only look for the shift on
bars after the sweep). Short case; long mirrors via the detectors.
"""
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from aoi import AOI, band_lo_hi
from triggers import tag_time, etf_sweep, etf_shift, first_opposing_candle
from trade_plan import build_plan


@dataclass
class MachineState:
    state: str = "WATCHING"
    tag_time: Optional[pd.Timestamp] = None
    swept_time: Optional[pd.Timestamp] = None
    shift_time: Optional[pd.Timestamp] = None
    plan: Optional[dict] = None


def _distal_broken(aoi: AOI, m15: pd.DataFrame) -> bool:
    """Price closed beyond the HTF distal edge (a real break, not a wick)."""
    closes = m15["close"].to_numpy()
    if aoi.side == "supply":
        return bool((closes > aoi.distal).any())
    return bool((closes < aoi.distal).any())


def _bars_after(frame: pd.DataFrame, t: pd.Timestamp) -> int:
    return int((frame["open_time"] > t).sum())


def advance(aoi: AOI, m15: pd.DataFrame, m5: pd.DataFrame, aois, inst,
            stale_sweep_bars: int, stale_shift_bars: int) -> MachineState:
    if _distal_broken(aoi, m15):
        return MachineState("INVALIDATED")

    tagged = tag_time(aoi, m15)
    if tagged is None:
        return MachineState("WATCHING")

    swept = etf_sweep(aoi, m15, tagged, tol=inst.stop_buffer)
    if swept is None:
        if _bars_after(m15, tagged) > stale_sweep_bars:
            return MachineState("STALE", tag_time=tagged)
        return MachineState("TAGGED", tag_time=tagged)

    shifted = etf_shift(aoi, m5, swept)
    if shifted is None:
        if _bars_after(m5, swept) > stale_shift_bars:
            return MachineState("STALE", tag_time=tagged, swept_time=swept)
        return MachineState("SWEPT", tag_time=tagged, swept_time=swept)

    entry = first_opposing_candle(aoi, m5, shifted)
    if entry is None:
        return MachineState("SHIFTED", tag_time=tagged, swept_time=swept, shift_time=shifted)

    plan = build_plan(aoi, entry, aois, inst)
    return MachineState("ARMED", tag_time=tagged, swept_time=swept, shift_time=shifted, plan=plan)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_machine.py -v`
Expected: 5 passed. (If H4 also matches the sweep path, note `_distal_broken` is checked first and returns INVALIDATED before tagging — that ordering is intentional.)

- [ ] **Step 5: Commit**

```bash
git add machine.py tests/test_machine.py
git commit -m "feat: trigger state machine advance (H1-H5)"
```

---

### Task 6: `tracker.py` — cross-tick state + stage events

**Files:** Create `tracker.py`; Test `tests/test_tracker.py`

- [ ] **Step 1: Write the failing test**

```python
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
    # WATCHING -> TAGGED is a transition -> one event
    assert len(ev1) == 1 and ev1[0][1].state == "TAGGED"
    # second identical advance -> no new event (state unchanged)
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
    tr.advance_all([], EMPTY_M5, EMPTY_M5, BTC, 12, 12)   # aoi gone
    assert tr.states == {}
    tr.advance_all([aoi], _m15([("2026-06-16T00:15Z", 104, 99, 102)]), EMPTY_M5, BTC, 12, 12)
    tr.reset()
    assert tr.states == {}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tracker'`.

- [ ] **Step 3: Create `tracker.py`**

```python
"""Holds per-AOI machine state across the 5-min ticks. Matches fresh scored AOIs by
aoi_key, advances each, and emits (aoi, new_state, prior_state_name) on transitions."""
from typing import List

from aoi import AOI, aoi_key
from machine import MachineState, advance


class Tracker:
    def __init__(self):
        self.states = {}   # aoi_key -> MachineState

    def reset(self):
        self.states = {}

    def advance_all(self, scored_aois: List[AOI], m15, m5, inst,
                    stale_sweep_bars: int, stale_shift_bars: int) -> list:
        tradeable = [a for a in scored_aois if a.gate == "pass"]
        events = []
        live = set()
        for aoi in tradeable:
            k = aoi_key(aoi)
            live.add(k)
            prior = self.states.get(k, MachineState())
            new = advance(aoi, m15, m5, tradeable, inst, stale_sweep_bars, stale_shift_bars)
            self.states[k] = new
            if new.state != prior.state:
                events.append((aoi, new, prior.state))
        for k in list(self.states):          # drop AOIs that no longer pass / exist
            if k not in live:
                del self.states[k]
        return events
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_tracker.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: tracker carries machine state across ticks + emits events"
```

---

### Task 7: Config + AOI state/plan fields + state.json serialization

**Files:** Modify `app_config.py`, `aoi.py`, `state.py`; Test `tests/test_state_machine_fields.py`

- [ ] **Step 1: Add config to `app_config.py`**

Append after the existing static knobs:

```python
# --- Phase 2 state machine ---
ENTRY_TF = "5m"
SWEEP_TF = "15m"
MIN_ALERT_GRADE = "valid"            # "A+" | "valid" | "weak"
ALERT_STAGES = ("SWEPT", "SHIFTED", "ARMED")
STALE_SWEEP_BARS = 12                # M15 bars in TAGGED before STALE (~3h)
STALE_SHIFT_BARS = 12                # M5 bars in SWEPT before STALE (~1h)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_state_machine_fields.py`:

```python
from aoi import AOI
import state


def test_aoi_carries_state_and_plan_in_state_json():
    a = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    a.gate, a.label = "pass", "A+"
    a.state = "ARMED"
    a.plan = {"entry": 69800.0, "stop": 70180.0, "target": 67000.0, "rr": 2.5}
    payload = state.build_state(price=69000.0, levels=[], zones=[], bias=None,
                                fired=[], last_alert={}, updated_at="x", aois=[a])
    d = payload["aois"][0]
    assert d["state"] == "ARMED"
    assert d["plan"]["rr"] == 2.5


def test_aoi_state_defaults_when_unset():
    a = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    payload = state.build_state(price=1.0, levels=[], zones=[], bias=None,
                                fired=[], last_alert={}, updated_at="x", aois=[a])
    assert payload["aois"][0]["state"] == "WATCHING"
    assert payload["aois"][0]["plan"] is None
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_state_machine_fields.py -v`
Expected: FAIL — `AttributeError: 'AOI' object has no attribute 'state'`.

- [ ] **Step 4: Add `state`/`plan` fields to `AOI` (end of the dataclass, after `breakdown`)**

In `aoi.py`, the `AOI` dataclass currently ends with `breakdown: dict = field(default_factory=dict)`. Add two fields AFTER it (so positional construction in existing tests is unaffected):

```python
    state: str = "WATCHING"
    plan: dict = None
```

- [ ] **Step 5: Serialize them in `state._aoi_to_dict`**

In `state.py`, extend `_aoi_to_dict` to include the two fields:

```python
def _aoi_to_dict(a) -> dict:
    return {"timeframe": a.timeframe, "side": a.side,
            "proximal": a.proximal, "distal": a.distal, "source": a.source,
            "gate": a.gate, "score": a.score, "label": a.label,
            "breakdown": a.breakdown, "state": a.state, "plan": a.plan}
```

- [ ] **Step 6: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_state_machine_fields.py -v`
Expected: 2 passed. Then run the full suite `./venv/bin/python -m pytest -q` — all prior tests must still pass (the new AOI fields are defaulted; deepcopy in `scoring.score_aoi` copies them).

- [ ] **Step 7: Commit**

```bash
git add app_config.py aoi.py state.py tests/test_state_machine_fields.py
git commit -m "feat: state-machine config + AOI state/plan fields in state.json"
```

---

### Task 8: App integration — run the tracker each tick, fire grade-gated alerts

**Files:** Modify `app.py`. No unit test (GUI/daemon); verify by `import app` + reading.

- [ ] **Step 1: Read `app.py`** to see the current `__init__`, `remark_now`, `tick`, `_emit`, `_write_state`, and the settings/notification wiring.

- [ ] **Step 2: Add a grade-rank helper + tracker wiring**

Near the top of `app.py` (after imports), add:

```python
from tracker import Tracker
from aoi import aoi_key

_GRADE_RANK = {"weak": 1, "valid": 2, "A+": 3}


def _grade_ok(label: str, minimum: str) -> bool:
    return _GRADE_RANK.get(label, 0) >= _GRADE_RANK.get(minimum, 99)
```

In `__init__`, alongside `self.aois = []`, add:

```python
        self.tracker = Tracker()
        self.machine_fired = set()   # (aoi_key, stage) already notified this session
```

- [ ] **Step 3: Reset the tracker on the morning re-mark**

In `remark_now`, inside the `try:` after `self.aois = engine.score_pass(...)` and `self.bias_tf = ...`, add:

```python
            self.tracker.reset()
            self.machine_fired = set()
```

- [ ] **Step 4: Advance the machine each tick and fire alerts**

In `tick`, after the existing sweep-`scan` block and before `self._write_state(...)`, add (inside the existing try/except so a failure can't kill the timer):

```python
            # Phase 2: advance the per-AOI trigger state machine on M15 + M5
            m15c = closed                                   # closed M15 bars (already computed)
            m5 = fetch_recent("5m", limit=300).iloc[:-1]    # drop in-progress M5
            inst = get_instrument("BTCUSDT")
            events = self.tracker.advance_all(self.aois, m15c, m5, inst,
                                              cfg.STALE_SWEEP_BARS, cfg.STALE_SHIFT_BARS)
            for aoi, st, _prior in events:
                aoi.state, aoi.plan = st.state, st.plan
                self._emit_machine(aoi, st)
            # reflect current machine state on every tradeable AOI for the chart
            for aoi in self.aois:
                ms = self.tracker.states.get(aoi_key(aoi))
                if ms is not None:
                    aoi.state, aoi.plan = ms.state, ms.plan
```

Add `from instruments import get_instrument` to the imports if not already present (it is used here).

- [ ] **Step 5: Add the `_emit_machine` method**

Add to `WatcherApp`:

```python
    def _emit_machine(self, aoi, st):
        if st.state not in cfg.ALERT_STAGES:
            return
        if not _grade_ok(aoi.label, cfg.MIN_ALERT_GRADE):
            return
        side = "short" if aoi.side == "supply" else "long"
        title = f"⚡ {st.state} — {aoi.label} {side} @ {aoi.source} {aoi.proximal:,.0f}"
        if st.state == "ARMED" and st.plan:
            p = st.plan
            tgt = f"{p['target']:,.0f}" if p["target"] is not None else "—"
            body = f"entry {p['entry']:,.0f} · stop {p['stop']:,.0f} · target {tgt} · {p['rr']:.1f}R"
        else:
            body = "entry forming"
        key = (aoi_key(aoi), st.state)
        if key in self.machine_fired:
            return
        self.machine_fired.add(key)
        if self.settings["notifications_enabled"]:
            rumps.notification(title, "", body, sound=self.settings["alert_sound_enabled"])
```

- [ ] **Step 6: Verify (no GUI launch)**

Run: `./venv/bin/python -c "import app; print('import OK')"`
Expected: `import OK`.
Run: `./venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: run trigger state machine in app; grade-gated stage alerts"
```

---

### Task 9: Chart — show machine state on each AOI line

**Files:** Modify `chart/chart.js`. No unit test.

- [ ] **Step 1: Update the AOI rendering to include state in the title and bolden ARMED**

In `chart/chart.js`, the AOI mapping currently builds `title: \`${a.label} ${a.source}\``. Replace that block's `.map(...)` body so the title shows state and ARMED is bold:

```javascript
  window._aoiLines = (s.aois || []).map(a => {
    const isNoTrade = a.label === 'no-trade';
    const armed = a.state === 'ARMED';
    const st = (a.state && a.state !== 'WATCHING') ? ' · ' + a.state : '';
    return candles.createPriceLine({
      price: a.proximal,
      color: LABEL_COLOR[a.label] || '#6e7681',
      lineWidth: armed ? 3 : (a.label === 'A+' ? 2 : 1),
      lineStyle: isNoTrade ? LightweightCharts.LineStyle.Dotted : LightweightCharts.LineStyle.Solid,
      title: `${a.label} ${a.source}${st}`,
    });
  });
```

- [ ] **Step 2: Verify**

Run: `./venv/bin/python -c "import app; print('import OK')"` (sanity — JS isn't imported, but confirm nothing else broke) and `./venv/bin/python -m pytest -q` (all pass).

- [ ] **Step 3: Commit**

```bash
git add chart/chart.js
git commit -m "feat: show trigger state on AOI lines (ARMED bold)"
```

---

### Task 10: README — document Phase 2

**Files:** Modify `README.md`

- [ ] **Step 1: Append to `README.md`**

```markdown
## Trigger state machine + entry alerts (Phase 2)
Each gate-passing AOI runs a per-level state machine that enforces **tag → sweep → shift**
in order before it can become an entry:

`WATCHING → TAGGED → SWEPT → SHIFTED → ARMED` (+ `INVALIDATED` / `STALE`).

- **Tag:** price enters the AOI band. **Sweep:** M15 runs the level's liquidity.
  **Shift:** M5 prints an MSS/CHoCH in the trade direction. **Armed:** first opposing
  candle — fires an entry alert with entry / stop (HTF distal edge) / target / R:R.
- Notifications fire on **SWEPT / SHIFTED / ARMED** (config `ALERT_STAGES`) for AOIs graded
  ≥ `MIN_ALERT_GRADE` (default `valid`); `weak` runs silently on the chart. Each alert is
  grade-stamped. The chart shows each AOI's live state; ARMED lines are bold.
- Timeouts: `STALE_SWEEP_BARS` (M15) and `STALE_SHIFT_BARS` (M5). All in `app_config.py`.

A stale sweep with no shift, or an out-of-order shift, never arms — "price at a level" is
not a trade until the full ordered sequence fires.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the trigger state machine (Phase 2)"
```

---

## Self-Review notes

- **Spec coverage:** persistence/aoi_key (Task 1); detectors tag/sweep/shift/entry (Tasks 2–3); trade plan with HTF stop + next-opposing target + RR (Task 4); state machine with strict ordering, timeouts, invalidation, H1–H5 (Task 5); tracker cross-tick state + events + drop/reset (Task 6); config + AOI state/plan + state.json (Task 7); app integration with grade-gated SWEPT/SHIFTED/ARMED alerts + per-(AOI,stage) de-dupe + tracker reset on re-mark (Task 8); chart state display (Task 9); docs (Task 10). Out-of-scope items (Road feed, auto-exec, backtest, multi-symbol live) intentionally absent.
- **Type consistency:** `MachineState(state, tag_time, swept_time, shift_time, plan)`; `advance(aoi, m15, m5, aois, inst, stale_sweep_bars, stale_shift_bars) -> MachineState`; detectors return `Optional[pd.Timestamp]` (tag/sweep/shift) and `Optional[dict]` (entry candle: `{time, low, high}`); `build_plan(aoi, entry_candle, aois, inst) -> {entry, stop, target, rr}`; `Tracker.advance_all(...) -> [(aoi, MachineState, prior_state_str)]`; `aoi_key(aoi)`; AOI gains `state`/`plan`. Used identically across tasks and `app.py`.
- **No placeholders:** every code step is complete and runnable.
```
