# Confluence Scoring Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure confluence-scoring layer that gates each AOI by per-timeframe bias and labels it `A+`/`valid`/`weak`/`no-trade` from six weighted factors — surfaced on the chart, with no new entry alerts (state machine is Phase 2).

**Architecture:** New pure, independently-testable modules (`instruments.py`, `bias.py`, `aoi.py`, `gate.py`, `factors.py`, `scoring.py`) layered on top of the existing engine (`levels.py`, `liquidity.py`, `fvg.py`, `structure.py`). A scoring pass in `engine.py` builds a per-TF bias map + banded AOIs, scores them, and writes results to `state.json`; the chart colors AOIs by label. The existing `watcher.scan` sweep alert is untouched.

**Tech Stack:** Python 3.9+, pandas, numpy. pytest. All scoring logic is pure (no I/O), tested with synthetic OHLC+AOI fixtures.

**Spec:** `docs/2026-06-16-confluence-scoring-phase1-design.md`

**Repo & conventions:** Work in the **Trade Assistant** repo. Flat layout (no `src/`), flat imports (`from aoi import AOI`), tests in `tests/test_<module>.py`, pure functions with docstrings, small hand-built DataFrames in tests. Run tests with `./venv/bin/python -m pytest`.

**Reused interfaces (already in the repo — do not change):**
- `liquidity.swing_points(df, left=2, right=2) -> (sh_idx, sl_idx)` — fractal swing index lists.
- `liquidity.detect_sweeps(df, left=2, right=2) -> [{index, direction('bearish'|'bullish'), level, swing_index}]` — `bearish` = swept a swing high then closed back below; `bullish` = swept a low then closed back above.
- `fvg.find_fvgs(df, direction) -> [FVG]`; `FVG(index, direction('bull'|'bear'), bottom, top, time)`.
- `levels.unfilled_fvgs(df, direction) -> [FVG]` — FVGs not yet traded back into.
- `levels.build_levels(daily, h4, now, daily_n, h4_n, left, right) -> [Level]`; `Level(source, price, side('high'|'low'))`.
- `levels.ema(series, period) -> pd.Series`.
- `structure.detect_structure_breaks(df, left=2, right=2) -> [{index, direction('up'|'down'), kind('BOS'|'MSS'), level, swing_index}]`.

---

### Task 1: `instruments.py` — per-instrument config + unit conversion

**Files:**
- Create: `instruments.py`
- Test: `tests/test_instruments.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from instruments import Instrument, INSTRUMENTS, get_instrument, to_units


def test_known_instruments_present():
    assert set(INSTRUMENTS) >= {"BTCUSDT", "XAUUSD", "EURUSD"}


def test_btc_uses_price_units_identity():
    btc = get_instrument("BTCUSDT")
    assert btc.units == "price"
    assert to_units(150.0, btc) == 150.0  # price units: identity


def test_eur_uses_pips():
    eur = get_instrument("EURUSD")
    assert eur.units == "pips"
    # 0.0008 price = 8 pips at pip_size 0.0001
    assert to_units(0.0008, eur) == pytest.approx(8.0)


def test_unknown_instrument_raises():
    with pytest.raises(KeyError):
        get_instrument("DOGE")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_instruments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'instruments'`.

- [ ] **Step 3: Implement `instruments.py`**

```python
"""Per-instrument configuration for the confluence scorer (units, bands, weights).

Only BTCUSDT is monitored live; XAUUSD/EURUSD exist for config + tests. Every
distance comparison goes through `to_units` so a pip instrument is never compared
against a price-unit band (the unit-bug guard from the spec).
"""
from dataclasses import dataclass, field


@dataclass
class Instrument:
    symbol: str
    units: str          # "price" | "pips"
    pip_size: float     # price per pip (used when units == "pips")
    aoi_band: float     # swing-level AOI band width, in PRICE
    cluster_band: float # clustering tolerance, in UNITS (pips for EUR, price else)
    min_rr: float       # Factor 5 minimum reward:risk
    stop_buffer: float  # extra distance beyond the distal edge, in PRICE
    factor_weights: dict
    label_thresholds: dict


_DEFAULT_WEIGHTS = {
    "sweep": 0.35, "cluster": 0.15, "structure": 0.15,
    "shift": 0.20, "rr": 0.10, "session": 0.05,
}
_DEFAULT_THRESHOLDS = {"A+": 0.70, "valid": 0.45, "weak": 0.0}

INSTRUMENTS = {
    "BTCUSDT": Instrument("BTCUSDT", "price", 0.0, aoi_band=120.0,
                          cluster_band=150.0, min_rr=2.0, stop_buffer=60.0,
                          factor_weights=dict(_DEFAULT_WEIGHTS),
                          label_thresholds=dict(_DEFAULT_THRESHOLDS)),
    "XAUUSD": Instrument("XAUUSD", "price", 0.0, aoi_band=3.0,
                         cluster_band=4.0, min_rr=2.0, stop_buffer=1.5,
                         factor_weights=dict(_DEFAULT_WEIGHTS),
                         label_thresholds=dict(_DEFAULT_THRESHOLDS)),
    "EURUSD": Instrument("EURUSD", "pips", 0.0001, aoi_band=0.0008,
                         cluster_band=8.0, min_rr=2.0, stop_buffer=0.0004,
                         factor_weights=dict(_DEFAULT_WEIGHTS),
                         label_thresholds=dict(_DEFAULT_THRESHOLDS)),
}


def get_instrument(symbol: str) -> Instrument:
    return INSTRUMENTS[symbol]


def to_units(price_distance: float, inst: Instrument) -> float:
    """Convert a raw price distance into the instrument's comparison unit."""
    if inst.units == "pips":
        return price_distance / inst.pip_size
    return price_distance
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_instruments.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add instruments.py tests/test_instruments.py
git commit -m "feat: per-instrument config + to_units (BTC/XAU/EUR)"
```

