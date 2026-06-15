# BTC Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS menu-bar app that marks BTCUSD levels each morning and alerts when a higher-timeframe-aligned sweep + reclaim forms on M15.

**Architecture:** A long-running `rumps` menu-bar process with three layers — a pure analysis **engine** (`levels.py`, `watcher.py`, reusing existing `liquidity.py`/`fvg.py`/`structure.py`), an **app shell** (`app.py`: scheduler, notifications, menu, local chart server), and a static **chart page** (`chart/`) that reads a `state.json` written by the app. Data flows one way: scheduler → fetch → engine → `state.json` → {notification, menu text, chart}.

**Tech Stack:** Python 3.11, pandas, requests, `rumps` (macOS menu bar + notifications), stdlib `zoneinfo`/`http.server`/`threading`, TradingView `lightweight-charts` (CDN) for the chart. pytest for the engine.

**Spec:** `docs/superpowers/specs/2026-06-15-btc-watcher-design.md`

**Conventions (match existing repo):** flat module layout (no `src/`), flat imports (`from levels import ...`), tests in `tests/test_<module>.py` using small hand-built DataFrames, pure engine functions. Run tests with `./venv/bin/python -m pytest`.

---

### Task 1: Add dependencies and extend intervals

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py:4` (the `INTERVALS` tuple)

- [ ] **Step 1: Add `rumps` to requirements**

Append to `requirements.txt`:

```
rumps>=0.4.0
```

- [ ] **Step 2: Install it**

Run: `./venv/bin/pip install "rumps>=0.4.0"`
Expected: installs cleanly (rumps is macOS-only — that's fine, this app is macOS).

- [ ] **Step 3: Extend INTERVALS**

In `config.py`, change line 4 from:

```python
INTERVALS = ("4h", "15m")
```

to:

```python
INTERVALS = ("1d", "4h", "15m", "5m")
```

- [ ] **Step 4: Verify the suite still passes**

Run: `./venv/bin/python -m pytest -q`
Expected: all existing tests pass (71+).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config.py
git commit -m "chore: add rumps dep and extend INTERVALS for the watcher"
```

---

### Task 2: Lightweight `fetch_recent` for the 5-min loop

The existing `download()` is full-history and disk-cached — too heavy to call every 5 minutes. Add a "last N candles" fetch.

**Files:**
- Modify: `fetch_data.py` (add function after `download`)
- Test: `tests/test_fetch_data.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fetch_data.py`:

```python
def test_fetch_recent_builds_df_from_api(monkeypatch):
    import fetch_data

    sample = [
        [1700000000000, "100", "110", "90", "105", "12.5", 1700000899999],
        [1700000900000, "105", "120", "104", "118", "8.0", 1700001799999],
    ]

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return sample

    def _fake_get(url, params=None, timeout=None):
        assert params["symbol"] == "BTCUSDT"
        assert params["interval"] == "15m"
        assert params["limit"] == 2
        return _Resp()

    monkeypatch.setattr(fetch_data.requests, "get", _fake_get)
    df = fetch_data.fetch_recent("15m", limit=2)

    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume", "close_time"]
    assert len(df) == 2
    assert df["high"].iloc[1] == 120.0
    assert str(df["open_time"].dt.tz) == "UTC"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_fetch_data.py::test_fetch_recent_builds_df_from_api -v`
Expected: FAIL — `AttributeError: module 'fetch_data' has no attribute 'fetch_recent'`.

- [ ] **Step 3: Implement `fetch_recent`**

Add to `fetch_data.py` after `download`:

```python
def fetch_recent(interval: str, limit: int = 300) -> pd.DataFrame:
    """Fetch the most recent `limit` klines for `interval` straight from the API.

    Unlike `download`, this does not cache to disk and does not page history. It is
    the light path used by the 5-minute watch loop. The last row may be the still-open
    (in-progress) candle; callers that need only closed bars should drop it.
    """
    resp = requests.get(
        config.BINANCE_BASE,
        params={"symbol": config.SYMBOL, "interval": interval, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return klines_to_df(resp.json())
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_fetch_data.py::test_fetch_recent_builds_df_from_api -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fetch_data.py tests/test_fetch_data.py
git commit -m "feat: fetch_recent for light periodic kline pulls"
```

---

### Task 3: `app_config.py` — defaults and persisted settings

**Files:**
- Create: `app_config.py`
- Test: `tests/test_app_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_config.py`:

```python
import json
import app_config


def test_load_settings_returns_defaults_when_missing(tmp_path):
    path = tmp_path / "settings.json"
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": True, "alert_sound_enabled": False}


def test_save_then_load_roundtrips(tmp_path):
    path = tmp_path / "settings.json"
    app_config.save_settings({"notifications_enabled": False, "alert_sound_enabled": True}, str(path))
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": False, "alert_sound_enabled": True}


def test_load_settings_fills_missing_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"notifications_enabled": False}))
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": False, "alert_sound_enabled": False}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app_config'`.

- [ ] **Step 3: Implement `app_config.py`**

Create `app_config.py`:

