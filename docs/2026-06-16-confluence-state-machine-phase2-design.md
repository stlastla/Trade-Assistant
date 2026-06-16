# Confluence Trigger State Machine — Phase 2 Design Spec

_Date: 2026-06-16 · Status: approved for planning_

## Purpose

Add the **trigger state machine** + **entry alerts** on top of the Phase 1 confluence
scorer. Phase 1 says *how good* each AOI is (`A+`/`valid`/`weak`); Phase 2 says *whether it
has become an entry*. Per AOI, the machine enforces that an entry can only fire after
**tag → sweep → shift** happen **in that order**, so "price is at a level" never reads as a
trade. This is the second and final phase of `~/Downloads/confluence-layer-spec.md` (§4/§5).

Phase 1 spec: `docs/2026-06-16-confluence-scoring-phase1-design.md`.

## Confirmed decisions (from brainstorming)

- **Timeframes:** the HTF AOI is **tagged** by price; the **sweep** is timed on **M15**; the
  **shift** is timed on **M5** (the finer execution read). Tag = a candle trades into the band.
- **Grades unchanged** (`A+`/`valid`/`weak`/`no-trade`). All **gate-pass** AOIs (incl. `weak`)
  run the machine and show their state on the chart. Notifications are gated by
  `MIN_ALERT_GRADE` (default `valid`) — so `weak` runs **silently** (chart only).
- **Notifying stages:** `SWEPT`, `SHIFTED`, `ARMED` all fire a notification (configurable via
  `ALERT_STAGES`); `TAGGED`/`WATCHING` are chart-only. Alerts are **grade-stamped**.
- **Tag rule:** price entering the band `[proximal, distal]` (not requiring the midpoint).
- **Timeouts:** `TAGGED` with no sweep within **N = 12 M15 bars (~3h)** → `STALE`; `SWEPT`
  with no shift within **M = 12 M5 bars (~1h)** → `STALE`. Both config.