---

### Task 2: `bias.py` — per-timeframe bias with FLAT

**Files:**
- Create: `bias.py`
- Test: `tests/test_bias.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
from bias import compute_bias, bias_map


def _rising():
    return pd.DataFrame({"high": [c + 1 for c in range(80)],
                         "low": [c - 1 for c in range(80)],
                         "close": [float(c) for c in range(80)]})


def _falling():
    return pd.DataFrame({"high": [101 - c for c in range(80)],
                         "low": [99 - c for c in range(80)],
                         "close": [100.0 - c for c in range(80)]})


def _flat():
    return pd.DataFrame({"high": [100.5] * 80, "low": [99.5] * 80,
                         "close": [100.0] * 80})


def test_compute_bias_up_down_flat():
    assert compute_bias(_rising()) == "UP"
    assert compute_bias(_falling()) == "DOWN"
    assert compute_bias(_flat()) == "FLAT"


def test_bias_map_keys():
    m = bias_map(_rising(), _rising(), _falling())
    assert set(m) == {"W", "D", "H4"}
    assert m["W"] == "UP" and m["H4"] == "DOWN"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_bias.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bias'`.

- [ ] **Step 3: Implement `bias.py`**

```python
"""Per-timeframe bias: UP / DOWN / FLAT, from EMA-50 position+slope and structure.

FLAT when the EMA slope is within a small fractional threshold, or when EMA
position and slope disagree, or when the last structure break contradicts the
slope. This replaces the flat single-`Bias` for the scoring path; the existing
watcher keeps its own bias until Phase 2.
"""
import pandas as pd

from levels import ema
from structure import detect_structure_breaks


def compute_bias(df: pd.DataFrame, ema_period: int = 50,
                 flat_slope_pct: float = 0.0008, left: int = 2, right: int = 2) -> str:
    close = df["close"]
    e = ema(close, ema_period)
    ema_last = float(e.iloc[-1])
    if ema_last == 0:
        return "FLAT"
    window = max(1, min(len(e) - 1, ema_period // 2))
    slope = (ema_last - float(e.iloc[-1 - window])) / abs(ema_last)
    if abs(slope) < flat_slope_pct:
        return "FLAT"
    slope_dir = "up" if slope > 0 else "down"
    pos_dir = "up" if float(close.iloc[-1]) >= ema_last else "down"
    if pos_dir != slope_dir:
        return "FLAT"
    breaks = detect_structure_breaks(df, left, right)
    if breaks and breaks[-1]["direction"] != slope_dir:
        return "FLAT"
    return "UP" if slope_dir == "up" else "DOWN"


def bias_map(weekly: pd.DataFrame, daily: pd.DataFrame, h4: pd.DataFrame, **kw) -> dict:
    """Per-TF bias map keyed 'W'/'D'/'H4'."""
    return {"W": compute_bias(weekly, **kw),
            "D": compute_bias(daily, **kw),
            "H4": compute_bias(h4, **kw)}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_bias.py -v`
Expected: 2 passed. (If `_flat` does not yield FLAT, the slope threshold is the only knob — the constant-price frame has zero slope, so it will.)

- [ ] **Step 5: Commit**

```bash
git add bias.py tests/test_bias.py
git commit -m "feat: per-timeframe bias (UP/DOWN/FLAT) + bias_map"
```

---

### Task 3: `aoi.py` — the banded AOI type and builders

**Files:**
- Create: `aoi.py`
- Test: `tests/test_aoi.py`

- [ ] **Step 1: Write the failing test**

```python
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
    assert aoi.distal == 70000.0 + BTC.aoi_band   # stop side above a high
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
    # bull FVG = demand: proximal is the top (reached first from above)
    assert by_side["demand"].proximal == 105.0 and by_side["demand"].distal == 100.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_aoi.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aoi'`.

- [ ] **Step 3: Implement `aoi.py`**

```python
"""Areas of Interest as bands [proximal, distal] with timeframe + side.

proximal = the edge price reaches first; distal = the far / stop-side edge.
Supply: distal is ABOVE (proximal < distal). Demand: distal is BELOW (proximal > distal).
"""
from dataclasses import dataclass, field
from typing import List

from levels import Level, build_levels, unfilled_fvgs
from fvg import FVG
from instruments import Instrument


@dataclass
class AOI:
    timeframe: str            # 'D' | 'H4'
    side: str                 # 'supply' | 'demand'
    proximal: float
    distal: float
    source: str
    origin: dict = field(default_factory=dict)
    # scoring results, filled by scoring.py
    score: float = 0.0
    label: str = "unscored"
    gate: str = ""
    breakdown: dict = field(default_factory=dict)


def band_lo_hi(aoi: AOI) -> tuple:
    """(low_edge, high_edge) of the band regardless of side."""
    return (min(aoi.proximal, aoi.distal), max(aoi.proximal, aoi.distal))


def _level_timeframe(source: str) -> str:
    return "H4" if source.startswith("h4") else "D"


def level_to_aoi(level: Level, inst: Instrument) -> AOI:
    tf = _level_timeframe(level.source)
    if level.side == "high":   # supply: stop above the high
        return AOI(tf, "supply", level.price, level.price + inst.aoi_band, level.source)
    return AOI(tf, "demand", level.price, level.price - inst.aoi_band, level.source)


def fvgs_to_aois(fvgs: List[FVG], timeframe: str) -> List[AOI]:
    tf = timeframe.lower()
    out: List[AOI] = []
    for f in fvgs:
        if f.direction == "bull":   # demand: price drops in from above -> proximal = top
            out.append(AOI(timeframe, "demand", f.top, f.bottom, f"{tf}_fvg_bull",
                           {"fvg_top": f.top, "fvg_bottom": f.bottom}))
        else:                       # bear = supply: price rises in from below -> proximal = bottom
            out.append(AOI(timeframe, "supply", f.bottom, f.top, f"{tf}_fvg_bear",
                           {"fvg_top": f.top, "fvg_bottom": f.bottom}))
    return out


def build_aois(daily, h4, now, inst: Instrument,
               daily_n: int, h4_n: int, left: int, right: int) -> List[AOI]:
    """All AOIs for scoring: banded swing/PDH/PDL levels + unmitigated H4 FVG zones."""
    levels = build_levels(daily, h4, now, daily_n, h4_n, left, right)
    aois = [level_to_aoi(l, inst) for l in levels]
    aois += fvgs_to_aois(unfilled_fvgs(h4, "bull") + unfilled_fvgs(h4, "bear"), "H4")
    return aois
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_aoi.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add aoi.py tests/test_aoi.py
git commit -m "feat: banded AOI type + builders from levels/PDH-PDL/FVGs"
```

