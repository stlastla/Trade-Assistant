# Multi-Instrument Live (XAUUSD + EURUSD) — Phase 3 Design Spec

_Date: 2026-06-16 · Status: approved for planning_

## Purpose

Make the watcher monitor **XAUUSD and EURUSD live**, alongside BTCUSD. The scoring engine,
per-instrument config (price-vs-pip units), and the trigger state machine are already
multi-instrument and tested; the missing piece is a **data feed for gold and forex** (Binance
is crypto-only) and a **multi-symbol app loop**. This adds a Twelve Data adapter behind a
small data-source abstraction, runs all enabled symbols in one process, and gives the chart a
symbol switcher.

Builds on: Phase 1 (`docs/2026-06-16-confluence-scoring-phase1-design.md`) and Phase 2
(`docs/2026-06-16-confluence-state-machine-phase2-design.md`).

## Confirmed decisions (from brainstorming)

- **Data source:** Twelve Data (free tier, 800 credits/day, 8/min; 1 credit per candle
  request). API key via env var `TWELVEDATA_API_KEY`. BTC stays on Binance (no Twelve Data
  cost). Intervals map `1w/1d/4h/15m/5m → 1week/1day/4h/15min/5min`; symbols `XAUUSD→XAU/USD`,
  `EURUSD→EUR/USD`.
- **Forex cadence:** 5-min, **session-gated** — scan XAU/EUR only inside `FOREX_SESSION_UTC`
  (default 07:00–21:00 UTC) and **skip weekends**; no Twelve Data calls outside the window.
  BTC scans 5-min 24/7. This keeps daily credit use well under 800.
- **Architecture:** one process, looping enabled symbols; per-symbol state files; chart gets
  in-page **BTC / XAU / EUR buttons**.
- **Engine unchanged:** scorer, state machine, triggers, tracker, trade_plan are untouched —
  they already accept a `symbol` and handle pip units.

## Architecture

### Data-source abstraction (`datasource.py`, new)
A tiny interface so the engine doesn't care where candles come from:

```
class DataSource:
    INTERVAL_MAP: dict           # our interval -> provider interval string
    def fetch_recent(provider_symbol, our_interval, limit) -> DataFrame
    def download(provider_symbol, our_interval) -> DataFrame   # full/long history

SOURCES = {"binance": BinanceSource(), "twelvedata": TwelveDataSource()}

def fetch_recent_for(inst, our_interval, limit) -> DataFrame   # dispatch by inst.source
def download_for(inst, our_interval) -> DataFrame
```

- **`BinanceSource`** — wraps the existing `fetch_data` logic (klines, `klines_to_df`),
  refactored behind the interface. Identity interval map (`1w/1d/4h/15m/5m`).
- **`TwelveDataSource`** — `GET https://api.twelvedata.com/time_series?symbol=&interval=&
  outputsize=&order=ASC&apikey=`. Maps intervals, reads `TWELVEDATA_API_KEY`, and normalizes
  the `{"values":[{datetime,open,high,low,close,volume}], "status":...}` JSON into the **same
  OHLCV DataFrame shape** the engine expects: tz-aware UTC `open_time`, float OHLC(V), and a
  **synthesized `close_time`** = `open_time + interval_duration` (so `prior_day_levels`'
  `close_time <= now` logic works). On an API error/`status != "ok"` it raises (callers are
  already wrapped in try/except and degrade).

Every output frame matches the existing column contract: `open_time, open, high, low, close,
volume, close_time`, ascending, UTC. So `levels.py`/`triggers.py`/`engine.py` consume forex
frames with zero changes.

### Per-instrument config (`instruments.py`)
`Instrument` gains `source: str` (`"binance"`|`"twelvedata"`) and `provider_symbol: str`.
BTCUSDT → binance/`BTCUSDT`; XAUUSD → twelvedata/`XAU/USD`; EURUSD → twelvedata/`EUR/USD`.
(The unit/band/weight fields already exist from Phase 1.)