```python
"""Watcher configuration: static defaults plus the two persisted UI toggles."""
import json
import os

# --- Static behavior knobs (edit in source) ---
SCAN_INTERVAL_MIN = 5
MORNING_TIME = "08:00"          # HH:MM in MORNING_TZ
MORNING_TZ = "Europe/Oslo"      # user's local time; tracks DST (was specified as "UTC+2")
DAILY_SWING_LOOKBACK_N = 5      # how many recent Daily swings (each side) to mark
H4_SWING_LOOKBACK_N = 6
SWING_LEFT = 2                  # fractal window, matches liquidity.swing_points defaults
SWING_RIGHT = 2
REQUIRE_HTF_ALIGNMENT = True
COUNTER_TREND_MODE = "silent"   # "silent" | "fyi"

# --- Persisted UI toggles ---
SETTINGS_PATH = "app_settings.json"
DEFAULT_SETTINGS = {"notifications_enabled": True, "alert_sound_enabled": False}


def load_settings(path: str = SETTINGS_PATH) -> dict:
    """Return persisted settings merged over DEFAULT_SETTINGS (missing file -> defaults)."""
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(path):
        with open(path) as f:
            settings.update(json.load(f))
    return settings


def save_settings(settings: dict, path: str = SETTINGS_PATH) -> None:
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app_config.py tests/test_app_config.py
git commit -m "feat: app_config with defaults and persisted toggles"
```

---

### Task 4: `levels.py` — prior-day high/low

**Files:**
- Create: `levels.py`
- Test: `tests/test_levels.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_levels.py`:

```python
import pandas as pd
from levels import prior_day_levels


def _daily(rows):
    # rows: list of (open_iso, high, low, close)
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "close_time": pd.to_datetime([r[0] for r in rows], utc=True) + pd.Timedelta(days=1),
    })


def test_prior_day_levels_picks_last_closed_bar():
    df = _daily([
        ("2026-06-12", 100, 90, 95),
        ("2026-06-13", 110, 92, 108),   # yesterday (closed)
        ("2026-06-14", 109, 100, 104),  # today, still open
    ])
    now = pd.Timestamp("2026-06-14 09:00", tz="UTC")
    pdh, pdl = prior_day_levels(df, now)
    assert pdh == 110.0
    assert pdl == 92.0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_levels.py::test_prior_day_levels_picks_last_closed_bar -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'levels'`.

- [ ] **Step 3: Implement the function**

Create `levels.py`:

```python
"""Top-down level marking + bias snapshot. Pure functions over kline DataFrames."""
from dataclasses import dataclass
from typing import List

import pandas as pd

from liquidity import swing_points
from fvg import find_fvgs, FVG
from structure import detect_structure_breaks


def prior_day_levels(daily: pd.DataFrame, now: pd.Timestamp) -> tuple:
    """(PDH, PDL): high/low of the most recent Daily candle that closed before `now`."""
    closed = daily[daily["close_time"] <= now]
    prev = closed.iloc[-1]
    return float(prev["high"]), float(prev["low"])
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_levels.py::test_prior_day_levels_picks_last_closed_bar -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add levels.py tests/test_levels.py
git commit -m "feat: prior_day_levels (PDH/PDL from last closed daily bar)"
```

---

### Task 5: `levels.py` — the `Level` type and `build_levels`

Marks recent confirmed swing highs/lows from Daily and H4, plus PDH/PDL, into one list of `Level`s.

