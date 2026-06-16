from instruments import get_instrument


def test_btc_is_binance():
    i = get_instrument("BTCUSDT")
    assert i.source == "binance" and i.provider_symbol == "BTCUSDT"


def test_xau_eur_are_twelvedata():
    x = get_instrument("XAUUSD")
    e = get_instrument("EURUSD")
    assert x.source == "twelvedata" and x.provider_symbol == "XAU/USD"
    assert e.source == "twelvedata" and e.provider_symbol == "EUR/USD"
