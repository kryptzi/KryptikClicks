def test_targeted_mode_clicks_the_captured_point(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    d = kc.Detector(cfg, log=lambda m: None)
    d.click_x, d.click_y = 111, 222
    assert d._resolve_click_position() == (111, 222)


def test_generic_fixed_mode_clicks_the_captured_point(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["generic_position"] = "fixed"
    d = kc.Detector(cfg, log=lambda m: None)
    d.click_x, d.click_y = 111, 222
    assert d._resolve_click_position() == (111, 222)


def test_generic_cursor_mode_clicks_the_live_cursor_position(kc, monkeypatch):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["generic_position"] = "cursor"
    d = kc.Detector(cfg, log=lambda m: None)

    import pyautogui
    monkeypatch.setattr(pyautogui, "position", lambda: (333, 444))

    assert d._resolve_click_position() == (333, 444)
