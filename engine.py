"""Orchestration tying fetch + levels + watcher together. Pure where possible."""
from typing import List, Tuple

import pandas as pd

import app_config as cfg
from levels import build_levels, bias_snapshot, unfilled_fvgs, Level, Bias
from fvg import FVG


def run_morning_pass(daily: pd.DataFrame, h4: pd.DataFrame,
                     now: pd.Timestamp) -> Tuple[List[Level], List[FVG], Bias]:
    """Build the marked level set, display zones, and the bias snapshot for the day."""
    levels = build_levels(daily, h4, now,
                          daily_n=cfg.DAILY_SWING_LOOKBACK_N, h4_n=cfg.H4_SWING_LOOKBACK_N,
                          left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    zones = unfilled_fvgs(h4, "bull") + unfilled_fvgs(h4, "bear")
    bias = bias_snapshot(daily, h4, left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    return levels, zones, bias
