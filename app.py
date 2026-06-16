"""Multi-symbol Watcher menu-bar app. Run with: ./venv/bin/python app.py"""
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
        # Daily mark is cheap and forex is open 24/5, so mark whenever the market is open
        # (weekday) — NOT gated by the intraday session window (the morning pass fires before
        # the window opens). Only the 5-min scan in _scan_symbol uses the hour window.
        now = pd.Timestamp.now(tz="UTC")
        for ss in self.syms.values():
            if ss.inst.source == "twelvedata" and now.weekday() >= 5:
                continue   # forex market closed on weekends
            self._remark_symbol(ss)
        self._update_status()

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


if __name__ == "__main__":
    WatcherApp().run()