---

### Task 4: `gate.py` — the bias gate (own-TF-and-higher only)

**Files:**
- Create: `gate.py`
- Test: `tests/test_gate.py`

- [ ] **Step 1: Write the failing test** (encodes spec fixtures A1, A2a, A2b, A2c, A3)

```python
from gate import bias_gate
from aoi import AOI

# A Daily supply AOI (short) and a Daily demand AOI (long) for the cases.
SUPPLY_D = AOI("D", "supply", 71050.0, 71170.0, "daily_swing_high")
DEMAND_D = AOI("D", "demand", 60000.0, 59880.0, "daily_swing_low")


def test_A1_flat_own_tf_is_no_trade():
    # demand needs UP; own-TF (D) FLAT -> no-trade even if everything else is perfect
    assert bias_gate(DEMAND_D, {"W": "UP", "D": "FLAT"}) == "no-trade"


def test_A2a_counter_htf_trend_is_no_trade():
    # supply needs DOWN; Daily AND Weekly UP -> no-trade
    assert bias_gate(SUPPLY_D, {"W": "UP", "D": "UP"}) == "no-trade"


def test_A2b_pullback_into_htf_aoi_passes():
    # supply needs DOWN; Daily DOWN (lower-TF rally into it is NOT consulted) -> pass
    assert bias_gate(SUPPLY_D, {"W": "DOWN", "D": "DOWN"}) == "pass"
    # Weekly unknown must not block
    assert bias_gate(SUPPLY_D, {"D": "DOWN"}) == "pass"


def test_A2c_aligned_continuation_passes():
    assert bias_gate(DEMAND_D, {"W": "UP", "D": "UP"}) == "pass"


def test_higher_tf_flat_does_not_block():
    assert bias_gate(SUPPLY_D, {"W": "FLAT", "D": "DOWN"}) == "pass"


def test_h4_aoi_checks_h4_d_w():
    h4_supply = AOI("H4", "supply", 64000.0, 64120.0, "h4_swing_high")
    assert bias_gate(h4_supply, {"H4": "DOWN", "D": "DOWN", "W": "DOWN"}) == "pass"
    assert bias_gate(h4_supply, {"H4": "DOWN", "D": "UP"}) == "no-trade"  # higher conflict
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate'`.

- [ ] **Step 3: Implement `gate.py`**

```python
"""Bias gate: hard pass / no-trade. Checks the AOI's own timeframe AND higher only.

A lower-timeframe move into the AOI is never consulted (spec §2): the up-leg into
an HTF supply is the pullback/delivery leg, not a bias conflict.
"""
from aoi import AOI

# AOI timeframe -> [own, higher...] in ascending order
_TF_CHAIN = {"H4": ["H4", "D", "W"], "D": ["D", "W"]}


def bias_gate(aoi: AOI, bias_map: dict) -> str:
    want = "UP" if aoi.side == "demand" else "DOWN"
    chain = _TF_CHAIN[aoi.timeframe]
    own = bias_map.get(chain[0])
    if own != want:                       # own-TF FLAT or opposite
        return "no-trade"
    for tf in chain[1:]:                  # strictly higher TFs
        b = bias_map.get(tf)
        if b is not None and b != "FLAT" and b != want:
            return "no-trade"             # higher-TF conflict
    return "pass"
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_gate.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add gate.py tests/test_gate.py
git commit -m "feat: bias gate (own-TF-and-higher; lower-TF pullback never blocks)"
```

---

### Task 5: `factors.py` — context + Factor 1 (liquidity sweep)

**Files:**
- Create: `factors.py`
- Test: `tests/test_factors_sweep.py`

- [ ] **Step 1: Write the failing test** (spec B1/B2/B3 idea — sweep present vs absent vs wrong-side)

```python
import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_sweep
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(frame):
    # other fields unused by factor_sweep; pass minimal placeholders
    return ScoringContext(daily=frame, h4=frame, etf=frame,
                          all_aois=[], bias_map={}, shift_reader=None)


def _frame_with_high_sweep():
    # swing high at idx 2 (high=120); bar 5 spikes above (125) then closes back below (118)
    return pd.DataFrame({
        "high":  [100, 110, 120, 110, 105, 125, 116],
        "low":   [90,  100, 110, 100,  95, 112, 108],
        "close": [95,  108, 118, 105, 100, 118, 112],
    })


def _frame_no_sweep():
    # same swing high, but price never runs above it
    return pd.DataFrame({
        "high":  [100, 110, 120, 110, 105, 116, 114],
        "low":   [90,  100, 110, 100,  95, 110, 108],
        "close": [95,  108, 118, 105, 100, 114, 112],
    })


def test_sweep_present_for_supply_scores_high():
    supply = AOI("H4", "supply", 116.0, 120.0, "h4_swing_high")
    assert factor_sweep(supply, _ctx(_frame_with_high_sweep()), BTC) == 1.0


def test_no_sweep_scores_zero():
    supply = AOI("H4", "supply", 116.0, 120.0, "h4_swing_high")
    assert factor_sweep(supply, _ctx(_frame_no_sweep()), BTC) == 0.0


def test_wrong_side_sweep_not_rewarded():
    # a long (demand) needs a swept LOW; only a high was swept -> 0
    demand = AOI("H4", "demand", 116.0, 112.0, "h4_swing_low")
    assert factor_sweep(demand, _ctx(_frame_with_high_sweep()), BTC) == 0.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_factors_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factors'`.

