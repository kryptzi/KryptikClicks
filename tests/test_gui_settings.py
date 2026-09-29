import gc

import pytest


@pytest.fixture
def make_gui(kc, monkeypatch):
    """Builds a real KryptikClicksGUI (real Tk widgets) with the blocking mainloop and
    the global keyboard hook stubbed out, so form wiring can be exercised directly.

    Teardown collects garbage on the main thread on purpose: the app sits in
    reference cycles, and if cyclic GC later frees its Tk variables on some other
    thread (e.g. a later test's detector worker), Variable.__del__ blocks that thread
    ~1s per variable waiting for a Tk mainloop that isn't running - stalling it."""
    import tkinter as tk
    from pynput import keyboard as pynkeyboard

    class NoopListener:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(pynkeyboard, "Listener", NoopListener)
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self, n=0: None)
    apps = []

    def make():
        apps.append(kc.KryptikClicksGUI())
        return apps[-1]

    yield make
    for app in apps:
        app.detector.stop_event.set()
        app.worker_thread.join(2.0)
        try:
            app.root.destroy()
        except tk.TclError:
            pass  # the test already quit the app
    apps.clear()
    gc.collect()


@pytest.fixture
def gui(make_gui):
    return make_gui()


def _is_shown(widget):
    return bool(widget.winfo_manager())


def test_trigger_delay_fields_save_to_config(kc, gui):
    gui.trigger_min_var.set("150")
    gui.trigger_max_var.set("300")

    gui.on_save_settings()

    assert gui.cfg["trigger_delay_min_ms"] == 150.0
    assert gui.cfg["trigger_delay_max_ms"] == 300.0
    saved = kc.load_config()
    assert saved["trigger_delay_min_ms"] == 150.0
    assert saved["trigger_delay_max_ms"] == 300.0


def test_invalid_trigger_delay_is_rejected_without_saving(kc, gui, monkeypatch):
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: errors.append(msg))
    gui.trigger_min_var.set("300")
    gui.trigger_max_var.set("100")

    gui.on_save_settings()

    assert errors
    assert kc.load_config()["trigger_delay_min_ms"] == 0


def test_trigger_delay_fields_show_saved_values_on_open(kc, make_gui):
    kc.save_config({"trigger_delay_min_ms": 120, "trigger_delay_max_ms": 480})

    app = make_gui()

    assert float(app.trigger_min_var.get()) == 120
    assert float(app.trigger_max_var.get()) == 480


def test_trigger_delay_rows_hide_in_generic_mode_and_return_in_targeted(gui):
    # Generic mode has no trigger to react to, so the setting would be inert there.
    assert all(_is_shown(w) for w in gui.trigger_delay_row_widgets)

    gui.mode_var.set("generic")
    gui._on_mode_changed()
    assert not any(_is_shown(w) for w in gui.trigger_delay_row_widgets)

    gui.mode_var.set("targeted")
    gui._on_mode_changed()
    assert all(_is_shown(w) for w in gui.trigger_delay_row_widgets)


def test_switching_generic_then_back_to_targeted_keeps_advanced_tab_order(gui):
    # pack_forget() + pack() appends a widget to the END of its parent's packing
    # list - so hiding Detection method / Scan area for Generic and re-showing them
    # used to move both below the settings panel and Save Settings button.
    advanced_tab = gui.detection_frame.master
    before = advanced_tab.pack_slaves()
    layout_before = [gui.detection_frame.pack_info(), gui.scan_scope_frame.pack_info()]

    gui.mode_var.set("generic")
    gui._on_mode_changed()
    gui.mode_var.set("targeted")
    gui._on_mode_changed()

    assert advanced_tab.pack_slaves() == before
    assert [gui.detection_frame.pack_info(), gui.scan_scope_frame.pack_info()] == layout_before


def test_window_still_opens_when_a_saved_capture_file_is_unreadable(kc, make_gui):
    # Detector.load() logs a warning for a corrupt capture, but the Detector was built
    # before the Tk root existed, so log() -> self.root raised AttributeError and the
    # app silently never opened (pythonw has no console) until the file was deleted.
    with open(kc.TARGET_PATH, "w") as f:
        f.write("")  # e.g. truncated by a crash mid-save

    app = make_gui()
    app.root.update()  # flush the root.after(0, ...) log calls

    assert any("click_target.txt" in line for line in app.log_list.get(0, "end"))


