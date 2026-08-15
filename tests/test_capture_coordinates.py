def test_canvas_point_to_absolute_adds_monitor_origin(kc):
    # On a multi-monitor setup where a secondary monitor sits left of/above the
    # primary, mss's combined virtual-desktop origin (monitor["left"/"top"]) is
    # non-zero. A point picked on the capture overlay is canvas-relative
    # (0,0 = top-left of the captured image) and must be converted to a true
    # absolute screen coordinate before pyautogui can click it correctly.
    monitor = {"left": -1920, "top": -200, "width": 3840, "height": 1600}
    assert kc.canvas_point_to_absolute(100, 50, monitor) == (100 - 1920, 50 - 200)


def test_canvas_point_to_absolute_is_a_noop_when_primary_is_at_origin(kc):
    monitor = {"left": 0, "top": 0, "width": 2560, "height": 1440}
    assert kc.canvas_point_to_absolute(300, 400, monitor) == (300, 400)