- [ ] **Step 3: Implement `factors.py` (context + factor_sweep)**

```python
"""Confluence factors. Each factor(aoi, ctx, inst) -> normalized contribution.

Contributions are in [0, 1] except factor_shift, which may be negative (a shift
against the trade direction is a penalty). Missing data degrades to neutral (0.0);
factors never raise.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pandas as pd

from aoi import AOI, band_lo_hi
from instruments import Instrument, to_units
from liquidity import detect_sweeps


@dataclass
class ScoringContext:
    daily: pd.DataFrame
    h4: pd.DataFrame
    etf: pd.DataFrame                       # entry timeframe (e.g. M15) for shift
    all_aois: List[AOI]                     # for clustering + R:R
    bias_map: dict
    shift_reader: Optional[Callable] = None # (aoi, ctx) -> 'up'|'down'|None
    sweep_lookback: int = 10                # bars back to credit a sweep


def _aoi_frame(aoi: AOI, ctx: ScoringContext) -> pd.DataFrame:
    return ctx.daily if aoi.timeframe == "D" else ctx.h4


def factor_sweep(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """1.0 if a directionally-relevant prior swing was run within `sweep_lookback`
    bars (a swept high fuels a supply/short, a swept low fuels a demand/long)."""
    frame = _aoi_frame(aoi, ctx)
    sweeps = detect_sweeps(frame)
    if not sweeps:
        return 0.0
    want = "bearish" if aoi.side == "supply" else "bullish"  # bearish = swept a high
    last_idx = len(frame) - 1
    for s in sweeps:
        if s["direction"] == want and last_idx - s["index"] <= ctx.sweep_lookback:
            return 1.0
    return 0.0
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_factors_sweep.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add factors.py tests/test_factors_sweep.py
git commit -m "feat: ScoringContext + factor_sweep (directional liquidity sweep)"
```

---

### Task 6: `factors.py` — Factor 2 (clustering, unit-aware)

**Files:**
- Modify: `factors.py`
- Test: `tests/test_factors_cluster.py`

- [ ] **Step 1: Write the failing test** (spec C1/C2/C3)

```python
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
    # within ~8 pips -> cluster bonus, proving pip (not price) comparison
    a = AOI("H4", "demand", 1.08500, 1.08420, "h4_swing_low")
    others = [a,
              AOI("D", "demand", 1.08530, 1.08450, "pdl"),
              AOI("D", "demand", 1.08470, 1.08390, "daily_swing_low")]
    assert factor_cluster(a, _ctx(others), EUR) > 0.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_factors_cluster.py -v`
Expected: FAIL — `ImportError: cannot import name 'factor_cluster'`.

- [ ] **Step 3: Add `factor_cluster` to `factors.py`**

```python
def factor_cluster(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """Reward AOIs whose proximal sits within `cluster_band` (in instrument units)
    of other AOIs' proximals. 0 if isolated; ramps with neighbour count."""
    neighbours = 0
    for other in ctx.all_aois:
        if other is aoi:
            continue
        if to_units(abs(other.proximal - aoi.proximal), inst) <= inst.cluster_band:
            neighbours += 1
    if neighbours == 0:
        return 0.0
    return min(neighbours / 2.0, 1.0)   # 2+ neighbours saturates the factor
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_factors_cluster.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add factors.py tests/test_factors_cluster.py
git commit -m "feat: factor_cluster (unit-aware AOI clustering)"
```

---

### Task 7: `factors.py` — Factor 3 (structural origin, unmitigated FVG)

**Files:**
- Modify: `factors.py`
- Test: `tests/test_factors_structure.py`

- [ ] **Step 1: Write the failing test** (spec D1/D2/D3)

```python
import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_structure
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(h4):
    return ScoringContext(daily=h4, h4=h4, etf=h4, all_aois=[], bias_map={})


def _h4_with_open_bull_fvg():
    # bull FVG at i=2 (low[2]=115 > high[0]=110); later bars stay above -> unmitigated
    return pd.DataFrame({
        "open_time": pd.to_datetime(
            ["2026-06-14T00:00Z", "2026-06-14T04:00Z", "2026-06-14T08:00Z",
             "2026-06-14T12:00Z", "2026-06-14T16:00Z"], utc=True),
        "high": [110, 113, 130, 132, 134],
        "low":  [108, 111, 115, 120, 122],
        "close":[109, 112, 128, 130, 132],
    })


def test_D1_fvg_at_demand_aoi_scores_positive():
    # demand AOI overlapping the bull FVG band [110, 115]
    aoi = AOI("H4", "demand", 115.0, 110.0, "h4_swing_low")
    assert factor_structure(aoi, _ctx(_h4_with_open_bull_fvg()), BTC) == 1.0


def test_D2_bare_level_scores_zero():
    # demand AOI far from any FVG
    aoi = AOI("H4", "demand", 90.0, 85.0, "h4_swing_low")
    assert factor_structure(aoi, _ctx(_h4_with_open_bull_fvg()), BTC) == 0.0


def test_D3_mitigated_fvg_not_rewarded():
    # later bar trades back into the gap -> unfilled_fvgs drops it -> 0
    df = _h4_with_open_bull_fvg().copy()
    df.loc[4, "low"] = 109   # dips back into [110,115]
    aoi = AOI("H4", "demand", 115.0, 110.0, "h4_swing_low")
    assert factor_structure(aoi, _ctx(df), BTC) == 0.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_factors_structure.py -v`
