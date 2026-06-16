# Multi-Instrument Live (Phase 3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Monitor XAUUSD + EURUSD live alongside BTCUSD by adding a Twelve Data adapter behind a data-source abstraction, a session gate, secure Keychain key storage, and a multi-symbol app loop with a per-symbol chart switcher.

**Architecture:** A `datasource.py` abstraction with `BinanceSource` (crypto, wraps existing `fetch_data`) and `TwelveDataSource` (forex/gold, normalizes to the same OHLCV frame). `instruments.py` gains `source`/`provider_symbol`. The app loops `ENABLED_SYMBOLS`, keeps per-symbol state, gates forex to a session window, and writes `state-<symbol>.json`. The scorer / state machine / triggers are **unchanged** (already multi-instrument).

**Tech Stack:** Python 3.9+, pandas, requests, `keyring` (macOS Keychain). pytest. The data adapters are tested with mocked HTTP + mocked key lookup; the app shell is verified by `import app` + a live smoke run.

**Spec:** `docs/2026-06-16-multi-instrument-phase3-design.md`

**Repo & conventions:** Trade Assistant repo, flat layout, flat imports, tests `tests/test_<module>.py`, pure functions + docstrings. Run `./venv/bin/python -m pytest`.

**Reused interfaces (do not change behavior):**
- `instruments.Instrument(symbol, units, pip_size, aoi_band, cluster_band, min_rr, stop_buffer, factor_weights, label_thresholds)`; `get_instrument(symbol)`.
- `fetch_data.klines_to_df(rows)`, `fetch_data.fetch_recent(interval, limit)` (Binance, `config.SYMBOL`/`config.BINANCE_BASE`).
- `engine.run_morning_pass(daily, h4, now)`, `engine.score_pass(weekly, daily, h4, etf, now, symbol)`.
- `bias.bias_map(weekly, daily, h4)`; `watcher.scan(...)`; `tracker.Tracker`; `state.build_state(...)`.
- OHLCV frame contract: columns `open_time, open, high, low, close, volume, close_time`, ascending, tz-aware UTC.

---

### Task 1: `instruments.py` — add `source` + `provider_symbol`

**Files:** Modify `instruments.py`; Test `tests/test_instrument_sources.py`

- [ ] **Step 1: Write the failing test**

```python
from instruments import get_instrument


def test_btc_is_binance():
    i = get_instrument("BTCUSDT")
    assert i.source == "binance" and i.provider_symbol == "BTCUSDT"


def test_xau_eur_are_twelvedata():
    x = get_instrument("XAUUSD")
    e = get_instrument("EURUSD")
    assert x.source == "twelvedata" and x.provider_symbol == "XAU/USD"
    assert e.source == "twelvedata" and e.provider_symbol == "EUR/USD"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_instrument_sources.py -v`
Expected: FAIL — `AttributeError: 'Instrument' object has no attribute 'source'`.

- [ ] **Step 3: Add the two fields and populate**

In `instruments.py`, add two fields to the `Instrument` dataclass AFTER `label_thresholds` (defaulted so construction order is safe):

```python
    source: str = "binance"          # "binance" | "twelvedata"
    provider_symbol: str = ""         # symbol string for that source's API
```

Then in each `INSTRUMENTS` entry add the two keyword args:
- BTCUSDT: `source="binance", provider_symbol="BTCUSDT"`
- XAUUSD: `source="twelvedata", provider_symbol="XAU/USD"`
- EURUSD: `source="twelvedata", provider_symbol="EUR/USD"`

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_instrument_sources.py -v`
Expected: 2 passed. Then `./venv/bin/python -m pytest -q` — all prior tests still green (defaults keep existing construction valid).

- [ ] **Step 5: Commit**

```bash
git add instruments.py tests/test_instrument_sources.py
git commit -m "feat: per-instrument source + provider_symbol"
```

---

### Task 2: `fetch_data.py` — symbol-parameterized recent fetch

**Files:** Modify `fetch_data.py`; Test `tests/test_fetch_data.py` (add)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fetch_data.py`:

```python
def test_fetch_recent_symbol_uses_given_symbol(monkeypatch):
    import fetch_data
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return [[1700000000000, "1", "2", "0.5", "1.5", "9", 1700000899999]]

    def _fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _Resp()

    monkeypatch.setattr(fetch_data.requests, "get", _fake_get)
    df = fetch_data.fetch_recent_symbol("ETHUSDT", "4h", 1)
    assert captured["symbol"] == "ETHUSDT" and captured["interval"] == "4h"
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume", "close_time"]
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_fetch_data.py::test_fetch_recent_symbol_uses_given_symbol -v`
Expected: FAIL — `AttributeError: ... has no attribute 'fetch_recent_symbol'`.

- [ ] **Step 3: Add `fetch_recent_symbol` and make `fetch_recent` delegate**

In `fetch_data.py`, add:

```python
def fetch_recent_symbol(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    """Most recent `limit` Binance klines for an arbitrary symbol (no caching)."""
    resp = requests.get(
        config.BINANCE_BASE,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return klines_to_df(resp.json())
```

Then change the existing `fetch_recent` body to delegate:

```python
def fetch_recent(interval: str, limit: int = 300) -> pd.DataFrame:
    """Most recent `limit` klines for `config.SYMBOL` (back-compat wrapper)."""
    return fetch_recent_symbol(config.SYMBOL, interval, limit)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_fetch_data.py -v`
Expected: all pass (the existing `test_fetch_recent_builds_df_from_api` still passes via the wrapper).

- [ ] **Step 5: Commit**

```bash
git add fetch_data.py tests/test_fetch_data.py
git commit -m "feat: fetch_recent_symbol (symbol-parameterized Binance fetch)"
```

---

### Task 3: `datasource.py` — `BinanceSource` + dispatch

**Files:** Create `datasource.py`; Test `tests/test_datasource_binance.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
import datasource
from instruments import get_instrument


def test_fetch_recent_for_binance_dispatches_with_provider_symbol(monkeypatch):
    seen = {}

    def _fake(symbol, interval, limit):
        seen.update(symbol=symbol, interval=interval, limit=limit)
        return pd.DataFrame({"open_time": [], "open": [], "high": [], "low": [],
                             "close": [], "volume": [], "close_time": []})

    import fetch_data
    monkeypatch.setattr(fetch_data, "fetch_recent_symbol", _fake)
    btc = get_instrument("BTCUSDT")
    datasource.fetch_recent_for(btc, "15m", 200)
    assert seen == {"symbol": "BTCUSDT", "interval": "15m", "limit": 200}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_datasource_binance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'datasource'`.

- [ ] **Step 3: Create `datasource.py` (Binance + dispatch only for now)**

```python
"""Data-source abstraction: one interface, per-provider adapters. The engine consumes
the same OHLCV frame shape regardless of where candles come from."""
import fetch_data
from instruments import Instrument


class BinanceSource:
    """Crypto candles via Binance (wraps fetch_data). Identity interval map."""
    INTERVAL_MAP = {"1w": "1w", "1d": "1d", "4h": "4h", "15m": "15m", "5m": "5m"}

    def fetch_recent(self, provider_symbol, our_interval, limit):
        return fetch_data.fetch_recent_symbol(
            provider_symbol, self.INTERVAL_MAP[our_interval], limit)


SOURCES = {"binance": BinanceSource()}


def fetch_recent_for(inst: Instrument, our_interval: str, limit: int = 300):
    """Fetch recent candles for `inst` from its configured source."""
    return SOURCES[inst.source].fetch_recent(inst.provider_symbol, our_interval, limit)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `./venv/bin/python -m pytest tests/test_datasource_binance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add datasource.py tests/test_datasource_binance.py
git commit -m "feat: datasource abstraction + BinanceSource + fetch_recent_for dispatch"
```

---

### Task 4: `datasource.py` — `TwelveDataSource`

**Files:** Modify `datasource.py`; Test `tests/test_datasource_twelvedata.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
import pytest
import datasource


