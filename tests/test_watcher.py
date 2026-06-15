from levels import Level, Bias
from watcher import detect_level_sweep, scan, level_key


def _bar(high, low, close):
    return {"high": high, "low": low, "close": close}


def test_bullish_sweep_of_a_low():
    lvl = Level("pdl", 100.0, "low")
    assert detect_level_sweep(_bar(105, 98, 102), lvl) == "bullish"


def test_bearish_sweep_of_a_high():
    lvl = Level("pdh", 100.0, "high")
    assert detect_level_sweep(_bar(103, 97, 99), lvl) == "bearish"


def test_no_sweep_when_no_reclaim():
    lvl = Level("pdl", 100.0, "low")
    assert detect_level_sweep(_bar(101, 96, 97), lvl) is None


def test_no_sweep_when_level_untouched():
    lvl = Level("pdl", 100.0, "low")
    assert detect_level_sweep(_bar(110, 104, 108), lvl) is None


def test_level_key_is_stable():
    lvl = Level("pdl", 100.0, "low")
    assert level_key(lvl) == "pdl:100.00"


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
    assert "pdl:100.00" in fired


def test_scan_dedupes_already_fired_levels():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="up", h4_dir="up", mom14_dir="up")
    fired = {"pdl:100.00"}
    bar = {"high": 105, "low": 98, "close": 102}
    assert scan(bar, levels, bias, fired) == []


def test_scan_silent_mode_suppresses_counter_trend():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="down", h4_dir="down", mom14_dir="down")
    fired = set()
    bar = {"high": 105, "low": 98, "close": 102}
    assert scan(bar, levels, bias, fired,
                require_alignment=True, counter_trend_mode="silent") == []
    assert fired == set()


def test_scan_fyi_mode_emits_counter_trend_as_not_aligned():
    levels = [Level("pdl", 100.0, "low")]
    bias = Bias(daily_dir="down", h4_dir="down", mom14_dir="down")
    fired = set()
    bar = {"high": 105, "low": 98, "close": 102}
    triggers = scan(bar, levels, bias, fired,
                    require_alignment=True, counter_trend_mode="fyi")
    assert len(triggers) == 1 and triggers[0]["aligned"] is False
    assert "pdl:100.00" in fired
