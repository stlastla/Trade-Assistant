import pytest
from instruments import Instrument, INSTRUMENTS, get_instrument, to_units


def test_known_instruments_present():
    assert set(INSTRUMENTS) >= {"BTCUSDT", "XAUUSD", "EURUSD"}


def test_btc_uses_price_units_identity():
    btc = get_instrument("BTCUSDT")
    assert btc.units == "price"
    assert to_units(150.0, btc) == 150.0


def test_eur_uses_pips():
    eur = get_instrument("EURUSD")
    assert eur.units == "pips"
    assert to_units(0.0008, eur) == pytest.approx(8.0)


def test_unknown_instrument_raises():
    with pytest.raises(KeyError):
        get_instrument("DOGE")