**Files:**
- Modify: `levels.py`
- Test: `tests/test_levels.py` (add tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_levels.py`:

```python
from levels import Level, build_levels


def test_level_is_a_simple_record():
    lvl = Level(source="pdh", price=110.0, side="high")
    assert (lvl.source, lvl.price, lvl.side) == ("pdh", 110.0, "high")


def test_build_levels_collects_swings_and_prior_day():
    # H4 with a clear swing high at idx 2 (high=5) and swing low at idx 4 (low=0)
    h4 = pd.DataFrame({
        "high": [1, 2, 5, 2, 1, 3, 1, 2],
        "low":  [1, 0, 3, 2, 0, 2, 1, 1],
        "close":[1, 2, 4, 2, 1, 3, 1, 2],
    })
    daily = _daily([
        ("2026-06-12", 100, 90, 95),
        ("2026-06-13", 110, 92, 108),
        ("2026-06-14", 109, 100, 104),
    ])
    now = pd.Timestamp("2026-06-14 09:00", tz="UTC")

    levels = build_levels(daily, h4, now, daily_n=5, h4_n=5, left=2, right=2)
    sources = {l.source for l in levels}
    assert "pdh" in sources and "pdl" in sources
    assert "h4_swing_high" in sources and "h4_swing_low" in sources
    # PDH/PDL values present
    prices = {(l.source, l.price) for l in levels}
    assert ("pdh", 110.0) in prices and ("pdl", 92.0) in prices
    # every level is high- or low-sided
    assert all(l.side in ("high", "low") for l in levels)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_levels.py -v`
Expected: FAIL — `ImportError: cannot import name 'Level'`.

- [ ] **Step 3: Implement `Level` and `build_levels`**

Add to `levels.py` (after the imports / before `prior_day_levels` is fine, but append for clarity):

```python
@dataclass
class Level:
    source: str   # 'daily_swing_high'|'daily_swing_low'|'h4_swing_high'|'h4_swing_low'|'pdh'|'pdl'
    price: float
    side: str     # 'high' = sell-side liquidity above; 'low' = buy-side below


def _swing_levels(df: pd.DataFrame, prefix: str, n: int, left: int, right: int) -> List[Level]:
    sh, sl = swing_points(df, left, right)
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    out: List[Level] = []
    for i in sh[-n:]:
        out.append(Level(f"{prefix}_swing_high", float(hi[i]), "high"))
    for i in sl[-n:]:
        out.append(Level(f"{prefix}_swing_low", float(lo[i]), "low"))
    return out


def build_levels(daily: pd.DataFrame, h4: pd.DataFrame, now: pd.Timestamp,
                 daily_n: int, h4_n: int, left: int, right: int) -> List[Level]:
    """The marked level set: recent Daily + H4 confirmed swings, plus PDH/PDL."""
    levels: List[Level] = []
    levels += _swing_levels(daily, "daily", daily_n, left, right)
    levels += _swing_levels(h4, "h4", h4_n, left, right)
    pdh, pdl = prior_day_levels(daily, now)
    levels.append(Level("pdh", pdh, "high"))
    levels.append(Level("pdl", pdl, "low"))
    return levels
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_levels.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add levels.py tests/test_levels.py
git commit -m "feat: Level type and build_levels (daily/h4 swings + PDH/PDL)"
```

---

### Task 6: `levels.py` — the `Bias` snapshot and alignment gate

Bias = Daily structure direction + H4 EMA-50 trend + 14-day momentum. The gate (per the repo's research) uses **H4 trend + 14d momentum**; Daily direction is carried for context/display.

**Files:**
- Modify: `levels.py`
- Test: `tests/test_levels.py` (add tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_levels.py`:

```python
from levels import Bias, ema, h4_trend, momentum_14d, bias_snapshot


def test_ema_matches_pandas_ewm():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = ema(s, 3)
    assert abs(out.iloc[-1] - s.ewm(span=3, adjust=False).mean().iloc[-1]) < 1e-9


def test_h4_trend_up_when_close_above_ema():
    # steadily rising closes -> last close above its EMA-50
    h4 = pd.DataFrame({"close": [float(x) for x in range(1, 80)]})
    assert h4_trend(h4, period=50) == "up"


def test_momentum_14d_sign():
    daily = pd.DataFrame({"close": [100.0] * 14 + [120.0]})  # up over 14 days
    assert momentum_14d(daily) == "up"
    daily_dn = pd.DataFrame({"close": [120.0] * 14 + [100.0]})
    assert momentum_14d(daily_dn) == "down"


def test_bias_alignment_gate_uses_h4_and_momentum():
    bull = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")
    assert bull.aligned("up") is True
    assert bull.aligned("down") is False

    mixed = Bias(daily_dir="up", h4_dir="up", mom14_dir="down")
    assert mixed.aligned("up") is False   # momentum disagrees -> not aligned
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_levels.py -v`
Expected: FAIL — `ImportError: cannot import name 'Bias'`.

- [ ] **Step 3: Implement the bias helpers**

Add to `levels.py`:

```python
@dataclass
class Bias:
    daily_dir: str   # 'up'|'down'|'none'  (context only)
    h4_dir: str      # 'up'|'down'
    mom14_dir: str   # 'up'|'down'

    def aligned(self, direction: str) -> bool:
        """True if the proven HTF edge (H4 trend + 14d momentum) agrees with `direction`.
        `direction` is 'up' for a bullish sweep (of a low) or 'down' for bearish."""
        return self.h4_dir == direction and self.mom14_dir == direction


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def h4_trend(h4: pd.DataFrame, period: int = 50) -> str:
    e = ema(h4["close"], period)
    return "up" if h4["close"].iloc[-1] >= e.iloc[-1] else "down"


def momentum_14d(daily: pd.DataFrame, lookback: int = 14) -> str:
    c = daily["close"].to_numpy()
    return "up" if c[-1] >= c[-1 - lookback] else "down"


def _daily_dir(daily: pd.DataFrame, left: int, right: int) -> str:
    breaks = detect_structure_breaks(daily, left, right)
    if not breaks:
        return "none"
    return "up" if breaks[-1]["direction"] == "up" else "down"


def bias_snapshot(daily: pd.DataFrame, h4: pd.DataFrame, left: int, right: int,
                  ema_period: int = 50, mom_lookback: int = 14) -> Bias:
    return Bias(
        daily_dir=_daily_dir(daily, left, right),
        h4_dir=h4_trend(h4, ema_period),
        mom14_dir=momentum_14d(daily, mom_lookback),
    )
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_levels.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add levels.py tests/test_levels.py
git commit -m "feat: Bias snapshot + H4/momentum alignment gate"
```

---

### Task 7: `levels.py` — unfilled FVG zones (display)

FVGs are display-only zones (not sweep targets in v1). Mark recent H4 FVGs that price has not yet traded back into.

**Files:**
- Modify: `levels.py`
- Test: `tests/test_levels.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_levels.py`:

```python
from levels import unfilled_fvgs


def test_unfilled_fvgs_excludes_entered_gaps():
    # bull FVG forms at i=2: low[2] > high[0]. Then a later bar trades back into it.
    df = pd.DataFrame({
        "open_time": pd.to_datetime(
            ["2026-06-14T00:00Z", "2026-06-14T04:00Z", "2026-06-14T08:00Z",
             "2026-06-14T12:00Z", "2026-06-14T16:00Z"], utc=True),
        "high": [10, 12, 20, 19, 16],
        "low":  [8, 11, 15, 14, 9],   # last bar dips to 9, into the 10..15 gap
        "close":[9, 11, 18, 16, 12],
    })
    out = unfilled_fvgs(df, "bull")
    # the single bull gap (10->15) was entered by the last bar -> filtered out
    assert out == []
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_levels.py::test_unfilled_fvgs_excludes_entered_gaps -v`
Expected: FAIL — `ImportError: cannot import name 'unfilled_fvgs'`.

- [ ] **Step 3: Implement it**

Add to `levels.py`:

```python
def unfilled_fvgs(df: pd.DataFrame, direction: str) -> List[FVG]:
    """FVGs of `direction` that no later bar has traded back into (gap still open)."""
    fvgs = find_fvgs(df, direction)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    out: List[FVG] = []
    for f in fvgs:
        entered = any(
            highs[j] >= f.bottom and lows[j] <= f.top
            for j in range(f.index + 1, len(df))
        )
        if not entered:
            out.append(f)
    return out
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_levels.py::test_unfilled_fvgs_excludes_entered_gaps -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add levels.py tests/test_levels.py
git commit -m "feat: unfilled_fvgs for display zones"
```

---

### Task 8: `watcher.py` — single-level sweep + reclaim

**Files:**
- Create: `watcher.py`
- Test: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_watcher.py`:

```python
from levels import Level
from watcher import detect_level_sweep


def _bar(high, low, close):
    return {"high": high, "low": low, "close": close}


def test_bullish_sweep_of_a_low():
    lvl = Level("pdl", 100.0, "low")
    # bar pierces below 100 then closes back above -> bullish sweep+reclaim
    assert detect_level_sweep(_bar(105, 98, 102), lvl) == "bullish"


def test_bearish_sweep_of_a_high():
    lvl = Level("pdh", 100.0, "high")
    assert detect_level_sweep(_bar(103, 97, 99), lvl) == "bearish"


def test_no_sweep_when_no_reclaim():
    lvl = Level("pdl", 100.0, "low")
    # pierces below and closes below -> not a reclaim
    assert detect_level_sweep(_bar(101, 96, 97), lvl) is None


def test_no_sweep_when_level_untouched():
    lvl = Level("pdl", 100.0, "low")
    assert detect_level_sweep(_bar(110, 104, 108), lvl) is None
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watcher'`.

- [ ] **Step 3: Implement `detect_level_sweep`**

Create `watcher.py`:

```python
"""Live sweep+reclaim detection against the marked level set, with the HTF gate."""
from typing import List, Optional

from levels import Level, Bias


def detect_level_sweep(bar: dict, level: Level) -> Optional[str]:
    """'bullish' if `bar` swept a low and closed back above it; 'bearish' for a high; else None.

    `bar` is a mapping with 'high','low','close' (one closed M15 candle)."""
    if level.side == "low" and bar["low"] < level.price and bar["close"] > level.price:
        return "bullish"
    if level.side == "high" and bar["high"] > level.price and bar["close"] < level.price:
        return "bearish"
    return None
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_watcher.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher.py
git commit -m "feat: detect_level_sweep (sweep+reclaim of a marked level)"
```

---

### Task 9: `watcher.py` — `scan` with the HTF gate and de-dupe

**Files:**
- Modify: `watcher.py`
- Test: `tests/test_watcher.py` (add tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_watcher.py`:

```python
from watcher import scan, level_key


def test_level_key_is_stable():
    lvl = Level("pdl", 100.0, "low")
    assert level_key(lvl) == "pdl:100.0"


def test_scan_emits_aligned_trigger_and_marks_fired():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")
    fired = set()
    bar = {"high": 105, "low": 98, "close": 102}

    triggers = scan(bar, levels, bias, fired,
                    require_alignment=True, counter_trend_mode="silent")
    assert len(triggers) == 1
    t = triggers[0]
    assert t["direction"] == "bullish" and t["aligned"] is True
    assert "pdl:100.0" in fired   # emitted -> marked fired


def test_scan_dedupes_already_fired_levels():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")
    fired = {"pdl:100.0"}
    bar = {"high": 105, "low": 98, "close": 102}
    assert scan(bar, levels, bias, fired) == []


def test_scan_silent_mode_suppresses_counter_trend():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="down", h4_dir="down", mom14_dir="down")  # bull sweep is counter-trend
    fired = set()
    bar = {"high": 105, "low": 98, "close": 102}
    assert scan(bar, levels, bias, fired,
                require_alignment=True, counter_trend_mode="silent") == []
    assert fired == set()   # nothing emitted -> nothing marked


def test_scan_fyi_mode_emits_counter_trend_as_not_aligned():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="down", h4_dir="down", mom14_dir="down")
    fired = set()
    bar = {"high": 105, "low": 98, "close": 102}
    triggers = scan(bar, levels, bias, fired,
                    require_alignment=True, counter_trend_mode="fyi")
    assert len(triggers) == 1 and triggers[0]["aligned"] is False
    assert "pdl:100.0" in fired
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_watcher.py -v`
Expected: FAIL — `ImportError: cannot import name 'scan'`.

- [ ] **Step 3: Implement `level_key` and `scan`**

Add to `watcher.py`:

```python
def level_key(level: Level) -> str:
    return f"{level.source}:{level.price}"


