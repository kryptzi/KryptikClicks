def test_default_config_has_generic_mode_settings(kc):
    cfg = kc.load_config()
    assert cfg["click_mode"] == "targeted"
    assert cfg["generic_position"] == "fixed"
    assert cfg["click_limit"] == 0
    assert cfg["sound_enabled"] is False


def test_load_config_rejects_invalid_click_mode(kc):
    kc.save_config({"click_mode": "bogus"})
    cfg = kc.load_config()
    assert cfg["click_mode"] == "targeted"


def test_load_config_rejects_invalid_generic_position(kc):
    kc.save_config({"generic_position": "bogus"})
    cfg = kc.load_config()
    assert cfg["generic_position"] == "fixed"


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
