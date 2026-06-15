import json
import app_config


def test_load_settings_returns_defaults_when_missing(tmp_path):
    path = tmp_path / "settings.json"
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": True, "alert_sound_enabled": False}


def test_save_then_load_roundtrips(tmp_path):
    path = tmp_path / "settings.json"
    app_config.save_settings({"notifications_enabled": False, "alert_sound_enabled": True}, str(path))
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": False, "alert_sound_enabled": True}


def test_load_settings_fills_missing_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"notifications_enabled": False}))
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": False, "alert_sound_enabled": False}


def test_load_settings_falls_back_on_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json")
    s = app_config.load_settings(str(path))
    assert s == {"notifications_enabled": True, "alert_sound_enabled": False}