Expected: FAIL — `ImportError: cannot import name 'factor_structure'`.

- [ ] **Step 3: Add `factor_structure` to `factors.py`** (add import at top: `from levels import unfilled_fvgs`)

```python
def _overlaps(a_lo, a_hi, b_lo, b_hi) -> bool:
    return a_hi >= b_lo and a_lo <= b_hi


def factor_structure(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """1.0 if an UNMITIGATED FVG (matching the AOI side) overlaps the AOI band.

    demand <- bull FVG, supply <- bear FVG. Mitigated gaps are excluded by
    unfilled_fvgs, so they score 0."""
    frame = _aoi_frame(aoi, ctx)
    direction = "bull" if aoi.side == "demand" else "bear"
    a_lo, a_hi = band_lo_hi(aoi)
    for f in unfilled_fvgs(frame, direction):
        if _overlaps(a_lo, a_hi, f.bottom, f.top):
            return 1.0
    return 0.0
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_factors_structure.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add factors.py tests/test_factors_structure.py
git commit -m "feat: factor_structure (unmitigated FVG at the AOI)"
```

---

### Task 8: `factors.py` — Factor 4 (shift, pluggable MSS/CHoCH)

**Files:**
- Modify: `factors.py`
- Test: `tests/test_factors_shift.py`

- [ ] **Step 1: Write the failing test** (spec E1/E2/E3 + the default reader)

```python
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
    # supply/short wants a 'down' shift
    assert factor_shift(SUPPLY, _ctx(lambda a, c: "down"), BTC) == 1.0


def test_E3_shift_against_penalizes():
    assert factor_shift(SUPPLY, _ctx(lambda a, c: "up"), BTC) == -1.0


def test_default_reader_reads_choch_from_etf():
    # etf with a confirmed downward structure break -> reader returns 'down'
    etf = pd.DataFrame({
        "high":  [100, 110, 120, 112, 108, 104],
        "low":   [90,  100, 110,  95,  92,  88],
        "close": [95,  108, 118, 100,  95,  90],
    })
    ctx = ScoringContext(daily=etf, h4=etf, etf=etf, all_aois=[], bias_map={})
    assert structure_shift_reader(SUPPLY, ctx) in ("up", "down", None)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_factors_shift.py -v`
Expected: FAIL — `ImportError: cannot import name 'factor_shift'`.

- [ ] **Step 3: Add `factor_shift` + default reader to `factors.py`** (add `from structure import detect_structure_breaks` at top)

```python
def structure_shift_reader(aoi: AOI, ctx: ScoringContext) -> Optional[str]:
    """Default shift feed: the last MSS/CHoCH direction on the entry timeframe.
    Returns 'up'/'down'/None. A RelicusRoad Signal Line reader can replace this."""
    breaks = detect_structure_breaks(ctx.etf)
    if not breaks:
        return None
    return breaks[-1]["direction"]


def factor_shift(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """+1 if the shift confirms the trade direction, -1 if against, 0 if no feed.
    demand/long wants 'up'; supply/short wants 'down'."""
    reader = ctx.shift_reader
    if reader is None:
        return 0.0
    shift = reader(aoi, ctx)
    if shift is None:
        return 0.0
    want = "up" if aoi.side == "demand" else "down"
    return 1.0 if shift == want else -1.0
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_factors_shift.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add factors.py tests/test_factors_shift.py
git commit -m "feat: factor_shift + pluggable MSS/CHoCH shift reader"
```

---

### Task 9: `factors.py` — Factor 5 (R:R) and Factor 6 (session)

**Files:**
- Modify: `factors.py`
- Test: `tests/test_factors_rr_session.py`

- [ ] **Step 1: Write the failing test** (spec F1/F2 + session neutral default)

```python
import pandas as pd
from aoi import AOI
from factors import ScoringContext, factor_rr, factor_session
from instruments import get_instrument

BTC = get_instrument("BTCUSDT")


def _ctx(all_aois):
    f = pd.DataFrame({"high": [1.0], "low": [1.0], "close": [1.0]})
    return ScoringContext(daily=f, h4=f, etf=f, all_aois=all_aois, bias_map={})


def test_F1_healthy_room_scores_positive():
    # short from supply at 70000 (stop above distal 70120 + buffer); target = next demand far below
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    target = AOI("D", "demand", 67000.0, 66880.0, "daily_swing_low")
    assert factor_rr(supply, _ctx([supply, target]), BTC) > 0.0


def test_F2_boxed_in_scores_zero():
    # target only a little below -> sub-1R after the HTF stop -> 0
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    target = AOI("D", "demand", 69950.0, 69900.0, "daily_swing_low")
    assert factor_rr(supply, _ctx([supply, target]), BTC) == 0.0


def test_F_no_target_is_neutral():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    assert factor_rr(supply, _ctx([supply]), BTC) == 0.0


def test_session_neutral_without_session_info():
    supply = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    assert factor_session(supply, _ctx([supply]), BTC) == 0.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_factors_rr_session.py -v`
Expected: FAIL — `ImportError: cannot import name 'factor_rr'`.

- [ ] **Step 3: Add `factor_rr` and `factor_session` to `factors.py`**

