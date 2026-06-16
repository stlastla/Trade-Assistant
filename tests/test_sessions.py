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
