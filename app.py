"""BTC Watcher menu-bar app. Run with: ./venv/bin/python app.py"""
import math
import os
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
from aoi import aoi_key
from bias import bias_map
from fetch_data import fetch_recent, download
from instruments import get_instrument
from tracker import Tracker
from watcher import scan

_GRADE_RANK = {"weak": 1, "valid": 2, "A+": 3}


def _grade_ok(label: str, minimum: str) -> bool:
    return _GRADE_RANK.get(label, 0) >= _GRADE_RANK.get(minimum, 99)

CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart")
STATE_FILE = os.path.join(CHART_DIR, "state.json")
CHART_PORT = 8753


def _serve_chart_dir():
    handler = partial(SimpleHTTPRequestHandler, directory=CHART_DIR)
    HTTPServer(("127.0.0.1", CHART_PORT), handler).serve_forever()


def _clean_price(value) -> float:
    """Coerce to a plain float; return 0.0 for NaN/None so state.json stays valid JSON."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if not math.isnan(f) else 0.0


def _df_to_candles(df: pd.DataFrame) -> list:
    return [
        {"time": int(t.timestamp()), "open": _clean_price(o), "high": _clean_price(h),
         "low": _clean_price(l), "close": _clean_price(c)}
        for t, o, h, l, c in zip(df["open_time"], df["open"], df["high"],
                                 df["low"], df["close"])
    ]


class WatcherApp(rumps.App):
    def __init__(self):
        super().__init__("₿ …", quit_button="Quit")
        self.settings = cfg.load_settings()
        self.levels, self.zones, self.bias = [], [], None
        self.aois = []
        self.tracker = Tracker()
        self.machine_fired = set()   # (aoi_key, stage) already notified this session
        self.bias_tf = {}   # per-TF confluence bias {W,D,H4} shown on the chart panel
        self.fired = set()
        self.last_alert = {}
        self._morning_done_for = None

        self.notif_item = rumps.MenuItem("Notifications", callback=self.toggle_notifications)
        self.sound_item = rumps.MenuItem("Alert sound", callback=self.toggle_sound)
        self._sync_toggle_marks()
        # Read-only info lines (no callback => rendered disabled/greyed by rumps)
        self.status_price = rumps.MenuItem("₿ … · bias —")
        self.status_alert = rumps.MenuItem("Last alert: —")
        self.status_watch = rumps.MenuItem("Watching 0 levels")
        self.menu = [
            self.notif_item, self.sound_item, None,
            rumps.MenuItem("Open marked chart", callback=self.open_chart),
            rumps.MenuItem("Re-mark levels now", callback=self.remark_now),
            None,
            self.status_price, self.status_alert, self.status_watch,
        ]

        threading.Thread(target=_serve_chart_dir, daemon=True).start()
        self.remark_now(None)  # initial level mark on launch
        rumps.Timer(self.tick, cfg.SCAN_INTERVAL_MIN * 60).start()

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
        try:
            now = pd.Timestamp.now(tz="UTC")
            daily = download("1d", force=True)
            weekly = fetch_recent("1w", limit=300)
            h4 = fetch_recent("4h", limit=500)
            etf = fetch_recent("15m", limit=300)
            self.levels, self.zones, self.bias = engine.run_morning_pass(daily, h4, now)
            self.aois = engine.score_pass(weekly, daily, h4, etf, now, symbol="BTCUSDT")
            self.bias_tf = bias_map(weekly, daily, h4)
            self.tracker.reset()
            self.machine_fired = set()
            self.fired = set()
            self._write_state()
            self._update_status(price=None)  # price unknown here; keep ₿ … placeholder
        except Exception as e:  # network/API/data error — keep the app alive, retry later
            print(f"[watcher] remark_now failed, keeping previous levels: {e}")

    # --- status lines ---
    def _update_status(self, price=None, next_scan=None):
        if price is None:
            price_str = "₿ …"
        else:
            price_str = f"₿ {price:,.0f}"
        if self.bias is None:
            self.status_price.title = f"{price_str} · bias —"
        else:
            b = self.bias
            self.status_price.title = (
                f"{price_str} · Daily {b.daily_dir} H4 {b.h4_dir} mom {b.mom14_dir}"
            )
        if self.last_alert:
            self.status_alert.title = (
                f"Last alert: {self.last_alert['time']} {self.last_alert['text']}"
            )
        else:
            self.status_alert.title = "Last alert: —"
        watch = f"Watching {len(self.levels)} levels"
        if next_scan:
            watch += f" · next scan {next_scan}"
        self.status_watch.title = watch

    # --- scheduled loop ---
    def tick(self, _):
        try:
            self._maybe_morning_pass()
            if not self.levels or self.bias is None:
                return  # no marked levels yet (e.g. the launch remark failed); wait for next remark
            m15 = fetch_recent("15m", limit=300)
            closed = m15.iloc[:-1]  # drop the still-open candle
            if len(closed) == 0:
                return  # thin/empty response — skip this tick, recover next interval
            last = closed.iloc[-1]
            bar = {"high": float(last["high"]), "low": float(last["low"]),
                   "close": float(last["close"])}
            triggers = scan(bar, self.levels, self.bias, self.fired,
                            require_alignment=cfg.REQUIRE_HTF_ALIGNMENT,
                            counter_trend_mode=cfg.COUNTER_TREND_MODE)
            price = _clean_price(last["close"])
            for t in triggers:
                self._emit(t, price)
            self.title = f"₿ {price:,.0f}"
            # Phase 2: advance the per-AOI trigger state machine on M15 + M5
            m5 = fetch_recent(cfg.ENTRY_TF, limit=300).iloc[:-1]   # drop in-progress M5
            inst = get_instrument("BTCUSDT")
            events = self.tracker.advance_all(self.aois, closed, m5, inst,
                                              cfg.STALE_SWEEP_BARS, cfg.STALE_SHIFT_BARS)
            for aoi, st, _prior in events:
                self._emit_machine(aoi, st)
            for aoi in self.aois:                                  # reflect state for the chart
                ms = self.tracker.states.get(aoi_key(aoi))
                if ms is not None:
                    aoi.state, aoi.plan = ms.state, ms.plan
            self._write_state(price=price, candles=_df_to_candles(closed.tail(200)))
            next_scan = (pd.Timestamp.now(tz=ZoneInfo(cfg.MORNING_TZ))
                         + pd.Timedelta(minutes=cfg.SCAN_INTERVAL_MIN)).strftime("%H:%M")
            self._update_status(price=price, next_scan=next_scan)
        except Exception as e:  # never let one bad tick stop the timer
            print(f"[watcher] tick failed, will retry next interval: {e}")

    def _maybe_morning_pass(self):
        local = pd.Timestamp.now(tz=ZoneInfo(cfg.MORNING_TZ))
        hh, mm = cfg.MORNING_TIME.split(":")
        hh, mm = int(hh), int(mm)
        key = local.date().isoformat()
        # Fire once when the local time is within the [mm, mm + SCAN_INTERVAL_MIN) window
        # of the configured hour. For the default 08:00 this is identical to minute < interval.
        if local.hour == hh and mm <= local.minute < mm + cfg.SCAN_INTERVAL_MIN \
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

    def _emit_machine(self, aoi, st):
        if st.state not in cfg.ALERT_STAGES:
            return
        if not _grade_ok(aoi.label, cfg.MIN_ALERT_GRADE):
            return
        key = (aoi_key(aoi), st.state)
        if key in self.machine_fired:
            return
        self.machine_fired.add(key)
        side = "short" if aoi.side == "supply" else "long"
        title = f"⚡ {st.state} — {aoi.label} {side} @ {aoi.source} {aoi.proximal:,.0f}"
        if st.state == "ARMED" and st.plan:
            p = st.plan
            tgt = f"{p['target']:,.0f}" if p["target"] is not None else "—"
            body = f"entry {p['entry']:,.0f} · stop {p['stop']:,.0f} · target {tgt} · {p['rr']:.1f}R"
        else:
            body = "entry forming"
        if self.settings["notifications_enabled"]:
            rumps.notification(title, "", body, sound=self.settings["alert_sound_enabled"])

    def _write_state(self, price=None, candles=None):
        if self.bias is None:
            return  # nothing meaningful to write until the first successful remark
        payload = state.build_state(
            price=_clean_price(price) if price is not None else 0.0,
            levels=self.levels, zones=self.zones, bias=self.bias,
            fired=list(self.fired), last_alert=self.last_alert,
            updated_at=pd.Timestamp.now(tz="UTC").isoformat(),
            aois=self.aois,
            bias_tf=self.bias_tf,
        )
        if candles is not None:
            payload["candles"] = candles
        state.save_state(payload, STATE_FILE)


if __name__ == "__main__":
    WatcherApp().run()