```python
def _next_opposing_target(aoi: AOI, ctx: ScoringContext) -> Optional[float]:
    """Nearest opposing-side AOI in the trade's profit direction.
    Short (supply): a demand BELOW proximal. Long (demand): a supply ABOVE proximal."""
    want = "demand" if aoi.side == "supply" else "supply"
    candidates = []
    for other in ctx.all_aois:
        if other is aoi or other.side != want:
            continue
        if aoi.side == "supply" and other.proximal < aoi.proximal:
            candidates.append(other.proximal)
        elif aoi.side == "demand" and other.proximal > aoi.proximal:
            candidates.append(other.proximal)
    if not candidates:
        return None
    # nearest target in the profit direction
    return max(candidates) if aoi.side == "supply" else min(candidates)


def factor_rr(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """Reward when R:R to the next opposing AOI clears `min_rr`, using the HTF-wide
    stop (beyond the distal edge + buffer). 0 when boxed-in or no target."""
    target = _next_opposing_target(aoi, ctx)
    if target is None:
        return 0.0
    entry = aoi.proximal
    stop = aoi.distal + inst.stop_buffer if aoi.side == "supply" \
        else aoi.distal - inst.stop_buffer
    risk = abs(stop - entry)
    reward = abs(entry - target)
    if risk == 0:
        return 0.0
    rr = reward / risk
    if rr < inst.min_rr:
        return 0.0
    return min(rr / (2.0 * inst.min_rr), 1.0)   # saturates at 2x the minimum


def factor_session(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> float:
    """Optional mild boost during London/NY. Neutral (0.0) when no session info is
    available — Phase 1 does not pass session context, so this stays neutral."""
    return 0.0
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_factors_rr_session.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add factors.py tests/test_factors_rr_session.py
git commit -m "feat: factor_rr (HTF-stop R:R) + neutral factor_session"
```

---

### Task 10: `scoring.py` — combine gate + factors into score/label

**Files:**
- Create: `scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing test** (spec A1, B1≫B2, D2, and G1 ordering)

```python
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


class _StubCtx(ScoringContext):
    pass


def test_factors_registry_has_all_six():
    assert {name for name, _ in FACTORS} == {
        "sweep", "cluster", "structure", "shift", "rr", "session"}


def test_A1_flat_bias_is_no_trade(monkeypatch):
    aoi = AOI("D", "demand", 100.0, 95.0, "daily_swing_low")
    out = score_aoi(aoi, _ctx({"D": "FLAT"}), BTC)
    assert out.label == "no-trade" and out.gate == "no-trade"


def test_Aplus_requires_sweep(monkeypatch):
    # Force all factors to max EXCEPT sweep=0; must NOT be A+ (hard rule).
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

    # B1: sweep + structure present
    monkeypatch.setattr(scoring, "FACTORS", [
        ("sweep", lambda a, c, i: 1.0), ("cluster", lambda a, c, i: 0.5),
        ("structure", lambda a, c, i: 1.0), ("shift", lambda a, c, i: 1.0),
        ("rr", lambda a, c, i: 1.0), ("session", lambda a, c, i: 0.0)])
    b1 = score_aoi(supply, _ctx({"D": "DOWN", "W": "DOWN"}), BTC)

    # B2: same but NO sweep
    monkeypatch.setattr(scoring, "FACTORS", [
        ("sweep", lambda a, c, i: 0.0), ("cluster", lambda a, c, i: 0.5),
        ("structure", lambda a, c, i: 1.0), ("shift", lambda a, c, i: 0.0),
        ("rr", lambda a, c, i: 0.0), ("session", lambda a, c, i: 0.0)])
    b2 = score_aoi(supply, _ctx({"D": "DOWN", "W": "DOWN"}), BTC)

    # A1: flat bias
    a1 = score_aoi(demand_flat, _ctx({"D": "FLAT"}), BTC)

    order = {"A+": 3, "valid": 2, "weak": 1, "no-trade": 0}
    assert order[b1.label] > order[b2.label] > order[a1.label]
    assert b1.label == "A+" and b2.label == "weak" and a1.label == "no-trade"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scoring'`.

- [ ] **Step 3: Implement `scoring.py`**

```python
"""Confluence scoring core: bias gate (hard) + weighted factors -> score + label."""
from aoi import AOI
from gate import bias_gate
from factors import (ScoringContext, factor_sweep, factor_cluster, factor_structure,
                     factor_shift, factor_rr, factor_session)
from instruments import Instrument

FACTORS = [
    ("sweep", factor_sweep),
    ("cluster", factor_cluster),
    ("structure", factor_structure),
    ("shift", factor_shift),
    ("rr", factor_rr),
    ("session", factor_session),
]


def _label(score: float, breakdown: dict, inst: Instrument) -> str:
    th = inst.label_thresholds
    # Hard rule: A+ requires a liquidity sweep present (no combination of other
    # factors can lift a no-sweep AOI to A+ — the anti-chase guard).
    if score >= th["A+"] and breakdown.get("sweep", 0.0) > 0.0:
        return "A+"
    if score >= th["valid"]:
        return "valid"
    return "weak"


def score_aoi(aoi: AOI, ctx: ScoringContext, inst: Instrument) -> AOI:
    """Score one AOI in place: sets gate, score, breakdown, label. Returns it."""
    gate = bias_gate(aoi, ctx.bias_map)
    aoi.gate = gate
    if gate == "no-trade":
        aoi.score = 0.0
        aoi.breakdown = {}
        aoi.label = "no-trade"
        return aoi
    breakdown = {}
    score = 0.0
    for name, fn in FACTORS:
        contrib = fn(aoi, ctx, inst)
        breakdown[name] = contrib
        score += inst.factor_weights[name] * contrib
    aoi.score = score
    aoi.breakdown = breakdown
    aoi.label = _label(score, breakdown, inst)
    return aoi
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_scoring.py -v`
Expected: all pass. (Check the default weights/thresholds in `instruments.py` actually put B1 at `A+` and B2 at `weak`: B1 score = .35+.15·.5+.15+.20+.10 = 0.875 ≥ .70 with sweep>0 → A+; B2 = .15·.5+.15 = 0.225 < .45 → weak. If not, adjust thresholds in `instruments.py` — they are config.)

