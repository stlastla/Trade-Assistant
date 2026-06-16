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