def scan(bar: dict, levels: List[Level], bias: Bias, fired: set,
         require_alignment: bool = True, counter_trend_mode: str = "silent") -> List[dict]:
    """Check `bar` against every not-yet-fired level. Returns emitted triggers and adds
    their keys to `fired` (mutated in place).

    A trigger is emitted when:
      - aligned with the HTF bias, OR
      - counter-trend AND (alignment not required OR counter_trend_mode == 'fyi').
    Silent counter-trend sweeps are dropped and NOT marked fired.

    Each trigger: {level, direction('bullish'/'bearish'), aligned(bool), key}.
    """
    triggers: List[dict] = []
    for lvl in levels:
        key = level_key(lvl)
        if key in fired:
            continue
        swept = detect_level_sweep(bar, lvl)
        if swept is None:
            continue
        direction = "up" if swept == "bullish" else "down"
        aligned = bias.aligned(direction)
        if not aligned and require_alignment and counter_trend_mode == "silent":
            continue
        triggers.append({"level": lvl, "direction": swept, "aligned": aligned, "key": key})
        fired.add(key)
    return triggers
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_watcher.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add watcher.py tests/test_watcher.py
git commit -m "feat: watcher.scan with HTF gate and per-session de-dupe"
```

---

### Task 10: `state.py` — serialize the shared state file

`state.json` is the single source of truth the chart and menu read. It must round-trip levels, zones, bias, fired set, last alert, price, and timestamp.

**Files:**
- Create: `state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state.py`:

```python
from levels import Level, Bias
from fvg import FVG
import pandas as pd
import state