def test_an_unreadable_config_is_reported_when_the_window_opens(kc, make_gui, monkeypatch):
    with open(kc.CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write('{"detection_method": "color",}')  # stray comma
    shown = []
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showwarning", lambda title, msg, **kw: shown.append(msg))

    app = make_gui()
    app.root.update()

    assert shown and ".unreadable-" in shown[0]
    assert any("default settings" in line for line in app.log_list.get(0, "end"))


def test_color_capture_calibrates_at_the_configured_tolerance(kc, make_gui, monkeypatch):
    from PIL import Image

    img = Image.new("RGB", (5, 1), (110, 96, 98))
    for x in range(3):
        img.putpixel((x, 0), (118, 52, 171))
    img.putpixel((3, 0), (148, 52, 171))  # within tolerance 40, not 20
    kc.save_config({"detection_method": "color", "click_position": "cursor", "color_tolerance": 40})
    monkeypatch.setattr(kc, "run_capture_ui", lambda **kwargs: ((0, 0, 5, 1), None, img))
    app = make_gui()

    app.on_capture()

    # 4 pixels match at tolerance 40 -> threshold 2; counting at 20 would give 3 -> 1.
    assert app.cfg["min_color_pixels"] == 2


def _ready_and_scanning(kc, app):
    app.cfg.update(click_mode="generic", click_position="cursor")  # ready with no capture
    app.detector.start_scanning()
    assert app.detector.scanning_active.is_set()


@pytest.mark.parametrize("cancelled", [False, True])
def test_limit_to_region_pauses_clicking_while_the_overlay_is_up(kc, gui, monkeypatch, cancelled):
    # The region picker is a frozen full-screen snapshot: the worker kept "seeing" the
    # trigger in it and clicking wherever the mouse was - i.e. mid-drag.
    from PIL import Image

    _ready_and_scanning(kc, gui)
    gui.scan_window_title_var.set("RuneLite")
    monkeypatch.setattr(kc, "list_visible_windows", lambda exclude_hwnd=None: [(7, "RuneLite")])
    monkeypatch.setattr(kc, "get_window_rect", lambda hwnd: {"left": 0, "top": 0, "width": 800, "height": 600})
    seen_during = []

    def fake_overlay(**kwargs):
        seen_during.append(gui.detector.scanning_active.is_set())
        if cancelled:
            return None, None, None
        return (10, 10, 110, 60), None, Image.new("RGB", (800, 600))

    monkeypatch.setattr(kc, "run_capture_ui", fake_overlay)

    gui.on_define_scan_region()

    assert seen_during == [False]
    assert gui.detector.scanning_active.is_set()  # resumed afterwards, even on Esc


def test_choose_window_picker_pauses_clicking_until_it_closes(kc, gui, monkeypatch):
    # In cursor mode a detection would click wherever the mouse is - i.e. on the picker.
    monkeypatch.setattr(kc, "list_visible_windows", lambda exclude_hwnd=None: [])
    _ready_and_scanning(kc, gui)

    gui.on_choose_window()
    picker = [w for w in gui.root.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    assert not gui.detector.scanning_active.is_set()

    picker.destroy()
    gui.root.update()
    assert gui.detector.scanning_active.is_set()


@pytest.mark.parametrize("flow", ["on_capture", "on_define_scan_region"])
def test_quitting_with_f9_while_an_overlay_is_open_exits_cleanly(kc, gui, monkeypatch, flow):
    # F9 is dispatched onto the Tk thread and runs inside the overlay's nested event
    # loop, destroying the root; the flow's `finally: root.deiconify()` then raised
    # TclError, shown as a "KryptikClicks - unexpected error" dialog on the way out.
    gui.scan_window_title_var.set("RuneLite")
    monkeypatch.setattr(kc, "list_visible_windows", lambda exclude_hwnd=None: [(7, "RuneLite")])
    monkeypatch.setattr(kc, "get_window_rect", lambda hwnd: {"left": 0, "top": 0, "width": 800, "height": 600})

    def quit_during_overlay(**kwargs):
        gui.on_quit()  # what the F9 hotkey does
        return None, None, None

    monkeypatch.setattr(kc, "run_capture_ui", quit_during_overlay)

    getattr(gui, flow)()  # must not raise

    assert gui.detector.stop_event.is_set()


@pytest.mark.parametrize("mode, method, threshold_shown", [
    ("targeted", "template", True),
    ("targeted", "color", False),   # color match uses the pixel count, not the threshold
    ("generic", "template", False),  # generic has no trigger at all
    ("generic", "color", False),
])
def test_match_threshold_only_shows_where_it_applies(gui, mode, method, threshold_shown):
    gui.detection_method_var.set(method)
    gui._on_detection_method_changed()
    gui.mode_var.set(mode)
    gui._on_mode_changed()

    assert all(_is_shown(w) == threshold_shown for w in gui.thr_row_widgets)


def test_a_bad_value_in_a_hidden_field_does_not_block_saving_the_rest(kc, gui, monkeypatch):
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: errors.append(msg))
    gui.thr_var.set("0")            # invalid, typed while it was visible...
    gui.trigger_min_var.set("900")  # ...and an invalid trigger range
    gui.trigger_max_var.set("100")
    gui.detection_method_var.set("color")
    gui._on_detection_method_changed()  # hides the threshold
    gui.mode_var.set("generic")
    gui._on_mode_changed()              # hides the trigger delay
    gui.min_var.set("100")

    gui.on_save_settings()

    assert errors == []
    saved = kc.load_config()
    assert saved["min_delay_ms"] == 100.0
    assert saved["match_threshold"] == kc.DEFAULT_CONFIG["match_threshold"]  # hidden: kept as it was
    assert saved["trigger_delay_min_ms"] == 0


def test_generic_mode_capture_only_sets_the_click_point_and_keeps_the_trigger(kc, make_gui, monkeypatch):
    # Generic mode only needs a click point, but capture made you drag a "trigger" box
    # first and saved it - overwriting the Targeted setup (e.g. the calibrated color).
    from PIL import Image

    Image.new("L", (30, 20), 77).save(kc.TEMPLATE_PATH)
    kc.save_config({
        "click_mode": "generic", "click_position": "fixed", "detection_method": "color",
        "target_color": [102, 46, 143], "min_color_pixels": 7175,
    })
    with open(kc.TEMPLATE_PATH, "rb") as f:
        template_before = f.read()
    calls = []

    def fake_overlay(**kwargs):
        calls.append(kwargs)
        return None, (50, 60), Image.new("RGB", (100, 100), (0, 200, 0))

    monkeypatch.setattr(kc, "run_capture_ui", fake_overlay)
    app = make_gui()
    assert app.capture_var.get() == "Capture Click Target..."

    app.on_capture()

    assert calls[0]["require_trigger"] is False and calls[0]["require_click_point"] is True
    assert app.cfg["target_color"] == [102, 46, 143] and app.cfg["min_color_pixels"] == 7175
    with open(kc.TEMPLATE_PATH, "rb") as f:
        assert f.read() == template_before
    assert (app.detector.click_x, app.detector.click_y) == (50, 60)
    assert app.capture_var.get() == "Recapture Click Target..."


def test_targeted_capture_still_asks_for_the_trigger(kc, gui, monkeypatch):
    calls = []
    monkeypatch.setattr(kc, "run_capture_ui", lambda **kwargs: calls.append(kwargs) or (None, None, None))

    gui.on_capture()

    assert calls[0]["require_trigger"] is True


def _pump_until(app, condition, timeout=2.0):
    import time

    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    return condition()


def _in_thread(fn):
    import threading

    t = threading.Thread(target=fn, daemon=True)
    t.start()
    t.join(3.0)


def test_a_worker_thread_log_returns_at_once_and_reaches_the_activity_panel(gui):
    # Worker threads used to call root.after() directly: that blocks until the Tk
    # thread services it (so a busy UI delayed the detector - and its next click), and
    # raises "main thread is not in main loop" when no mainloop is running.
    import time

    took = []

    def log_from_worker():
        start = time.monotonic()
        gui.log("hello from the worker")
        took.append(time.monotonic() - start)

    _in_thread(log_from_worker)  # the Tk thread is NOT servicing events meanwhile

    assert took and took[0] < 0.05
    assert _pump_until(gui, lambda: any("hello from the worker" in line for line in gui.log_list.get(0, "end")))


def test_hotkeys_from_the_listener_thread_run_on_the_ui_thread(gui):
    import threading

    ran_on = []
    _in_thread(lambda: gui.hotkeys.dispatch(lambda: ran_on.append(threading.current_thread())))

    assert _pump_until(gui, lambda: ran_on)
    assert ran_on == [threading.main_thread()]


def test_update_check_always_reports_back_even_if_it_fails(kc, gui, monkeypatch):
    def exploding_check(version, fetcher=None):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(kc, "check_for_update", exploding_check)
    gui.update_status_label.config(text="Checking for updates...")

    gui._run_update_check(silent=False)

    assert _pump_until(gui, lambda: "couldn't check" in gui.update_status_label.cget("text").lower())