### Multi-symbol app (`app.py`)
One `WatcherApp`, looping `cfg.ENABLED_SYMBOLS`. Per-symbol state moves into a dict keyed by
symbol — each symbol has its own `Tracker`, `fired`, `machine_fired`, `bias_tf`, `levels`,
`zones`, `bias`, `aois`, `last_alert`. Each writes its own `chart/state-<symbol>.json`.
- **Morning pass** (per symbol): fetch that symbol's 1w/1d/4h/15m via its source, build
  levels + score + bias_map, reset its tracker.
- **5-min tick** (per symbol): if the symbol is forex and `not in_forex_session(now)`, skip
  it (no API calls). Else fetch its M15 + M5, run the existing sweep `scan` and the state
  machine, fire **symbol-tagged** notifications, write its state file.
- **Menu-bar:** one status line per enabled symbol (price + bias + last state). Title shows
  the primary symbol (BTC) price.
- Notifications, toggles (`notifications_enabled`/`alert_sound_enabled`), and the existing
  sweep-alert path are unchanged in behavior, just per-symbol and symbol-stamped.

### Session gate (`sessions.py` or a helper in app)
`in_forex_session(now_utc, window=cfg.FOREX_SESSION_UTC) -> bool`: False on Sat/Sun, else
`window[0] <= now.hour < window[1]`. Pure, unit-tested.

### Chart (`chart/`)
`index.html` gains a row of buttons **BTC / XAU / EUR**; `chart.js` keeps a `symbol` variable
(default `BTCUSDT`) and fetches `state-${symbol}.json`. All rendering (candles, levels, AOI
labels, machine state, bias panel) is instrument-agnostic and unchanged. The local server
already serves the whole `chart/` dir, so the per-symbol files are reachable.

## Data flow
`tick → for each enabled symbol → (forex? in session?) → fetch_recent_for(inst, …) → score_pass(symbol) → tracker → symbol-tagged notifications → state-<symbol>.json → chart (selected symbol)`.

## Config (`app_config.py`)
- `ENABLED_SYMBOLS = ("BTCUSDT", "XAUUSD", "EURUSD")`.
- `FOREX_SESSION_UTC = (7, 21)`.
- Twelve Data key read from env `TWELVEDATA_API_KEY` (in `datasource.py`).
- Per-symbol `source`/`provider_symbol` live in `instruments.py`; `scan_interval` stays the
  global 5-min tick (forex just gated by session).

## Rate-budget sanity
Forex, session-gated ~14h/weekday: 2 symbols × 2 credits/tick × 12 ticks/h × 14h ≈ **672
credits/day** + morning passes (~6) — under the 800 free cap, with BTC entirely on Binance.

## Testing
- **`TwelveDataSource`**: mock the HTTP JSON → assert the normalized frame (columns, UTC
  `open_time`, float OHLC, synthesized `close_time`), the interval map, the symbol passthrough,
  and `order=ASC`. Error/`status!="ok"` raises.
- **`BinanceSource`**: thin wrapper — assert it still returns the existing-shape frame (reuse
  the current `fetch_data` monkeypatch test pattern).
- **dispatch**: `fetch_recent_for(inst, …)` routes to the right source by `inst.source`.
- **`in_forex_session`**: in-window weekday True; out-of-window False; weekend False.
- Engine/scorer/machine/tracker tests are untouched and must stay green.
- The multi-symbol `app.py` loop is verified by `import app` + a live run (no unit test for
  the GUI shell), plus a non-GUI smoke that runs one XAU/EUR scan end-to-end with a real key.

## Out of scope
- Backtesting XAU/EUR (engine edge already covered by the BTC research; this is live tooling).
- WebSocket/streaming (REST polling is enough at this cadence).
- More than these three symbols (config-extensible later).
- Per-symbol bespoke session models beyond the single forex window + weekend skip.

## Open questions / first-iteration tunables
- Exact `FOREX_SESSION_UTC` window (start 07–21; widen/narrow after watching credit use).
- Twelve Data `outputsize` for the morning history fetch (start ~500 for 4h/15m, ~300 for 1d).
- Whether the menu-bar title should rotate symbols or stay on BTC (start: BTC).
