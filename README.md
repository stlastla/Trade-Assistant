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
