def test_click_once_clicks_resolved_position_with_configured_button(kc, monkeypatch):
    cfg = kc.load_config()
    cfg["click_button"] = "right"
    d = kc.Detector(cfg, log=lambda m: None)
    d.click_x, d.click_y = 50, 60

    calls = []
    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda x, y, button: calls.append((x, y, button)))

    d._click_once()

    assert calls == [(50, 60, "right")]


def test_click_once_increments_total_clicks(kc, monkeypatch):
    cfg = kc.load_config()
    d = kc.Detector(cfg, log=lambda m: None)
    d.click_x, d.click_y = 1, 1

    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: None)

    assert d.total_clicks == 0
    d._click_once()
    assert d.total_clicks == 1
    d._click_once()
    assert d.total_clicks == 2


def test_click_once_swallows_click_errors_without_crashing(kc, monkeypatch):
    cfg = kc.load_config()
    d = kc.Detector(cfg, log=lambda m: None)
    d.click_x, d.click_y = 1, 1

    import pyautogui

    def boom(*a, **k):
        raise RuntimeError("simulated click failure")

    monkeypatch.setattr(pyautogui, "click", boom)

    d._click_once()  # must not raise
    assert d.total_clicks == 1  # still counted as an attempted click


def test_click_once_swallows_position_resolution_errors_without_crashing(kc, monkeypatch):
    # Regression test: generic+cursor mode resolves the click position via
    # pyautogui.position(), a second fallible pyautogui call alongside
    # pyautogui.click() - it must be guarded the same way, or a background
    # scan/click thread can die silently (the exact class of bug this
    # project's error handling elsewhere is meant to prevent).
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["click_position"] = "cursor"
    d = kc.Detector(cfg, log=lambda m: None)

    import pyautogui

    def boom():
        raise RuntimeError("simulated position-query failure")

    monkeypatch.setattr(pyautogui, "position", boom)
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: None)

    d._click_once()  # must not raise
    assert d.total_clicks == 1


def test_beep_does_nothing_when_sound_disabled(kc, monkeypatch):
    cfg = kc.load_config()
    cfg["sound_enabled"] = False
    d = kc.Detector(cfg, log=lambda m: None)

    calls = []
    import winsound
    monkeypatch.setattr(winsound, "Beep", lambda *a: calls.append(a))

    d._beep()
    assert calls == []


def test_beep_plays_when_sound_enabled(kc, monkeypatch):
    cfg = kc.load_config()
    cfg["sound_enabled"] = True
    d = kc.Detector(cfg, log=lambda m: None)

    calls = []
    import winsound
    monkeypatch.setattr(winsound, "Beep", lambda *a: calls.append(a))

    d._beep()
    assert len(calls) == 1