SAMPLE = {
    "values": [
        {"datetime": "2026-06-16 09:30:00", "open": "2300.0", "high": "2305.0",
         "low": "2299.0", "close": "2304.0", "volume": "10"},
        {"datetime": "2026-06-16 09:45:00", "open": "2304.0", "high": "2306.0",
         "low": "2301.0", "close": "2302.0", "volume": "8"},
    ],
    "status": "ok",
}


def _src(monkeypatch, payload=SAMPLE):
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return payload
    captured = {}
    def _fake_get(url, params=None, timeout=None):
        captured.update(params); captured["url"] = url
        return _Resp()
    monkeypatch.setattr(datasource.requests, "get", _fake_get)
    src = datasource.TwelveDataSource()
    monkeypatch.setattr(src, "_api_key", lambda: "KEY")
    return src, captured


def test_normalizes_and_maps_interval_symbol(monkeypatch):
    src, captured = _src(monkeypatch)
    df = src.fetch_recent("XAU/USD", "15m", 2)
    assert captured["symbol"] == "XAU/USD" and captured["interval"] == "15min"
    assert captured["order"] == "ASC" and captured["outputsize"] == 2
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume", "close_time"]
    assert str(df["open_time"].dt.tz) == "UTC"
    assert df["high"].iloc[0] == 2305.0
    # close_time = open_time + 15min
    assert (df["close_time"].iloc[0] - df["open_time"].iloc[0]) == pd.Timedelta("15min")


def test_status_error_raises(monkeypatch):
    src, _ = _src(monkeypatch, {"status": "error", "message": "bad symbol"})
    with pytest.raises(RuntimeError):
        src.fetch_recent("XAU/USD", "15m", 2)


def test_api_key_keychain_then_env_then_error(monkeypatch):
    import os
    src = datasource.TwelveDataSource()
    # keychain hit
    monkeypatch.setattr(datasource, "_keyring_get", lambda: "FROM_KC")
    assert src._api_key() == "FROM_KC"
    # keychain miss -> env
    monkeypatch.setattr(datasource, "_keyring_get", lambda: None)
    monkeypatch.setenv("TWELVEDATA_API_KEY", "FROM_ENV")
    assert src._api_key() == "FROM_ENV"
    # neither -> error
    monkeypatch.setattr(datasource, "_keyring_get", lambda: None)
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        src._api_key()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_datasource_twelvedata.py -v`
Expected: FAIL — `AttributeError: module 'datasource' has no attribute 'TwelveDataSource'` (and no `requests` import yet).

- [ ] **Step 3: Add `TwelveDataSource` + key helpers to `datasource.py`**

Add `import os`, `import requests`, `import pandas as pd` to the top of `datasource.py`, then:

```python
TWELVEDATA_BASE = "https://api.twelvedata.com/time_series"


def _keyring_get():
    """Read the Twelve Data key from the macOS Keychain, or None if unavailable."""
    try:
        import keyring
        return keyring.get_password("trade-assistant", "twelvedata")
    except Exception:
        return None


