from aoi import AOI, aoi_key


def test_aoi_key_is_stable_and_distinct():
    a = AOI("D", "supply", 70000.004, 70120.0, "daily_swing_high")
    b = AOI("D", "supply", 70000.001, 70120.0, "daily_swing_high")
    c = AOI("D", "demand", 60000.0, 59880.0, "daily_swing_low")
    assert aoi_key(a) == "daily_swing_high:70000.0"
    assert aoi_key(a) == aoi_key(b)
    assert aoi_key(c) == "daily_swing_low:60000.0"