- **Long and short** both (the spec's short case mirrored for longs).
- The existing Phase-0 sweep-watcher alert (`watcher.scan`) is **untouched**.

## Architecture (new pure-ish modules, additive)

```
triggers.py    detectors: is_tagged, etf_sweep (M15), etf_shift (M5), first_opposing_candle
machine.py     MachineState + advance(prior, aoi, ctx) -> (new_state, events). States:
               WATCHING -> TAGGED -> SWEPT -> SHIFTED -> ARMED  (+ INVALIDATED, STALE)
trade_plan.py  build_plan(aoi, ctx) -> {entry, stop, target, rr}  (HTF-wide stop)
tracker.py     holds {aoi_key -> MachineState} across ticks; matches fresh scored AOIs by key,
               advances each, returns the list of (aoi, state, events) to act on
```

- **Persistence.** Machine state lives in memory in the app, keyed by a stable AOI id
  (`aoi_key(aoi)` = `f"{source}:{round(proximal,2)}"`), reset at the morning re-mark. Phase 1
  rebuilds scored AOIs fresh every tick; the tracker re-attaches the matching machine state by
  key. New AOIs start `WATCHING`; AOIs that disappear (e.g. a now-mitigated FVG) drop.
- **Purity.** `triggers`, `machine`, and `trade_plan` are pure functions over the M15/M5
  frames + the AOI + the scored-AOI set + bias; `tracker` holds the cross-tick dict and is the
  one stateful unit. The app shell wires fetch → tracker → notifications → `state.json`.

## State machine (short case; long is the exact mirror — swap high/low, supply/demand, up/down)

Only **gate-pass** AOIs run the machine. **Strict ordering**: a shift that prints before a
sweep does NOT advance; a sweep with no following shift stays `SWEPT` until it shifts, times
out, or invalidates. Each entry stores the event time so later detectors only look at bars
*after* the prior event.

| State | Enters when | Notifies? |
|---|---|---|
| `WATCHING` | AOI passes the bias gate and has a score | no (chart only) |
| `TAGGED` | an **M15** candle trades into the band `[proximal, distal]` | no (chart only) |
| `SWEPT` | after tag, **M15** runs a local swing high (supply) / low (demand) at the level | **yes** (if grade ≥ MIN) |
| `SHIFTED` | after the sweep, **M5** prints an MSS/CHoCH in the trade direction | **yes** (if grade ≥ MIN) |
| `ARMED` | the first-opposing-candle entry condition is set → trade plan built | **yes** (if grade ≥ MIN) |
| `INVALIDATED` | price breaks the HTF AOI **distal** edge before `ARMED`, or bias flips against the AOI | logged, setup closed |
| `STALE` | timeout (N bars in `TAGGED` w/o sweep, or M bars in `SWEPT` w/o shift) | → `WATCHING` if still valid, else closed |

Detectors (`triggers.py`), short case:
- **`is_tagged(aoi, m15)`** — any M15 high ≥ band low (price entered the band).
- **`etf_sweep(aoi, m15, after)`** — a `liquidity.detect_sweeps` bearish event (swept a swing
  high then closed back below) at/near the AOI, on M15 bars after the tag time.
- **`etf_shift(aoi, m5, after)`** — a `structure.detect_structure_breaks` `down` break on M5
  after the sweep time (MSS/CHoCH in the trade direction). Pluggable so a RelicusRoad Signal
  Line reader can replace it later.
- **`first_opposing_candle(aoi, m5, after)`** — the first bullish M5 candle of the rejected
  rally after the shift; entry triggers below its low.

## Trade plan (`trade_plan.py`, built on `ARMED`)
- **Entry:** below the first opposing candle (above it, for longs).
- **Stop:** the **HTF AOI distal edge + `STOP_BUFFER`** — not the tight M5 swing (spec §5.5: a
  stop tucked behind an M5 swing inside a Daily zone gets run by noise).
- **Target:** the next opposing AOI in the profit direction (reuse Phase 1's
  `_next_opposing_target`).
- **R:R:** `|entry - target| / |entry - stop|`, computed off the HTF stop. Included in the alert.

## Alerts + chart
- On entering a notifying stage (`ALERT_STAGES`, default `SWEPT/SHIFTED/ARMED`), if the AOI's
  grade ≥ `MIN_ALERT_GRADE` (default `valid`), fire a macOS notification through the existing
  notification path (respects `notifications_enabled` / `alert_sound_enabled`). Title is
  **grade-stamped**: e.g. `⚡ SHIFTED — A+ short @ PDH 67,292 (entry forming)`; `ARMED` adds
  `entry / stop / target / R:R`. De-dupe: each (AOI, stage) fires at most once per session.
- Chart: each AOI line's title shows its state (e.g. `A+ supply · SWEPT`); `ARMED` drawn
  boldest. `weak` AOIs still show state, just never notify.
- `state.json` AOIs gain `state` and (when `ARMED`) `plan` fields.

## Config (`app_config.py`)
- `ENTRY_TF = "5m"`, `SWEEP_TF = "15m"`.
- `MIN_ALERT_GRADE = "valid"` (`"A+"` | `"valid"` | `"weak"`).
- `ALERT_STAGES = ("SWEPT", "SHIFTED", "ARMED")`.
- `STALE_SWEEP_BARS = 12` (M15), `STALE_SHIFT_BARS = 12` (M5).
- `STATE_STOP_BUFFER` (beyond the HTF distal edge) — may reuse the per-instrument `stop_buffer`.

## Integration
Each 5-min tick: fetch M15 + M5, run the Phase 1 `score_pass` to get fresh scored AOIs, hand
them to the `tracker` (which carries machine state across ticks and advances each on the new
bars), then fire notifications for the returned stage events (grade-gated) and write each
AOI's `state`/`plan` into `state.json`. The morning re-mark resets the tracker. The existing
`watcher.scan` sweep alert continues to run unchanged in the same tick.

## Testing
The source spec's **§10 group H** as fixtures (synthetic M15/M5 + an AOI), asserting **state**
not scores:
- **H1 — premature tag:** tag, no sweep follows → stays `TAGGED`, never `ARMED`, no entry alert.
- **H2 — out-of-order shift:** M5 shifts before the M15 sweep → not armed (sweep-then-shift
  required).
- **H3 — stale reset:** `SWEPT` past the timeout with no shift → `STALE` → `WATCHING` if valid.
- **H4 — invalidation:** price breaks the HTF distal edge before `ARMED` → `INVALIDATED`, no entry.
- **H5 — clean armed sequence:** tag → M15 sweep → M5 shift → first opposing candle → `ARMED`,
  emits a plan with the **HTF stop** and **HTF target**, R:R off the HTF stop distance.
Plus per-detector unit tests (`is_tagged`, `etf_sweep`, `etf_shift`, `first_opposing_candle`),
a `trade_plan` test, and a `tracker` test (state carries across two advances; new/disappeared
AOIs handled; reset clears state). The app shell is verified by `import app` + live run.

## Out of scope
- RelicusRoad Signal Line feed (the shift stays MSS/CHoCH; the detector is pluggable).
- Auto-execution / broker orders — the app alerts; the user trades.
- Backtesting the machine (the Phase 1 research already covers the edge; this is live tooling).
- Multi-symbol live monitoring (BTC only; scoring engine remains multi-instrument).

## Open questions / first-iteration tunables
- Exact "at/near the AOI" tolerance for the M15 sweep detector (start: sweep's swept level
  within the AOI band or within `stop_buffer` of it).
- Whether `SHIFTED` should require a *momentum* threshold on the M5 break or accept any
  MSS/CHoCH (start: any break in the trade direction; tighten if noisy).
- Timeout values N/M (start 12/12; tune live).