- [ ] **Step 5: Commit**

```bash
git add scoring.py tests/test_scoring.py
git commit -m "feat: scoring core (gate + weighted factors + A+-requires-sweep)"
```

---

### Task 11: Integration — Weekly fetch + scoring pass in `engine.py`

**Files:**
- Modify: `config.py` (extend `INTERVALS`)
- Modify: `engine.py` (add `score_pass`)
- Test: `tests/test_engine_scoring.py`

- [ ] **Step 1: Extend INTERVALS**

In `config.py`, change `INTERVALS = ("1d", "4h", "15m", "5m")` to:

```python
INTERVALS = ("1w", "1d", "4h", "15m", "5m")
```

- [ ] **Step 2: Write the failing test**

```python
import pandas as pd
import engine
from aoi import AOI


def _frame(n, base, step):
    return pd.DataFrame({
        "open_time": pd.to_datetime("2026-01-01", utc=True) + pd.to_timedelta(range(n), unit="h"),
        "high": [base + step * i + 1 for i in range(n)],
        "low":  [base + step * i - 1 for i in range(n)],
        "close":[float(base + step * i) for i in range(n)],
        "close_time": pd.to_datetime("2026-01-01", utc=True) + pd.to_timedelta(range(1, n + 1), unit="h"),
    })


def test_score_pass_returns_scored_aois():
    weekly = _frame(60, 100, 1)
    daily = _frame(60, 100, 1)
    h4 = _frame(120, 100, 1)
    etf = _frame(120, 100, 1)
    now = daily["close_time"].iloc[-1]
    scored = engine.score_pass(weekly, daily, h4, etf, now, symbol="BTCUSDT")
    assert all(isinstance(a, AOI) for a in scored)
    assert all(a.label in ("A+", "valid", "weak", "no-trade") for a in scored)
    assert all(a.gate in ("pass", "no-trade") for a in scored)
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_engine_scoring.py -v`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'score_pass'`.

- [ ] **Step 4: Add `score_pass` to `engine.py`** (add imports for the new modules)

```python
import app_config as cfg
from instruments import get_instrument
from aoi import build_aois
from bias import bias_map
from factors import ScoringContext, structure_shift_reader
from scoring import score_aoi


