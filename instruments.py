"""Per-instrument configuration for the confluence scorer (units, bands, weights).

Only BTCUSDT is monitored live; XAUUSD/EURUSD exist for config + tests. Every
distance comparison goes through `to_units` so a pip instrument is never compared
against a price-unit band (the unit-bug guard from the spec).
"""
from dataclasses import dataclass


@dataclass
class Instrument:
    symbol: str
    units: str          # "price" | "pips"
    pip_size: float     # price per pip (used when units == "pips")
    aoi_band: float     # swing-level AOI band width, in PRICE
    cluster_band: float # clustering tolerance, in UNITS (pips for EUR, price else)
    min_rr: float       # Factor 5 minimum reward:risk
    stop_buffer: float  # extra distance beyond the distal edge, in PRICE
    factor_weights: dict
    label_thresholds: dict
    source: str = "binance"          # "binance" | "twelvedata"
    provider_symbol: str = ""         # symbol string for that source's API


_DEFAULT_WEIGHTS = {
    "sweep": 0.35, "cluster": 0.15, "structure": 0.15,
    "shift": 0.20, "rr": 0.10, "session": 0.05,
}
_DEFAULT_THRESHOLDS = {"A+": 0.70, "valid": 0.45, "weak": 0.0}

INSTRUMENTS = {
    "BTCUSDT": Instrument("BTCUSDT", "price", 0.0, aoi_band=120.0,
                          cluster_band=150.0, min_rr=2.0, stop_buffer=60.0,
                          factor_weights=dict(_DEFAULT_WEIGHTS),
                          label_thresholds=dict(_DEFAULT_THRESHOLDS),
                          source="binance", provider_symbol="BTCUSDT"),
    "XAUUSD": Instrument("XAUUSD", "price", 0.0, aoi_band=3.0,
                         cluster_band=4.0, min_rr=2.0, stop_buffer=1.5,
                         factor_weights=dict(_DEFAULT_WEIGHTS),
                         label_thresholds=dict(_DEFAULT_THRESHOLDS),
                         source="twelvedata", provider_symbol="XAU/USD"),
    "EURUSD": Instrument("EURUSD", "pips", 0.0001, aoi_band=0.0008,
                         cluster_band=8.0, min_rr=2.0, stop_buffer=0.0004,
                         factor_weights=dict(_DEFAULT_WEIGHTS),
                         label_thresholds=dict(_DEFAULT_THRESHOLDS),
                         source="twelvedata", provider_symbol="EUR/USD"),
}


def get_instrument(symbol: str) -> Instrument:
    """Return the Instrument config for `symbol`; raises KeyError if unknown."""
    return INSTRUMENTS[symbol]


def to_units(price_distance: float, inst: Instrument) -> float:
    """Convert a raw price distance into the instrument's comparison unit."""
    if inst.units == "pips":
        return price_distance / inst.pip_size
    return price_distance