class TwelveDataSource:
    """Forex/commodity candles via Twelve Data, normalized to the Binance frame shape."""
    INTERVAL_MAP = {"1w": "1week", "1d": "1day", "4h": "4h", "15m": "15min", "5m": "5min"}
    _DURATION = {"1w": pd.Timedelta("7D"), "1d": pd.Timedelta("1D"),
                 "4h": pd.Timedelta("4h"), "15m": pd.Timedelta("15min"),
                 "5m": pd.Timedelta("5min")}

    def _api_key(self):
        key = _keyring_get()
        if key:
            return key
        key = os.environ.get("TWELVEDATA_API_KEY")
        if key:
            return key
        raise RuntimeError(
            "No Twelve Data API key. Run set_api_key.py to store it in the Keychain, "
            "or set the TWELVEDATA_API_KEY env var.")

    def fetch_recent(self, provider_symbol, our_interval, limit):
        resp = requests.get(TWELVEDATA_BASE, params={
            "symbol": provider_symbol,
            "interval": self.INTERVAL_MAP[our_interval],
            "outputsize": limit,
            "order": "ASC",
            "timezone": "UTC",
            "apikey": self._api_key(),
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"Twelve Data error for {provider_symbol}: {data.get('message')}")
        return self._normalize(data["values"], our_interval)

    def _normalize(self, values, our_interval):
        open_time = pd.to_datetime([v["datetime"] for v in values], utc=True)
        df = pd.DataFrame({
            "open_time": open_time,
            "open": [float(v["open"]) for v in values],
            "high": [float(v["high"]) for v in values],
            "low": [float(v["low"]) for v in values],
            "close": [float(v["close"]) for v in values],
            "volume": [float(v.get("volume", 0) or 0) for v in values],
            "close_time": open_time + self._DURATION[our_interval],
        })
        return df
```

Then register it in `SOURCES`:

```python
SOURCES = {"binance": BinanceSource(), "twelvedata": TwelveDataSource()}
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_datasource_twelvedata.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add datasource.py tests/test_datasource_twelvedata.py
git commit -m "feat: TwelveDataSource (normalize + interval/symbol map + Keychain key)"
```

---

### Task 5: `sessions.py` + config (ENABLED_SYMBOLS, FOREX_SESSION_UTC)

**Files:** Create `sessions.py`; Modify `app_config.py`; Test `tests/test_sessions.py`

- [ ] **Step 1: Add config to `app_config.py`** (after the Phase 2 block)

```python
# --- Phase 3 multi-instrument ---
ENABLED_SYMBOLS = ("BTCUSDT", "XAUUSD", "EURUSD")
FOREX_SESSION_UTC = (8, 22)          # scan forex only within [start, end) UTC, weekdays
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_sessions.py`:

```python
import pandas as pd
from sessions import in_forex_session


def test_in_window_weekday_true():
    t = pd.Timestamp("2026-06-16 10:00", tz="UTC")  # Tuesday
    assert in_forex_session(t, (8, 22)) is True


def test_out_of_window_false():
    t = pd.Timestamp("2026-06-16 23:30", tz="UTC")
    assert in_forex_session(t, (8, 22)) is False
    t2 = pd.Timestamp("2026-06-16 06:00", tz="UTC")
    assert in_forex_session(t2, (8, 22)) is False


def test_weekend_false_even_in_window():
    sat = pd.Timestamp("2026-06-20 10:00", tz="UTC")  # Saturday
    sun = pd.Timestamp("2026-06-21 10:00", tz="UTC")  # Sunday
    assert in_forex_session(sat, (8, 22)) is False
    assert in_forex_session(sun, (8, 22)) is False
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `./venv/bin/python -m pytest tests/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sessions'`.

- [ ] **Step 4: Create `sessions.py`**

```python
"""Trading-session gating for forex/commodity symbols (UTC)."""
import pandas as pd


def in_forex_session(now: pd.Timestamp, window) -> bool:
    """True if `now` (tz-aware UTC) is a weekday within [window[0], window[1]) hours."""
    if now.weekday() >= 5:          # 5 = Sat, 6 = Sun
        return False
    return window[0] <= now.hour < window[1]
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `./venv/bin/python -m pytest tests/test_sessions.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add sessions.py app_config.py tests/test_sessions.py
git commit -m "feat: forex session gate + ENABLED_SYMBOLS/FOREX_SESSION_UTC config"
```

---

### Task 6: `set_api_key.py` helper + `keyring` dependency

**Files:** Create `set_api_key.py`; Modify `requirements.txt`

- [ ] **Step 1: Add `keyring` to `requirements.txt`**

Append:

```
keyring>=24.0
```

Install: `./venv/bin/pip install "keyring>=24.0"`

- [ ] **Step 2: Create `set_api_key.py`**

```python
"""One-time helper: store the Twelve Data API key in the macOS login Keychain.

Run:  ./venv/bin/python set_api_key.py
"""
import getpass
import keyring

SERVICE, ACCOUNT = "trade-assistant", "twelvedata"


def main():
    key = getpass.getpass("Twelve Data API key (input hidden): ").strip()
    if not key:
        print("No key entered; nothing stored.")
        return
    keyring.set_password(SERVICE, ACCOUNT, key)
    print(f"Stored under Keychain service '{SERVICE}', account '{ACCOUNT}'.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify it imports (no key prompt in CI)**

Run: `./venv/bin/python -c "import set_api_key; print('import OK')"`
Expected: `import OK`.

- [ ] **Step 4: Commit**

```bash
git add set_api_key.py requirements.txt
git commit -m "feat: set_api_key helper (store Twelve Data key in Keychain) + keyring dep"
```

---

### Task 7: `app.py` — multi-symbol loop (manual verify)

This is the integration rewrite. No unit test; verify by `import app` + reading. **READ the current `app.py` fully first.**

**Files:** Modify `app.py`

- [ ] **Step 1: Replace the imports block + module helpers**

At the top of `app.py`, the imports become (replace the existing `from fetch_data import ...` and add the new ones):

```python
import math
import os
import threading
import webbrowser
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, HTTPServer

import pandas as pd
import rumps
from zoneinfo import ZoneInfo

import app_config as cfg
import engine
import state
from aoi import aoi_key
from bias import bias_map
from datasource import fetch_recent_for
from instruments import get_instrument
from sessions import in_forex_session
from tracker import Tracker
from watcher import scan

_GRADE_RANK = {"weak": 1, "valid": 2, "A+": 3}


def _grade_ok(label, minimum):
    return _GRADE_RANK.get(label, 0) >= _GRADE_RANK.get(minimum, 99)


CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart")
CHART_PORT = 8753


def _state_file(symbol):
    return os.path.join(CHART_DIR, f"state-{symbol}.json")


def _serve_chart_dir():
    handler = partial(SimpleHTTPRequestHandler, directory=CHART_DIR)
    HTTPServer(("127.0.0.1", CHART_PORT), handler).serve_forever()


def _clean_price(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if not math.isnan(f) else 0.0


def _df_to_candles(df):
    return [
        {"time": int(t.timestamp()), "open": _clean_price(o), "high": _clean_price(h),
         "low": _clean_price(l), "close": _clean_price(c)}
        for t, o, h, l, c in zip(df["open_time"], df["open"], df["high"], df["low"], df["close"])
    ]


@dataclass
class SymStat:
    """Per-symbol runtime state held across ticks."""
    symbol: str
    inst: object
    levels: list = field(default_factory=list)
    zones: list = field(default_factory=list)
    bias: object = None
    bias_tf: dict = field(default_factory=dict)
    aois: list = field(default_factory=list)
    fired: set = field(default_factory=set)
    machine_fired: set = field(default_factory=set)
    tracker: Tracker = field(default_factory=Tracker)
    last_alert: dict = field(default_factory=dict)
    last_price: float = 0.0
```

- [ ] **Step 2: Replace `WatcherApp.__init__`**

```python
class WatcherApp(rumps.App):
    def __init__(self):
        super().__init__("₿ …", quit_button="Quit")
        self.settings = cfg.load_settings()
        self.syms = {s: SymStat(s, get_instrument(s)) for s in cfg.ENABLED_SYMBOLS}
        self._morning_done_for = None

        self.notif_item = rumps.MenuItem("Notifications", callback=self.toggle_notifications)
        self.sound_item = rumps.MenuItem("Alert sound", callback=self.toggle_sound)
        self._sync_toggle_marks()
        self.status_items = {s: rumps.MenuItem(f"{s}: …") for s in cfg.ENABLED_SYMBOLS}
        self.menu = [
            self.notif_item, self.sound_item, None,
            rumps.MenuItem("Open marked chart", callback=self.open_chart),
            rumps.MenuItem("Re-mark levels now", callback=self.remark_now),
            None,
            *self.status_items.values(),
        ]

        threading.Thread(target=_serve_chart_dir, daemon=True).start()
        self.remark_now(None)
        rumps.Timer(self.tick, cfg.SCAN_INTERVAL_MIN * 60).start()

    # --- toggles (unchanged) ---
    def _sync_toggle_marks(self):
        self.notif_item.state = 1 if self.settings["notifications_enabled"] else 0
        self.sound_item.state = 1 if self.settings["alert_sound_enabled"] else 0

    def toggle_notifications(self, _):
        self.settings["notifications_enabled"] = not self.settings["notifications_enabled"]
        cfg.save_settings(self.settings); self._sync_toggle_marks()

    def toggle_sound(self, _):
        self.settings["alert_sound_enabled"] = not self.settings["alert_sound_enabled"]
        cfg.save_settings(self.settings); self._sync_toggle_marks()

    def open_chart(self, _):
        webbrowser.open(f"http://127.0.0.1:{CHART_PORT}/index.html")
```

- [ ] **Step 3: Per-symbol morning pass + `remark_now`**

```python
    def _remark_symbol(self, ss):
        try:
            now = pd.Timestamp.now(tz="UTC")
            inst = ss.inst
            daily = fetch_recent_for(inst, "1d", 500)
            weekly = fetch_recent_for(inst, "1w", 300)
            h4 = fetch_recent_for(inst, "4h", 500)
            etf = fetch_recent_for(inst, "15m", 300)
            ss.levels, ss.zones, ss.bias = engine.run_morning_pass(daily, h4, now)
            ss.aois = engine.score_pass(weekly, daily, h4, etf, now, symbol=ss.symbol)
            ss.bias_tf = bias_map(weekly, daily, h4)
            ss.tracker.reset(); ss.machine_fired = set(); ss.fired = set()
            self._write_symbol_state(ss)
        except Exception as e:
            print(f"[watcher] {ss.symbol} remark failed, keeping previous: {e}")

    def remark_now(self, _):
        # The daily mark is cheap (~few credits/symbol) and forex is open 24/5, so mark it
        # whenever the market is open (weekday) — NOT gated by the intraday session window
        # (the morning pass fires ~06:00 UTC, before the 08:00 scan window opens). Only the
        # 5-min scan in _scan_symbol uses the hour window.
        now = pd.Timestamp.now(tz="UTC")
        for ss in self.syms.values():
            if ss.inst.source == "twelvedata" and now.weekday() >= 5:
                continue   # forex market closed on weekends
            self._remark_symbol(ss)
        self._update_status()
```

- [ ] **Step 4: The tick loop + per-symbol scan**

```python
    def tick(self, _):
        self._maybe_morning_pass()
        now = pd.Timestamp.now(tz="UTC")
        for ss in self.syms.values():
            self._scan_symbol(ss, now)
        if "BTCUSDT" in self.syms:
            self.title = f"₿ {self.syms['BTCUSDT'].last_price:,.0f}"
        self._update_status()

    def _scan_symbol(self, ss, now):
        try:
            if ss.inst.source == "twelvedata" and not in_forex_session(now, cfg.FOREX_SESSION_UTC):
                return
            if not ss.levels or ss.bias is None:
                return
            inst = ss.inst
            m15 = fetch_recent_for(inst, "15m", 300)
            closed = m15.iloc[:-1]
            if len(closed) == 0:
                return
            last = closed.iloc[-1]
            bar = {"high": float(last["high"]), "low": float(last["low"]), "close": float(last["close"])}
            for t in scan(bar, ss.levels, ss.bias, ss.fired,
                          require_alignment=cfg.REQUIRE_HTF_ALIGNMENT,
                          counter_trend_mode=cfg.COUNTER_TREND_MODE):
                self._emit_sweep(ss, t)
            price = _clean_price(last["close"]); ss.last_price = price
            m5 = fetch_recent_for(inst, "5m", 300).iloc[:-1]
            events = ss.tracker.advance_all(ss.aois, closed, m5, inst,
                                            cfg.STALE_SWEEP_BARS, cfg.STALE_SHIFT_BARS)
            for aoi, st, prior in events:
                ss.machine_fired.discard((aoi_key(aoi), prior))
                self._emit_machine(ss, aoi, st)
            for aoi in ss.aois:
                ms = ss.tracker.states.get(aoi_key(aoi))
                if ms is not None:
                    aoi.state, aoi.plan = ms.state, ms.plan
            self._write_symbol_state(ss, price=price, candles=_df_to_candles(closed.tail(200)))
        except Exception as e:
            print(f"[watcher] {ss.symbol} tick failed: {e}")

    def _maybe_morning_pass(self):
        local = pd.Timestamp.now(tz=ZoneInfo(cfg.MORNING_TZ))
        hh, mm = (int(x) for x in cfg.MORNING_TIME.split(":"))
        key = local.date().isoformat()
        if local.hour == hh and mm <= local.minute < mm + cfg.SCAN_INTERVAL_MIN \
                and self._morning_done_for != key:
            self.remark_now(None)
            self._morning_done_for = key
```

- [ ] **Step 5: Emitters + state write + status (symbol-tagged)**

```python
    def _emit_sweep(self, ss, trigger):
        lvl = trigger["level"]
        side = "LONG" if trigger["direction"] == "bullish" else "SHORT"
        tag = "" if trigger["aligned"] else " (counter-trend FYI)"
        title = f"⚡ {ss.symbol} sweep+reclaim — {side}{tag}"
        ss.last_alert = {"text": f"{lvl.source} sweep", "time": pd.Timestamp.now().strftime("%H:%M")}
        if self.settings["notifications_enabled"]:
            rumps.notification(title, "", f"Swept {lvl.source.upper()} {lvl.price:,.2f}",
                               sound=self.settings["alert_sound_enabled"])

    def _emit_machine(self, ss, aoi, st):
        if st.state not in cfg.ALERT_STAGES or not _grade_ok(aoi.label, cfg.MIN_ALERT_GRADE):
            return
        k = (aoi_key(aoi), st.state)
        if k in ss.machine_fired:
            return
        ss.machine_fired.add(k)
        side = "short" if aoi.side == "supply" else "long"
        title = f"⚡ {ss.symbol} {st.state} — {aoi.label} {side} @ {aoi.source} {aoi.proximal:,.2f}"
        if st.state == "ARMED" and st.plan:
            p = st.plan
            tgt = f"{p['target']:,.2f}" if p["target"] is not None else "—"
            body = f"entry {p['entry']:,.2f} · stop {p['stop']:,.2f} · target {tgt} · {p['rr']:.1f}R"
        else:
            body = "entry forming"
        ss.last_alert = {"text": f"{aoi.source} {st.state}", "time": pd.Timestamp.now().strftime("%H:%M")}
        if self.settings["notifications_enabled"]:
            rumps.notification(title, "", body, sound=self.settings["alert_sound_enabled"])

    def _write_symbol_state(self, ss, price=None, candles=None):
        if ss.bias is None:
            return
        payload = state.build_state(
            price=_clean_price(price) if price is not None else ss.last_price,
            levels=ss.levels, zones=ss.zones, bias=ss.bias,
            fired=list(ss.fired), last_alert=ss.last_alert,
            updated_at=pd.Timestamp.now(tz="UTC").isoformat(),
            aois=ss.aois, bias_tf=ss.bias_tf)
        if candles is not None:
            payload["candles"] = candles
        state.save_state(payload, _state_file(ss.symbol))

    def _update_status(self):
        for s, ss in self.syms.items():
            price = f"{ss.last_price:,.2f}" if ss.last_price else "…"
            d = ss.bias_tf.get("D", "—")
            la = ss.last_alert.get("text", "")
            self.status_items[s].title = f"{s}: {price}  D:{d}" + (f"  · {la}" if la else "")
```

(Delete the old single-symbol methods that these replace: the old `remark_now`, `tick`, `_update_status`, `_emit`, `_emit_machine`, `_write_state`, and the `_maybe_morning_pass` if duplicated. Keep `__main__`.)

- [ ] **Step 6: Verify (no GUI launch)**

Run: `./venv/bin/python -c "import app; print('import OK')"`
Expected: `import OK`.
Run: `./venv/bin/python -m pytest -q`
Expected: all pass (engine/scorer/machine/datasource/sessions tests green; app has no unit tests).

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: multi-symbol app loop (per-symbol state, session gate, symbol-tagged alerts)"
```

---

### Task 8: Chart — symbol switcher (manual)

**Files:** Modify `chart/index.html`, `chart/chart.js`

- [ ] **Step 1: Add switcher buttons to `chart/index.html`**

Inside the `#panel` div, ABOVE the `<h3>Bias (gate)</h3>` line, add:

```html
      <div id="symbuttons" style="margin-bottom:10px">
        <button onclick="setSymbol('BTCUSDT')">BTC</button>
        <button onclick="setSymbol('XAUUSD')">XAU</button>
        <button onclick="setSymbol('EURUSD')">EUR</button>
      </div>
```

- [ ] **Step 2: Make `chart/chart.js` symbol-aware**

Near the top of `chart.js` (before `refresh`), add:

```javascript
let SYMBOL = 'BTCUSDT';
function setSymbol(s) { SYMBOL = s; refresh(); }
```

Then change the fetch line in `refresh()` from `fetch('state.json?t=' + Date.now())` to:

```javascript
  try { s = await (await fetch(`state-${SYMBOL}.json?t=` + Date.now())).json(); }
```

- [ ] **Step 3: Verify** `./venv/bin/python -m pytest -q` still green (JS untested; just confirm nothing else broke). Commit:

```bash
git add chart/index.html chart/chart.js
git commit -m "feat: chart symbol switcher (BTC/XAU/EUR) reading per-symbol state files"
```

---

### Task 9: gitignore per-symbol state + README

**Files:** Modify `.gitignore`, `README.md`

- [ ] **Step 1: Ignore the per-symbol state files**

In `.gitignore`, replace the `chart/state.json` / `chart/state.json.tmp` lines (or add alongside) with a glob:

```
chart/state*.json
chart/state*.json.tmp
```

- [ ] **Step 2: Append to `README.md`**

```markdown
## Multi-instrument (Phase 3)
Monitors **BTCUSD, XAUUSD, EURUSD** in one app. BTC uses Binance; gold/forex use Twelve Data.

- **API key:** run `./venv/bin/python set_api_key.py` once to store your Twelve Data key in
  the macOS Keychain (service `trade-assistant`, account `twelvedata`). Never stored in the repo.
- **Forex session gate:** XAU/EUR are scanned only 08:00–22:00 UTC on weekdays
  (`FOREX_SESSION_UTC`), keeping Twelve Data usage under the free 800-credit/day cap. BTC scans
  24/7 on Binance.
- **Chart:** the BTC / XAU / EUR buttons switch which symbol's marked chart you view.
- Each symbol has its own state file (`chart/state-<symbol>.json`); alerts are symbol-tagged.

`ENABLED_SYMBOLS` and `FOREX_SESSION_UTC` live in `app_config.py`; per-symbol source/symbol in
`instruments.py`.
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore README.md
git commit -m "docs: document multi-instrument setup + gitignore per-symbol state"
```

---

## Self-Review notes

- **Spec coverage:** data-source abstraction + BinanceSource + dispatch (Tasks 2–3); TwelveDataSource normalize/interval/symbol/close_time + Keychain→env→error key resolution (Task 4); instruments source/provider_symbol (Task 1); session gate + config (Task 5); secure key storage helper + keyring dep (Task 6); multi-symbol app loop, per-symbol state files, session-gated forex, symbol-tagged alerts (Task 7); chart switcher (Task 8); gitignore + README (Task 9). Engine/scorer/machine untouched. Out-of-scope items (backtest, websocket, >3 symbols) absent.
- **Type consistency:** `fetch_recent_for(inst, our_interval, limit)`, `BinanceSource.fetch_recent(provider_symbol, our_interval, limit)`, `TwelveDataSource.fetch_recent(...)` + `_api_key()` + `_keyring_get()` module fn, `in_forex_session(now, window)`, `SymStat(symbol, inst, …)`, per-symbol `_state_file(symbol)`, `engine.score_pass(..., symbol=ss.symbol)`. All consistent across tasks. The app reuses unchanged `engine`/`scan`/`Tracker`/`state.build_state` signatures.
- **No placeholders:** every code step is complete and runnable. App-shell tasks (7, 8) are manual-verify (import + live), consistent with prior phases.
```
