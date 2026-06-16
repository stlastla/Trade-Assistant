# Confluence Scoring — Phase 1 Design Spec

_Date: 2026-06-16 · Status: approved for planning_

## Purpose

Add a **confluence layer** to the BTC Watcher that scores how *tradeable* each Area of
Interest (AOI) is and labels it `A+` / `valid` / `weak` / `no-trade`, so that high-quality
trend-pullback setups stand out and "price is at a level" stops reading as "this is a
trade." This is **Phase 1 of two**: scoring only. Phase 2 (separate spec) adds the
`tag → sweep → shift → ARMED` trigger state machine and entry alerts.

Source spec: `~/Downloads/confluence-layer-spec.md` (the user's feature spec). This document
is the Phase-1-scoped, app-grounded adaptation of it.

## Scope

**In scope (Phase 1):**
- Per-timeframe bias with a real FLAT state (Weekly + Daily + H4).
- AOIs modeled as **bands** `[proximal, distal]` with timeframe + side (supply/demand).
- The **bias gate** (hard pass/no-trade) per §2 of the source spec.
- The **6 confluence factors**, each independent, testable, and degrading to neutral.
- The **scoring core** → numeric score + label + per-factor breakdown, written to
  `state.json` and surfaced on the chart (color by label; breakdown visible).
- **Multi-instrument** scoring engine + config + tests (BTC/XAU/EUR, price-vs-pip units).

**Explicitly out of scope (Phase 1):**
- The trigger state machine (`WATCHING…ARMED`, `INVALIDATED`, `STALE`) — Phase 2.
- New entry alerts. The existing `watcher.scan` sweep+reclaim notification is unchanged.
- Live XAU/EUR data feeds. The app fetches only BTCUSDT from Binance; the scoring engine
  and config are multi-instrument and tested for all three, but live monitoring runs BTC
  only. Adding live XAU/EUR is a separate data-adapter task.
- Order-block / breaker detection (Factor 3 uses unmitigated FVGs only for now).
- A RelicusRoad Signal Line feed (Factor 4 uses MSS/CHoCH now; Road is pluggable later).

## Design rationale

The two things that separate a real setup from a chase are the **bias gate** and the
**liquidity-sweep factor**; the source spec is emphatic that neither may be loosened. The
gate is a hard pass/fail (never a weight), and the sweep is weighted so that no combination
of other factors can lift a no-sweep AOI to `A+`. This matches this repo's own research:
HTF alignment is the edge, the M15 pattern alone is a coin-flip.

## Confirmed decisions (from brainstorming)

- **Phasing:** scoring first (this spec); state machine + entry alerts in Phase 2.
- **Instruments:** full multi-instrument config + tests now; live feed BTC-only.
- **Bias timeframes:** Weekly + Daily + H4.
- **Shift signal:** MSS/CHoCH via `structure.detect_structure_breaks` now, behind a
  pluggable interface; returns neutral when it has no read.
- **Swing detection:** the existing `liquidity.swing_points` fractal detector (left/right=2).

## Architecture (new pure modules, additive — nothing in the existing engine is rewritten)

```
instruments.py  per-instrument config (band widths, min R:R, units, weights, thresholds)
bias.py         compute_bias(df) -> UP|DOWN|FLAT ; per-TF map {Weekly,Daily,H4}
aoi.py          AOI dataclass with band [proximal,distal] ; builders from levels/PDH-PDL/FVGs
gate.py         bias_gate(aoi, bias_map) -> pass | no-trade  (own-TF-and-higher only)
factors.py      6 independent factor fns, each -> normalized contribution, neutral on no data
scoring.py      score_aoi(aoi, context, instrument) -> {score, label, breakdown}
```

Data flow (extends the morning pass; does not replace it):
`fetch (incl. 1W) → bias map + AOIs(bands) → gate → factors → score/label → state.json → chart`.

### `instruments.py`
A dict keyed by instrument symbol, each entry: `units` (`"price"` | `"pips"`),
`pip_size` (for pip instruments), `aoi_band` (width of a swing-level band),
`cluster_band` (tolerance for Factor 2), `min_rr` (Factor 5 threshold),
`factor_weights` (per-factor), `label_thresholds` (score cutoffs for A+/valid/weak).
BTC and XAU expressed in price; EUR in pips. A helper converts a raw price distance to the
instrument's unit so clustering/R:R never mix dollars and pips. BTC is the only instrument
the live loop fetches; XAU/EUR exist for config + tests.

### `bias.py`
`compute_bias(df) -> "UP"|"DOWN"|"FLAT"`: combine EMA-50 position/slope with the last
`detect_structure_breaks` direction. **FLAT** when the EMA slope is within a flat threshold
(config) or structure and EMA disagree. `bias_map(weekly, daily, h4) -> {"W":…, "D":…, "H4":…}`.
This replaces the old flat `Bias(daily_dir,h4_dir,mom14_dir)` for the scoring path; the
existing watcher keeps using its current bias until Phase 2 unifies them.

### `aoi.py`
```
@dataclass
class AOI:
    timeframe: str   # 'D' | 'H4' (the TF that produced it)
    side: str        # 'supply' (sell zone, above) | 'demand' (buy zone, below)
    proximal: float  # near edge price enters first
    distal: float    # far edge / stop side
    source: str      # 'daily_swing_high' | 'pdh' | 'h4_fvg_bull' | ...
    origin: dict     # metadata (e.g. fvg edges) for factor functions
```
Builders: swing highs → supply band `[level - aoi_band, level]` with distal above; swing
lows → demand band; PDH/PDL likewise; FVGs map direction→side with their natural
`[bottom, top]` band and `mitigated` flag. Band widths come from `instruments.py`.

### `gate.py`
`bias_gate(aoi, bias_map) -> "pass" | "no-trade"`. Checks the AOI's own timeframe **and
higher only** (D AOI ⇒ D+W; H4 AOI ⇒ H4+D+W). `demand` needs UP, `supply` needs DOWN, at
those TFs. Own-TF FLAT or conflict ⇒ `no-trade`. A lower-TF move into the AOI is **never**
consulted (the §2 edge — regression-guarded by tests A2b/A2c).

### `factors.py`
Each `factor_x(aoi, context, instrument) -> float` in a normalized range (Factor 4 may be
negative as a penalty). `context` carries the OHLC frames, swing points, FVGs, the AOI set
(for clustering and R:R), and the optional shift read. Missing data ⇒ neutral (0), never
raises.
1. `factor_sweep` (highest weight): a directionally-relevant prior swing run before price
   reached the AOI (high→short, low→long). The dominant factor.
2. `factor_cluster` (medium): count of other AOIs within `cluster_band` (unit-aware).
3. `factor_structure` (medium): an **unmitigated** FVG at/near the AOI (uses
   `unfilled_fvgs`); mitigated ⇒ no credit.
4. `factor_shift` (high, pluggable): MSS/CHoCH in trade direction ⇒ +, against ⇒ −, none
   ⇒ neutral.
5. `factor_rr` (medium): distance to the next opposing AOI vs the **HTF-wide** stop
   (distal edge + config buffer); reward ≥ `min_rr`, penalize boxed-in.
6. `factor_session` (low, optional): mild London/NY boost if session known, else neutral.

### `scoring.py`
`score_aoi(aoi, context, instrument)`:
1. `bias_gate` first → if `no-trade`, return label `no-trade` (muted), no factor scoring.
2. Else sum `weight_x * factor_x` over the configured weights → numeric `score`.
3. Map `score` → label via `label_thresholds`, with a **hard rule: `A+` requires
   `factor_sweep` > 0** (no sweep ⇒ capped below `A+` regardless of other factors).
4. Return `{score, label, breakdown: {factor: contribution}}`.

## Integration

A new scoring pass runs after the morning level-marking (and on each scan refresh):
build the per-TF bias map, build AOIs with bands, score each, and attach
`{score, label, breakdown, gate}` to the AOI records in `state.json`. The chart colors AOIs
by label and shows the breakdown on hover/click. **No entry alerts are emitted in Phase 1.**
`INTERVALS` gains `"1w"`; a Weekly fetch feeds the bias map.

## Config (no hardcoding — `instruments.py` + `app_config.py`)
- Per-instrument: `units`/`pip_size`, `aoi_band`, `cluster_band`, `min_rr`, `factor_weights`,
  `label_thresholds`, stop buffer behind the distal edge.
- Bias: EMA period (50) and the FLAT slope threshold.

## Testing

Synthetic OHLC + AOI fixtures, run without any live feed, asserting **labels and ordering**
(not exact scores). From the source spec §10:
- **A — gate:** A1 (FLAT kills a perfect setup → no-trade), A2a (counter-HTF → no-trade),
  **A2b (lower-TF rally into HTF supply, HTF down → passes — permanent regression guard)**,
  A2c (aligned continuation → passes), A3 (control → A+).
- **B — sweep:** B1 (sweep+structure → A+), **B2 (same minus the sweep → weak; B1≫B2)**,
  B3 (wrong-side sweep → not rewarded).
- **C — clustering:** C1 (XAU tight cluster → bonus), C2 (XAU false cluster → none),
  **C3 (EUR cluster in pips → unit-bug guard)**.
- **D — structure:** D1 (FVG → +), D2 (bare level → lower, never A+ on cluster+RR alone),
  D3 (mitigated FVG → no credit).
- **E — shift degradation:** E1 (no feed → neutral, no crash), E2 (with → boosted),
  E3 (against → penalized).
- **F — R:R:** F1 (room → +), F2 (boxed-in → penalized).
- **G — end-to-end ranking:** **G1 (B1 A+ > B2 weak > A1 no-trade — permanent guard).**

Each factor and the gate are unit-tested in isolation; `scoring.py` is tested on the
combined fixtures. (Group H — state machine — is Phase 2.)

## Design intent (kept strict)

The bias gate is a hard pass/fail, and `factor_sweep` is weighted (plus the `A+`-requires-
sweep rule) so structure or clustering can never compensate for a missing sweep. B2, C3, D2,
and G1 are permanent regression guards. The app is meant to *be* the patience — in Phase 1
that means refusing to label a bare, unswept level as a high-quality setup.

## Open questions / first-iteration tunables
- Exact FLAT slope threshold per TF (start from a small ATR-relative slope; tune on fixtures).
- Swing-level `aoi_band` width per instrument (start from a small ATR/price fraction).
- Whether Factor 6 (session) earns its keep, or should stay neutral until Phase 2.
