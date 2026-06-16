"""Orchestration tying fetch + levels + watcher together. Pure where possible."""
from typing import List, Tuple

import pandas as pd

import app_config as cfg
from levels import build_levels, bias_snapshot, unfilled_fvgs, Level, Bias
from fvg import FVG
from instruments import get_instrument
from aoi import build_aois
from bias import bias_map
from factors import ScoringContext, structure_shift_reader
from scoring import score_aoi


def run_morning_pass(daily: pd.DataFrame, h4: pd.DataFrame,
                     now: pd.Timestamp) -> Tuple[List[Level], List[FVG], Bias]:
    """Build the marked level set, display zones, and the bias snapshot for the day."""
    levels = build_levels(daily, h4, now,
                          daily_n=cfg.DAILY_SWING_LOOKBACK_N, h4_n=cfg.H4_SWING_LOOKBACK_N,
                          left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    zones = unfilled_fvgs(h4, "bull") + unfilled_fvgs(h4, "bear")
    bias = bias_snapshot(daily, h4, left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    return levels, zones, bias


def score_pass(weekly, daily, h4, etf, now, symbol="BTCUSDT"):
    """Build banded AOIs, the per-TF bias map, and score every AOI. Returns scored [AOI].

    score_aoi returns scored copies (it does not mutate), so we collect the returns."""
    inst = get_instrument(symbol)
    aois = build_aois(daily, h4, now,
                      inst, daily_n=cfg.DAILY_SWING_LOOKBACK_N, h4_n=cfg.H4_SWING_LOOKBACK_N,
                      left=cfg.SWING_LEFT, right=cfg.SWING_RIGHT)
    bm = bias_map(weekly, daily, h4)
    ctx = ScoringContext(daily=daily, h4=h4, etf=etf, all_aois=aois, bias_map=bm,
                         shift_reader=structure_shift_reader)
    return [score_aoi(aoi, ctx, inst) for aoi in aois]
