import threading
import time

import pytest


def _run_until_paused_or_timeout(detector, timeout=3.0):
    # Detector.run() is a long-lived background worker: hitting the click limit
    # pauses scanning (clears scanning_active) but the thread itself keeps running
    # idle until stop_event is set - so we poll for the pause, not thread death.
    t = threading.Thread(target=detector.run, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not detector.scanning_active.is_set():
                return
            time.sleep(0.02)
        pytest.fail("Detector did not auto-pause (hit the click limit) in time")
    finally:
        detector.stop_event.set()
        t.join(2.0)


def test_generic_mode_clicks_immediately_without_a_trigger_and_stops_at_limit(kc, monkeypatch):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["click_position"] = "fixed"
    cfg["click_limit"] = 3
    cfg["min_delay_ms"] = 0
    cfg["max_delay_ms"] = 1

    d = kc.Detector(cfg, log=lambda m: None)
    d.click_x, d.click_y = 5, 5  # generic+fixed only needs a click point, no template

    calls = []
    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: calls.append(a))

    d.start_scanning()
    _run_until_paused_or_timeout(d)

    assert len(calls) == 3
    assert d.total_clicks == 3
    assert d.scanning_active.is_set() is False  # auto-paused itself on hitting the limit


def test_targeted_mode_only_clicks_while_a_match_is_found_and_stops_at_limit(kc, monkeypatch):
    from PIL import Image

    Image.new("L", (20, 20), 128).save(kc.TEMPLATE_PATH)
    with open(kc.TARGET_PATH, "w") as f:
        f.write("5,5")

    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["click_limit"] = 3
    cfg["min_delay_ms"] = 0
    cfg["max_delay_ms"] = 1

    d = kc.Detector(cfg, log=lambda m: None)

    # Simulate the trigger being permanently visible so we don't depend on real screen content.
    monkeypatch.setattr(kc.Detector, "_find_match_in", lambda self, sct, region: (5, 5))

    calls = []
    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: calls.append(a))

    d.start_scanning()
    _run_until_paused_or_timeout(d)

    assert len(calls) == 3
    assert d.total_clicks == 3
    assert d.scanning_active.is_set() is False


def test_targeted_mode_does_not_click_when_nothing_matches(kc, monkeypatch):
    from PIL import Image

    Image.new("L", (20, 20), 128).save(kc.TEMPLATE_PATH)
    with open(kc.TARGET_PATH, "w") as f:
        f.write("5,5")

    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"

    d = kc.Detector(cfg, log=lambda m: None)
    monkeypatch.setattr(kc.Detector, "_find_match_in", lambda self, sct, region: None)

    calls = []
    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: calls.append(a))

    d.start_scanning()
    t = threading.Thread(target=d.run, daemon=True)
    t.start()
    t.join(0.3)  # let it scan a few times, finding nothing
    d.stop_event.set()
    t.join(2.0)

    assert calls == []
    assert d.total_clicks == 0


def test_targeted_cursor_mode_clicks_once_then_waits_for_trigger_to_disappear(kc, monkeypatch):
    # Cursor-position mode clicks wherever the mouse already is, not on the
    # trigger itself - so unlike fixed-position mode, clicking never makes the
    # trigger go away on its own. If it kept re-clicking as long as the trigger
    # was still visible, a persistent on-screen trigger would spam-click forever.
    # It should click once, then wait for the trigger to actually disappear
    # (and a fresh detection to occur) before clicking again.
    from PIL import Image

    Image.new("L", (20, 20), 128).save(kc.TEMPLATE_PATH)

    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["click_position"] = "cursor"
    cfg["min_delay_ms"] = 0
    cfg["max_delay_ms"] = 1

    d = kc.Detector(cfg, log=lambda m: None)

    # Simulate the trigger being permanently visible so we don't depend on real screen content.
    monkeypatch.setattr(kc.Detector, "_find_match_in", lambda self, sct, region: (5, 5))

    calls = []
    import pyautogui
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(pyautogui, "position", lambda: (5, 5))

    d.start_scanning()
    t = threading.Thread(target=d.run, daemon=True)
    t.start()
    t.join(0.3)  # let several scan cycles pass while the trigger stays visible
    d.stop_event.set()
    t.join(2.0)

    assert len(calls) == 1
    assert d.total_clicks == 1
