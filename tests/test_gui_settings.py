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