def score_pass(weekly, daily, h4, etf, now, symbol="BTCUSDT"):
    """Build banded AOIs, the per-TF bias map, and score every AOI. Returns [AOI]."""
    inst = get_instrument(symbol)
    aois = build_aois(daily, h4, now, inst,
                      daily_n=cfg.DAILY_SWING_LOOKBACK_N, h4_n=cfg.H4_SWING_LOOKBACK_N,
                      left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    bm = bias_map(weekly, daily, h4)
    ctx = ScoringContext(daily=daily, h4=h4, etf=etf, all_aois=aois, bias_map=bm,
                         shift_reader=structure_shift_reader)
    for aoi in aois:
        score_aoi(aoi, ctx, inst)
    return aois
```

- [ ] **Step 5: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_engine_scoring.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add config.py engine.py tests/test_engine_scoring.py
git commit -m "feat: weekly interval + engine.score_pass (bias map + scored AOIs)"
```

---

### Task 12: Serialize scored AOIs into `state.json`

**Files:**
- Modify: `state.py` (add `aois` to the payload)
- Test: `tests/test_state_aois.py`

- [ ] **Step 1: Write the failing test**

```python
from aoi import AOI
import state


def test_build_state_includes_scored_aois(tmp_path):
    a = AOI("D", "supply", 70000.0, 70120.0, "daily_swing_high")
    a.gate, a.score, a.label = "pass", 0.82, "A+"
    a.breakdown = {"sweep": 1.0, "cluster": 0.5}
    payload = state.build_state(
        price=69000.0, levels=[], zones=[], bias=None,
        fired=[], last_alert={}, updated_at="2026-06-16T07:00:00Z", aois=[a])
    assert payload["aois"][0]["label"] == "A+"
    assert payload["aois"][0]["side"] == "supply"
    assert payload["aois"][0]["breakdown"]["sweep"] == 1.0
    assert payload["aois"][0]["proximal"] == 70000.0


def test_build_state_aois_defaults_empty():
    payload = state.build_state(
        price=1.0, levels=[], zones=[], bias=None,
        fired=[], last_alert={}, updated_at="x")
    assert payload["aois"] == []
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_state_aois.py -v`
Expected: FAIL — `build_state() got an unexpected keyword argument 'aois'`.

- [ ] **Step 3: Modify `state.py`** — add an `_aoi_to_dict` helper and an optional `aois` param

Add near `_zone_to_dict`:

```python
def _aoi_to_dict(a) -> dict:
    return {"timeframe": a.timeframe, "side": a.side,
            "proximal": a.proximal, "distal": a.distal, "source": a.source,
            "gate": a.gate, "score": a.score, "label": a.label,
            "breakdown": a.breakdown}
```

Change the `build_state` signature to accept `aois=None` and add the key. The existing
signature is `build_state(price, levels, zones, bias, fired, last_alert, updated_at)`;
make it:

```python
def build_state(price, levels, zones, bias, fired, last_alert, updated_at, aois=None):
    return {
        "price": price,
        "levels": [asdict(l) for l in levels],
        "zones": [_zone_to_dict(z) for z in zones],
        "bias": asdict(bias) if bias is not None else None,
        "fired": list(fired),
        "last_alert": last_alert,
        "updated_at": updated_at,
        "aois": [_aoi_to_dict(a) for a in (aois or [])],
    }
```

(Note: this also makes `bias` tolerate `None`, matching `app.py`'s existing guard.)

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_state_aois.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the FULL suite to confirm nothing regressed**

Run: `./venv/bin/python -m pytest -q`
Expected: all pass (existing `test_state.py` still green — the new `aois` param is optional).

- [ ] **Step 6: Commit**

```bash
git add state.py tests/test_state_aois.py
git commit -m "feat: serialize scored AOIs into state.json"
```

---

### Task 13: Wire `score_pass` into the app + render labels on the chart

**Files:**
- Modify: `app.py` (call `score_pass` in `remark_now`; pass `aois` to `_write_state`; fetch weekly)
- Modify: `chart/chart.js` (color AOI bands by label, show breakdown)
- No unit test (GUI/integration) — verified by `import app` + the live smoke test.

- [ ] **Step 1: Update `app.py`**

In `remark_now`, after computing levels, fetch weekly + ETF and run the scoring pass. Replace the body of `remark_now` with:

```python
    def remark_now(self, _):
        try:
            now = pd.Timestamp.now(tz="UTC")
            daily = download("1d", force=True)
            weekly = fetch_recent("1w", limit=300)
            h4 = fetch_recent("4h", limit=500)
            etf = fetch_recent("15m", limit=300)
            self.levels, self.zones, self.bias = engine.run_morning_pass(daily, h4, now)
            self.aois = engine.score_pass(weekly, daily, h4, etf, now, symbol="BTCUSDT")
            self.fired = set()
            self._write_state()
        except Exception as e:
            print(f"[watcher] remark_now failed, keeping previous levels: {e}")
```

Add `self.aois = []` next to `self.levels, self.zones, self.bias = [], [], None` in `__init__`.

In `_write_state`, pass the AOIs through. Change the `state.build_state(...)` call to include
`aois=self.aois`:

```python
        payload = state.build_state(
            price=_clean_price(price) if price is not None else 0.0,
            levels=self.levels, zones=self.zones, bias=self.bias,
            fired=list(self.fired), last_alert=self.last_alert,
            updated_at=pd.Timestamp.now(tz="UTC").isoformat(),
            aois=self.aois,
        )
```

(Phase 1 does NOT add entry alerts. The scoring pass only runs in `remark_now`; `tick`
keeps doing the existing sweep scan. AOIs refresh whenever levels are re-marked.)

- [ ] **Step 2: Update `chart/chart.js`** to draw AOI bands colored by label

After the existing level-line rendering in `refresh()`, add AOI band rendering. Append
inside `refresh()` (after `setBias(s.bias);`):

```javascript
  // AOI bands colored by confluence label
  (window._aoiLines || []).forEach(l => candles.removePriceLine(l));
  const LABEL_COLOR = { 'A+': '#3fb950', 'valid': '#58a6ff', 'weak': '#6e7681', 'no-trade': '#30363d' };
  window._aoiLines = (s.aois || [])
    .filter(a => a.label !== 'no-trade')
    .map(a => candles.createPriceLine({
      price: a.proximal,
      color: LABEL_COLOR[a.label] || '#6e7681',
      lineWidth: a.label === 'A+' ? 2 : 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      title: `${a.label} ${a.source}`,
    }));
```

- [ ] **Step 3: Verify (no GUI launch)**

Run: `./venv/bin/python -c "import app; print('import OK')"`
Expected: `import OK`.
Run: `./venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add app.py chart/chart.js
git commit -m "feat: run score_pass in app + render AOI labels on the chart"
```

---

### Task 14: Docs — update README with the confluence layer

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a section to `README.md`**

```markdown
## Confluence scoring (Phase 1)
Each Area of Interest (swing levels, PDH/PDL, H4 FVGs) is gated by per-timeframe
bias (Weekly/Daily/H4, with a FLAT state) and scored by six factors — liquidity
sweep (dominant), clustering, unmitigated FVG, MSS/CHoCH shift, R:R to the next
opposing level, and session — into a label: `A+` / `valid` / `weak` / `no-trade`.

- The bias gate is hard pass/fail and only consults the AOI's own timeframe and
  higher; a lower-TF move *into* an HTF level is the pullback, not a conflict.
- `A+` requires a liquidity sweep — structure/clustering can never substitute for it.
- Labels show on the chart (color-coded). Phase 1 emits **no entry alerts**; the
  `tag → sweep → shift → ARMED` state machine and entry signals are Phase 2.

Per-instrument config (BTC/XAU/EUR, price vs pips) lives in `instruments.py`.
Only BTCUSDT is monitored live.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the confluence scoring layer (Phase 1)"
```

---

## Self-Review notes

- **Spec coverage:** per-TF bias + FLAT (Task 2); AOI bands (Task 3); bias gate / §2 edge (Task 4, fixtures A1/A2a/A2b/A2c); 6 factors (Tasks 5–9, fixtures B/C/D/E/F + session); scoring + labels + A+-requires-sweep + ordering (Task 10, fixtures A1/B1/B2/G1); multi-instrument units (Task 1, fixtures C1/C2/C3 in Task 6); integration + weekly + chart display (Tasks 11–13); state.json source of truth (Task 12); docs (Task 14). Out-of-scope (state machine group H, entry alerts, live XAU/EUR) intentionally absent.
- **Type consistency:** `AOI(timeframe, side, proximal, distal, source, origin, score, label, gate, breakdown)`, `Instrument(...)` fields, `ScoringContext(daily, h4, etf, all_aois, bias_map, shift_reader, sweep_lookback)`, `bias_map`→keys `W/D/H4`, `bias_gate(aoi, bias_map)`, `factor_*(aoi, ctx, inst)`, `score_aoi(aoi, ctx, inst)`, `build_aois(...)`, `engine.score_pass(weekly, daily, h4, etf, now, symbol)` are used identically across tasks.
- **No placeholders:** every code step is complete. Default weights/thresholds are concrete in Task 1; Task 10 documents how to confirm they produce the required B1/B2 ordering and that they're config if tuning is needed.
```