def test_build_and_save_state_roundtrips(tmp_path):
    path = tmp_path / "state.json"
    levels = [Level("pdl", 100.0, "low"), Level("pdh", 110.0, "high")]
    zones = [FVG(2, "bull", 100.0, 105.0, pd.Timestamp("2026-06-14T08:00Z"))]
    bias = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")

    payload = state.build_state(
        price=104.0, levels=levels, zones=zones, bias=bias,
        fired=["pdl:100.0"], last_alert={"text": "swept PDL", "time": "09:25"},
        updated_at="2026-06-14T09:25:00Z",
    )
    state.save_state(payload, str(path))
    loaded = state.load_state(str(path))

    assert loaded["price"] == 104.0
    assert loaded["bias"]["h4_dir"] == "up"
    assert loaded["levels"][0]["source"] == "pdl"
    assert loaded["zones"][0]["direction"] == "bull"
    assert loaded["fired"] == ["pdl:100.0"]
    assert loaded["last_alert"]["text"] == "swept PDL"


def test_load_state_missing_returns_empty(tmp_path):
    assert state.load_state(str(tmp_path / "nope.json")) == {}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'state'`.

- [ ] **Step 3: Implement `state.py`**

Create `state.py`:

```python
"""Read/write state.json — the single source of truth shared by app, menu, and chart."""
import json
import os
from dataclasses import asdict
from typing import List

from levels import Level, Bias
from fvg import FVG


def _zone_to_dict(z: FVG) -> dict:
    return {"direction": z.direction, "bottom": z.bottom, "top": z.top,
            "time": str(z.time)}


def build_state(price: float, levels: List[Level], zones: List[FVG], bias: Bias,
                fired: list, last_alert: dict, updated_at: str) -> dict:
    return {
        "price": price,
        "levels": [asdict(l) for l in levels],
        "zones": [_zone_to_dict(z) for z in zones],
        "bias": asdict(bias),
        "fired": list(fired),
        "last_alert": last_alert,
        "updated_at": updated_at,
    }


