"""Watcher configuration: static defaults plus the two persisted UI toggles."""
import json
import os

# --- Static behavior knobs (edit in source) ---
SCAN_INTERVAL_MIN = 5
MORNING_TIME = "08:00"          # HH:MM in MORNING_TZ
MORNING_TZ = "Europe/Oslo"      # user's local time; tracks DST (was specified as "UTC+2")
DAILY_SWING_LOOKBACK_N = 5      # how many recent Daily swings (each side) to mark
H4_SWING_LOOKBACK_N = 6
SWING_LEFT = 2                  # fractal window, matches liquidity.swing_points defaults
SWING_RIGHT = 2
REQUIRE_HTF_ALIGNMENT = True
COUNTER_TREND_MODE = "silent"   # "silent" | "fyi"

# --- Persisted UI toggles ---
SETTINGS_PATH = "app_settings.json"
DEFAULT_SETTINGS = {"notifications_enabled": True, "alert_sound_enabled": False}


def load_settings(path: str = SETTINGS_PATH) -> dict:
    """Return persisted settings merged over DEFAULT_SETTINGS.

    A missing or corrupt settings file falls back to defaults rather than crashing
    the long-running app on startup.
    """
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(path):
        try:
            with open(path) as f:
                settings.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict, path: str = SETTINGS_PATH) -> None:
    """Persist the UI toggles to `path` as JSON."""
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
