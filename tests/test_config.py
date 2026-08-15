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
