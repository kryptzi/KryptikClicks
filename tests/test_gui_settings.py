import pytest


@pytest.fixture
def make_gui(kc, monkeypatch):
    """Builds a real KryptikClicksGUI (real Tk widgets) with the blocking mainloop and
    the global keyboard hook stubbed out, so form wiring can be exercised directly."""
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
        app.root.destroy()


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
