def test_default_config_has_generic_mode_settings(kc):
    cfg = kc.load_config()
    assert cfg["click_mode"] == "targeted"
    assert cfg["click_position"] == "fixed"
    assert cfg["click_limit"] == 0
    assert cfg["sound_enabled"] is False
    assert cfg["auto_update_check"] is True
    assert cfg["scan_scope"] == "all_monitors"
    assert cfg["scan_window_title"] == ""
    assert cfg["detection_method"] == "template"
    assert cfg["target_color"] is None
    assert cfg["color_tolerance"] == 30
    assert cfg["min_color_pixels"] == 0


def test_load_config_rejects_invalid_detection_method(kc):
    kc.save_config({"detection_method": "bogus"})
    cfg = kc.load_config()
    assert cfg["detection_method"] == "template"


def test_load_config_rejects_malformed_target_color(kc):
    kc.save_config({"target_color": [1, 2]})
    cfg = kc.load_config()
    assert cfg["target_color"] is None

    kc.save_config({"target_color": [1, 2, 300]})
    cfg = kc.load_config()
    assert cfg["target_color"] is None

    kc.save_config({"target_color": "purple"})
    cfg = kc.load_config()
    assert cfg["target_color"] is None


def test_load_config_accepts_valid_target_color(kc):
    kc.save_config({"target_color": [118, 52, 171]})
    cfg = kc.load_config()
    assert cfg["target_color"] == [118, 52, 171]


def test_load_config_rejects_negative_color_tolerance(kc):
    kc.save_config({"color_tolerance": -5})
    cfg = kc.load_config()
    assert cfg["color_tolerance"] == 30


def test_load_config_rejects_negative_min_color_pixels(kc):
    kc.save_config({"min_color_pixels": -1})
    cfg = kc.load_config()
    assert cfg["min_color_pixels"] == 0


def test_load_config_rejects_invalid_scan_scope(kc):
    kc.save_config({"scan_scope": "bogus"})
    cfg = kc.load_config()
    assert cfg["scan_scope"] == "all_monitors"


def test_load_config_rejects_non_string_scan_window_title(kc):
    kc.save_config({"scan_window_title": 12345})
    cfg = kc.load_config()
    assert cfg["scan_window_title"] == ""


def test_load_config_rejects_non_bool_auto_update_check(kc):
    kc.save_config({"auto_update_check": "yes"})
    cfg = kc.load_config()
    assert cfg["auto_update_check"] is True


def test_load_config_rejects_invalid_click_mode(kc):
    kc.save_config({"click_mode": "bogus"})
    cfg = kc.load_config()
    assert cfg["click_mode"] == "targeted"


def test_load_config_rejects_invalid_click_position(kc):
    kc.save_config({"click_position": "bogus"})
    cfg = kc.load_config()
    assert cfg["click_position"] == "fixed"


def test_load_config_rejects_negative_click_limit(kc):
    kc.save_config({"click_limit": -5})
    cfg = kc.load_config()
    assert cfg["click_limit"] == 0


def test_load_config_rejects_non_numeric_delay_values(kc):
    # A hand-edited or otherwise corrupted config with non-numeric delay/threshold
    # values would otherwise crash the background thread's sleep_between_clicks()
    # the first time it runs (self.cfg["min_delay_ms"] / 1000.0 on a string).
    kc.save_config({"min_delay_ms": "fast", "max_delay_ms": None, "match_threshold": "high"})
    cfg = kc.load_config()
    assert cfg["min_delay_ms"] == kc.DEFAULT_CONFIG["min_delay_ms"]
    assert cfg["max_delay_ms"] == kc.DEFAULT_CONFIG["max_delay_ms"]
    assert cfg["match_threshold"] == kc.DEFAULT_CONFIG["match_threshold"]


def test_load_config_rejects_threshold_out_of_range(kc):
    kc.save_config({"match_threshold": 1.5})
    cfg = kc.load_config()
    assert cfg["match_threshold"] == kc.DEFAULT_CONFIG["match_threshold"]


def test_load_config_rejects_max_delay_below_min_delay(kc):
    kc.save_config({"min_delay_ms": 200, "max_delay_ms": 50})
    cfg = kc.load_config()
    assert cfg["min_delay_ms"] == kc.DEFAULT_CONFIG["min_delay_ms"]
    assert cfg["max_delay_ms"] == kc.DEFAULT_CONFIG["max_delay_ms"]
