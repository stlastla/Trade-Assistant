# BTC Watcher — Design Spec

_Date: 2026-06-15 · Status: approved for planning_

## Purpose

A macOS menu-bar app that watches BTCUSD and taps the user on the shoulder when a
high-quality intraday setup forms. It does a top-down level-marking pass each morning,
then scans every 5 minutes for a sweep + reclaim of those levels, alerting only when the
setup aligns with the higher-timeframe bias. The user trades H4 bias → M15 setup → M5
execution; the app automates the watching, not the trading.

This is a desktop companion built on the existing BTC research engine in this repo. It
reuses the pure analysis modules (`fvg.py`, `liquidity.py`, `structure.py`) directly and
adds a thin app shell plus two small engine modules.

## Design rationale (grounded in this repo's research)

The repo's backtests (see `HANDOFF.md`) found that M15 patterns are near coin-flips
*standalone* — sweeps, structure breaks, road slope all ~50% alone. The real, repeatable
edge is **higher-timeframe alignment**: H4 EMA-50 trend + multi-day (14-day) momentum.
The app therefore treats the M15 sweep as a *trigger* and the HTF bias as a *gate*:
counter-trend sweeps (the low-edge ones) are suppressed by default. The single best
descriptive signal in the research was "liquidity grab + reclaim" (~72% to move 1 ATR),
which is exactly what `liquidity.detect_sweeps()` already encodes.

Scope is deliberately lean: **sweep + reclaim only** to start. FVG-reaction,
reclaim-of-broken-level, and ORB triggers are explicitly deferred until the lean version
has been watched live and tuned.

## Architecture (Approach A — pure Python)

A single long-running menu-bar process with three internal layers, data flowing one way:

```
scheduler ──> fetch ──> engine ──> state.json ──> { notification, menu-bar text, chart page }
```

### Layer 1 — Engine (pure functions, no UI, unit-tested)
- **Existing, reused as-is:** `liquidity.swing_points`, `liquidity.detect_sweeps`,
  `fvg.find_fvgs`, `structure.detect_structure_breaks`.
- **New `levels.py`** — builds the marked level set from Daily + H4 + prior day:
  Daily swing highs/lows, H4 swing highs/lows, H4 unfilled FVGs, PDH/PDL. Also computes
  the bias snapshot (Daily direction, H4 EMA-50 trend, 14-day momentum sign).
- **New `watcher.py`** — given the marked level set and the latest closed bar(s), detects
  a sweep + reclaim against *any marked level* (a generalization of `detect_sweeps`, which
  today only checks the most-recent confirmed swing). Applies the HTF-alignment gate and
  returns a structured trigger (or none).

### Layer 2 — App shell (`app.py`, `rumps`)
Owns the macOS menu-bar icon, the internal scheduler (morning pass + 5-min loop), fires
native notifications, persists settings, and opens the chart. Thin; tested manually.

### Layer 3 — Chart (local HTML, TradingView `lightweight-charts`)
A static page opened in the browser on demand. Reads `state.json` and renders the M15
chart with marked zones, the bias panel, and the live trigger. M5 available for execution
context. No server needed beyond a local file (or a tiny localhost serve if required by
the charting lib).

## Behavior

### Morning pass — 08:00 Europe/Oslo (user's local time; tracks DST)
1. Fetch Daily, H4, M15, M5.
2. Build the marked level set via `levels.py`: Daily swing highs/lows (last N confirmed),
   H4 swing highs/lows, H4 unfilled FVGs, PDH, PDL.
3. Freeze the day's bias snapshot (refreshed each scan, but the level map is set here).
4. Write everything to `state.json` with per-level `{source, price, side}` tags.
5. Reset the per-session `fired` set.

A "Re-mark levels now" menu item runs this pass on demand.

### 5-minute watch loop
1. Refetch M15 + M5 (light `fetch_recent`, see below) and recompute the live bias.
2. Check the newest **closed** M15 bar for a sweep + reclaim of any marked level
   (pierce the level then close back inside — bullish on a low, bearish on a high).
3. **HTF-alignment gate:** a bullish sweep alerts at full strength only if Daily↑ / H4
   EMA-50↑ / 14d-momentum↑ agree (mirror for bearish). Counter-trend sweeps are **silent
   by default** (configurable to a downgraded "FYI" alert).
4. **De-dupe:** each marked level can fire at most once per session (`fired` set in state),
   so a persisting sweep does not re-alert every 5 minutes.
5. On a qualifying trigger: update `state.json`, set the menu-bar icon to the active state,
   and — if notifications are ON — fire a banner (with sound if that toggle is ON).

### Alerts
- Native macOS notification. Title = setup + direction context
  (e.g. "⚡ BTC sweep + reclaim — LONG context"); body = which level + bias flags
  (e.g. "Swept PDL 67,820, reclaimed. Daily↑ H4↑ mom↑. Tap to open chart.").
- Menu-bar icon reflects calm vs. ⚡ active.
- Tapping the notification (or the menu item) opens the marked chart.

### Menu-bar dropdown
- Live: current price + bias flags; last alert; "Watching N levels · next scan HH:MM".
- **Notifications ON/OFF** — when OFF, scanning continues and the icon still updates; no
  banners are fired.
- **Alert sound ON/OFF** — independent of the above (silent banner vs. banner + sound).
- Actions: "Open marked chart", "Re-mark levels now".
- Both toggles persist across restarts.

## Data

- Source: Binance public klines API (`config.BINANCE_BASE`), same as `fetch_data.py`.
  Free, no key, includes volume.
- Extend `config.INTERVALS` to `("1d", "4h", "15m", "5m")`.
- Add `fetch_data.fetch_recent(interval, limit)` — a lightweight "last N candles" fetch for
  the 5-min loop (the existing `download` is full-history / disk-cached and too heavy for a
  5-minute cadence). The morning pass can use the heavier path or a larger `fetch_recent`.
- `state.json` is the single source of truth shared between engine output and the UI/chart:
  marked levels, bias snapshot, fired set, last-alert, settings.

## Configuration (`app_config.py`)
- `SCAN_INTERVAL_MIN = 5`
- `MORNING_TIME = "08:00"`, `MORNING_TZ = "Europe/Oslo"`
- `DAILY_SWING_LOOKBACK_N` (how many Daily swings to mark)
- `REQUIRE_HTF_ALIGNMENT = True`
- `COUNTER_TREND_MODE = "silent"` (`"silent"` | `"fyi"`)
- `NOTIFICATIONS_ENABLED = True` (persisted toggle)
- `ALERT_SOUND_ENABLED = False` (persisted toggle)

## Testing
- Engine stays pure → unit-test `levels.py` (level extraction, bias snapshot) and the
  generalized sweep-against-level-set in `watcher.py` on fixture DataFrames, including the
  HTF-gate and de-dupe logic. Fits the existing pytest suite (71 tests passing).
- App shell (`app.py`) is thin (scheduler wiring, notification calls, menu state) and is
  verified manually.

## Explicitly out of scope (for now)
- Triggers other than sweep + reclaim (FVG reaction, reclaim-of-broken-level, ORB) —
  deferred until the lean version is tuned.
- M5 as an independent trigger (M5 is display/execution context only at first).
- Auto-trading or broker integration — the app watches and notifies; the user trades.
- Multi-symbol support.

## Open questions / first-iteration tunables
- Single-bar reclaim vs. reclaim-within-N-bars (start single-bar; revisit if it misses
  real sweeps).
- How many Daily swings (`DAILY_SWING_LOOKBACK_N`) keep the map useful without clutter.
- Whether session opens / untested-level "approach" heads-ups are worth adding in v2.