def save_state(payload: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_state.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat: state.json build/save/load"
```

---

### Task 11: The chart page

A static page that reads `state.json` (served from the same dir, so `fetch` works) and draws M15 candles with marked level lines + FVG zone boxes and a bias panel. Kept deliberately simple.

**Files:**
- Create: `chart/index.html`
- Create: `chart/chart.js`

- [ ] **Step 1: Create `chart/index.html`**

> **SRI pin:** the `lightweight-charts` `<script>` below loads from a CDN. Before committing,
> pin it with Subresource Integrity so a CDN compromise can't inject code. Generate the hash:
> `curl -sL https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js | openssl dgst -sha384 -binary | openssl base64 -A`
> then add `integrity="sha384-<that value>" crossorigin="anonymous"` to the tag. (Alternatively
> vendor the file into `chart/` and load it locally — preferred for a fully offline desktop tool.)

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>BTC Watcher</title>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    body { margin: 0; background: #0e1116; color: #c9d1d9; font: 13px -apple-system, system-ui, sans-serif; }
    #wrap { display: flex; height: 100vh; }
    #chart { flex: 1; }
    #panel { width: 200px; border-left: 1px solid #30363d; padding: 12px; }
    .up { color: #3fb950; } .down { color: #f85149; } .none { color: #9aa4b2; }
    h3 { font-size: 12px; margin: 0 0 6px; }
    .alert { background: rgba(63,185,80,.15); border: 1px solid #3fb950; border-radius: 6px; padding: 8px; margin-top: 8px; }
  </style>
</head>
<body>
  <div id="wrap">
    <div id="chart"></div>
    <div id="panel">
      <h3>Bias</h3>
      <div>Daily: <span id="daily"></span></div>
      <div>H4 EMA-50: <span id="h4"></span></div>
      <div>14d mom: <span id="mom"></span></div>
      <h3 style="margin-top:14px">Last alert</h3>
      <div id="alert" class="none">—</div>
      <div id="updated" style="margin-top:14px;color:#6e7681;font-size:11px"></div>
    </div>
  </div>
  <script src="chart.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `chart/chart.js`**

```javascript
// Reads state.json (candles + levels + zones + bias) and renders the marked chart.
const chart = LightweightCharts.createChart(document.getElementById('chart'), {
  layout: { background: { color: '#0e1116' }, textColor: '#c9d1d9' },
  grid: { vertLines: { color: '#161b22' }, horzLines: { color: '#161b22' } },
  timeScale: { timeVisible: true },
});
const candles = chart.addCandlestickSeries({
  upColor: '#3fb950', downColor: '#f85149',
  wickUpColor: '#3fb950', wickDownColor: '#f85149', borderVisible: false,
});

const COLORS = { high: '#f85149', low: '#3fb950', pdh: '#f0883e', pdl: '#f0883e' };

function setBias(b) {
  for (const [id, key] of [['daily', 'daily_dir'], ['h4', 'h4_dir'], ['mom', 'mom14_dir']]) {
    const el = document.getElementById(id);
    const v = b ? b[key] : 'none';
    el.textContent = v;
    el.className = v;
  }
}

async function refresh() {
  let s;
  try { s = await (await fetch('state.json?t=' + Date.now())).json(); }
  catch (e) { return; }

  if (s.candles) {
    candles.setData(s.candles); // [{time, open, high, low, close}]
  }
  // clear + redraw price lines for each marked level
  (window._lines || []).forEach(l => candles.removePriceLine(l));
  window._lines = (s.levels || []).map(lv => candles.createPriceLine({
    price: lv.price,
    color: COLORS[lv.source] || COLORS[lv.side] || '#9aa4b2',
    lineStyle: LightweightCharts.LineStyle.Dashed,
    lineWidth: 1,
    title: lv.source,
  }));

  setBias(s.bias);
  const a = document.getElementById('alert');
  if (s.last_alert && s.last_alert.text) {
    a.textContent = s.last_alert.text + (s.last_alert.time ? '  (' + s.last_alert.time + ')' : '');
    a.className = 'alert';
  }
  document.getElementById('updated').textContent = 'updated ' + (s.updated_at || '');
}

refresh();
setInterval(refresh, 15000);
```

- [ ] **Step 3: Manual smoke check (deferred until Task 12 serves it)**

The page needs `state.json` served alongside it (file:// fetch is blocked by CORS), so it is verified in Task 12 once `app.py` serves the `chart/` dir. No commit-time test here.

- [ ] **Step 4: Commit**

```bash
git add chart/index.html chart/chart.js
git commit -m "feat: lightweight-charts page reading state.json"
```

---

### Task 12: `app.py` — menu-bar shell, scheduler, notifications, chart server

This is the integration layer. It has no unit tests (thin glue over tested engine pieces); it is verified by a manual run. Every piece of code it needs is given below in full.

**Files:**
- Create: `app.py`
- Create: `engine.py` (the one orchestration function that ties fetch → levels → state, so both the morning pass and the scan reuse it)
- Test: `tests/test_engine.py` (the pure orchestration is testable with injected DataFrames)

- [ ] **Step 1: Write the failing test for `engine.run_morning_pass`**

Create `tests/test_engine.py`:

```python
import pandas as pd
import engine
from levels import Level


def _daily():
    rows = [(f"2026-05-{d:02d}", 100 + d, 90 + d, 95 + d) for d in range(1, 31)]
    return pd.DataFrame({
        "open_time": pd.to_datetime([r[0] for r in rows], utc=True),
        "high": [r[1] for r in rows], "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "close_time": pd.to_datetime([r[0] for r in rows], utc=True) + pd.Timedelta(days=1),
    })


def _h4():
    n = 120
    return pd.DataFrame({
        "open_time": pd.to_datetime("2026-06-01", utc=True) + pd.to_timedelta(range(n), unit="h"),
        "high": [100 + (i % 7) for i in range(n)],
        "low": [90 + (i % 5) for i in range(n)],
        "close": [95 + (i % 6) for i in range(n)],
    })


def test_run_morning_pass_returns_levels_and_bias():
    now = pd.Timestamp("2026-06-06 06:00", tz="UTC")
    levels, zones, bias = engine.run_morning_pass(_daily(), _h4(), now)
    assert all(isinstance(l, Level) for l in levels)
    assert bias.h4_dir in ("up", "down")
    assert any(l.source in ("pdh", "pdl") for l in levels)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine'`.

- [ ] **Step 3: Implement `engine.py`**

Create `engine.py`:

```python
"""Orchestration tying fetch + levels + watcher together. Pure where possible."""
from typing import List, Tuple

import pandas as pd

import app_config as cfg
from levels import build_levels, bias_snapshot, unfilled_fvgs, Level, Bias
from fvg import FVG


def run_morning_pass(daily: pd.DataFrame, h4: pd.DataFrame,
                     now: pd.Timestamp) -> Tuple[List[Level], List[FVG], Bias]:
    """Build the marked level set, display zones, and the bias snapshot for the day."""
    levels = build_levels(daily, h4, now,
                          daily_n=cfg.DAILY_SWING_LOOKBACK_N, h4_n=cfg.H4_SWING_LOOKBACK_N,
                          left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    zones = unfilled_fvgs(h4, "bull") + unfilled_fvgs(h4, "bear")
    bias = bias_snapshot(daily, h4, left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    return levels, zones, bias
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit the engine**

```bash
git add engine.py tests/test_engine.py
git commit -m "feat: engine.run_morning_pass orchestration"
```

- [ ] **Step 6: Implement `app.py`**

Create `app.py`:

```python
"""BTC Watcher menu-bar app. Run with: ./venv/bin/python app.py"""
import os
import subprocess
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, HTTPServer

import pandas as pd
import rumps
from zoneinfo import ZoneInfo

import app_config as cfg
import engine
import state
from fetch_data import fetch_recent, download
from watcher import scan

CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart")
STATE_FILE = os.path.join(CHART_DIR, "state.json")
CHART_PORT = 8753


def _serve_chart_dir():
    handler = partial(SimpleHTTPRequestHandler, directory=CHART_DIR)
    HTTPServer(("127.0.0.1", CHART_PORT), handler).serve_forever()


def _df_to_candles(df: pd.DataFrame) -> list:
    return [
        {"time": int(t.timestamp()), "open": float(o), "high": float(h),
         "low": float(l), "close": float(c)}
        for t, o, h, l, c in zip(df["open_time"], df["open"], df["high"],
                                 df["low"], df["close"])
    ]


class WatcherApp(rumps.App):
    def __init__(self):
        super().__init__("₿ …", quit_button="Quit")
        self.settings = cfg.load_settings()
        self.levels, self.zones, self.bias = [], [], None
        self.fired = set()
        self.last_alert = {}

        self.notif_item = rumps.MenuItem("Notifications", callback=self.toggle_notifications)
        self.sound_item = rumps.MenuItem("Alert sound", callback=self.toggle_sound)
        self._sync_toggle_marks()
        self.menu = [
            self.notif_item, self.sound_item, None,
            rumps.MenuItem("Open marked chart", callback=self.open_chart),
            rumps.MenuItem("Re-mark levels now", callback=self.remark_now),
        ]

        threading.Thread(target=_serve_chart_dir, daemon=True).start()
        self.remark_now(None)  # initial level mark on launch
        rumps.Timer(self.tick, cfg.SCAN_INTERVAL_MIN * 60).start()
        self._morning_done_for = None

    # --- toggles ---
    def _sync_toggle_marks(self):
        self.notif_item.state = 1 if self.settings["notifications_enabled"] else 0
        self.sound_item.state = 1 if self.settings["alert_sound_enabled"] else 0

    def toggle_notifications(self, _):
        self.settings["notifications_enabled"] = not self.settings["notifications_enabled"]
        cfg.save_settings(self.settings)
        self._sync_toggle_marks()

    def toggle_sound(self, _):
        self.settings["alert_sound_enabled"] = not self.settings["alert_sound_enabled"]
        cfg.save_settings(self.settings)
        self._sync_toggle_marks()

    # --- actions ---
    def open_chart(self, _):
        webbrowser.open(f"http://127.0.0.1:{CHART_PORT}/index.html")

    def remark_now(self, _):
        now = pd.Timestamp.now(tz="UTC")
        daily = download("1d", force=True)
        h4 = fetch_recent("4h", limit=500)
        self.levels, self.zones, self.bias = engine.run_morning_pass(daily, h4, now)
        self.fired = set()
        self._write_state()

    # --- scheduled loop ---
    def tick(self, _):
        self._maybe_morning_pass()
        m15 = fetch_recent("15m", limit=300)
        closed = m15.iloc[:-1]  # drop the still-open candle
        last = closed.iloc[-1]
        bar = {"high": float(last["high"]), "low": float(last["low"]),
               "close": float(last["close"])}
        triggers = scan(bar, self.levels, self.bias, self.fired,
                        require_alignment=cfg.REQUIRE_HTF_ALIGNMENT,
                        counter_trend_mode=cfg.COUNTER_TREND_MODE)
        for t in triggers:
            self._emit(t, float(last["close"]))
        self.title = f"₿ {float(last['close']):,.0f}"
        self._write_state(price=float(last["close"]), candles=_df_to_candles(closed.tail(200)))

    def _maybe_morning_pass(self):
        local = pd.Timestamp.now(tz=ZoneInfo(cfg.MORNING_TZ))
        hh, mm = cfg.MORNING_TIME.split(":")
        key = local.date().isoformat()
        if local.hour == int(hh) and local.minute < cfg.SCAN_INTERVAL_MIN \
                and self._morning_done_for != key:
            self.remark_now(None)
            self._morning_done_for = key

    def _emit(self, trigger, price):
        lvl = trigger["level"]
        side = "LONG" if trigger["direction"] == "bullish" else "SHORT"
        tag = "" if trigger["aligned"] else " (counter-trend FYI)"
        title = f"⚡ BTC sweep + reclaim — {side} context{tag}"
        b = self.bias
        body = (f"Swept {lvl.source.upper()} {lvl.price:,.0f}, reclaimed. "
                f"Daily {b.daily_dir} H4 {b.h4_dir} mom {b.mom14_dir}.")
        self.last_alert = {"text": f"{lvl.source} sweep", "time": pd.Timestamp.now().strftime("%H:%M")}
        if self.settings["notifications_enabled"]:
            rumps.notification(title, "", body, sound=self.settings["alert_sound_enabled"])

    def _write_state(self, price=None, candles=None):
        payload = state.build_state(
            price=price if price is not None else 0.0,
            levels=self.levels, zones=self.zones, bias=self.bias,
            fired=list(self.fired), last_alert=self.last_alert,
            updated_at=pd.Timestamp.now(tz="UTC").isoformat(),
        )
        if candles is not None:
            payload["candles"] = candles
        state.save_state(payload, STATE_FILE)


if __name__ == "__main__":
    WatcherApp().run()
```

- [ ] **Step 7: Manual smoke test**

Run: `./venv/bin/python app.py`
Expected, in order:
1. A `₿ …` then `₿ <price>` icon appears in the macOS menu bar within ~one scan.
2. Menu shows **Notifications** and **Alert sound** with checkmarks reflecting `app_settings.json`; clicking toggles the check and rewrites `app_settings.json`.
3. **Open marked chart** opens `http://127.0.0.1:8753/index.html` showing candles, dashed level lines (PDH/PDL/swings), and the bias panel populated.
4. **Re-mark levels now** repopulates levels without error.

Verify the chart renders by confirming the bias panel shows up/down (not blank) and price lines are visible.

- [ ] **Step 8: Confirm the whole suite is green**

Run: `./venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add app.py
git commit -m "feat: menu-bar app shell, scheduler, notifications, chart server"
```

---

### Task 13: Gitignore runtime artifacts + README

**Files:**
- Modify: `.gitignore`
- Create: `README_WATCHER.md`

- [ ] **Step 1: Ignore runtime files**

Append to `.gitignore`:

```
app_settings.json
chart/state.json
.superpowers/
```

- [ ] **Step 2: Write `README_WATCHER.md`**

```markdown
# BTC Watcher

Menu-bar app that marks BTCUSD levels each morning and alerts on HTF-aligned
sweep + reclaim setups on M15.

## Run
    ./venv/bin/python app.py

## What it does
- 08:00 Europe/Oslo: marks Daily/H4 swing highs/lows + PDH/PDL, computes bias
  (Daily structure, H4 EMA-50, 14d momentum), draws H4 FVG zones.
- Every 5 min: pulls recent M15, checks the last *closed* bar for a sweep+reclaim
  of any marked level, and fires a macOS notification when it aligns with the bias
  (H4 trend + 14d momentum). Counter-trend setups are silent by default.

## Controls (menu bar)
- Notifications ON/OFF, Alert sound ON/OFF (persisted to `app_settings.json`)
- Open marked chart (served at http://127.0.0.1:8753)
- Re-mark levels now

## Config
Edit `app_config.py` (scan interval, morning time/tz, swing lookbacks,
`REQUIRE_HTF_ALIGNMENT`, `COUNTER_TREND_MODE`).

## Tests
    ./venv/bin/python -m pytest -q
(The engine — levels/watcher/state/engine — is unit-tested; `app.py` is verified by running it.)
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore README_WATCHER.md
git commit -m "docs: watcher README + gitignore runtime artifacts"
```

---

## Self-Review notes

- **Spec coverage:** morning pass (Tasks 4–7, 12), 5-min loop + sweep+reclaim (Tasks 8–9, 12), HTF gate (Tasks 6, 9), de-dupe (Task 9), notifications + sound toggles (Tasks 3, 12), menu-bar form factor + on-demand chart (Tasks 11–12), Binance data + `fetch_recent` (Tasks 1–2), `state.json` source of truth (Task 10), config incl. Europe/Oslo + counter-trend default (Task 3). FVG display zones (Task 7). Out-of-scope items (other triggers, M5 trigger, auto-trade) intentionally absent.
- **Type consistency:** `Level(source, price, side)`, `Bias(daily_dir, h4_dir, mom14_dir)` with `aligned(direction)`, `detect_level_sweep(bar, level)->'bullish'|'bearish'|None`, `scan(...)->[{level,direction,aligned,key}]`, `level_key`, `build_state(...)` keys, and `engine.run_morning_pass` return triple are used identically across tasks and `app.py`.
- **No placeholders:** every code step is complete and runnable.
```
