def test_compute_scan_region_offset_relative_to_window_top_left(kc):
    window_rect = {"left": 3429, "top": 400, "width": 1331, "height": 686}
    box_abs = (3500, 450, 3800, 900)  # left, top, right, bottom
    offset = kc.compute_scan_region_offset(box_abs, window_rect)
    assert offset == {"left": 71, "top": 50, "width": 300, "height": 450}


def test_apply_scan_region_offset_reanchors_to_current_window_position(kc):
    # Window has moved since the offset was captured - the absolute region
    # must move with it, not stay pinned to the old screen position.
    window_rect = {"left": 100, "top": 200, "width": 1331, "height": 686}
    scan_region = {"left": 71, "top": 50, "width": 300, "height": 450}
    region = kc.apply_scan_region_offset(window_rect, scan_region)
    assert region == {"left": 171, "top": 250, "width": 300, "height": 450}


def test_apply_scan_region_offset_returns_window_rect_unchanged_when_no_region_set(kc):
    window_rect = {"left": 100, "top": 200, "width": 1331, "height": 686}
    assert kc.apply_scan_region_offset(window_rect, None) == window_rect


def test_resolve_scan_regions_applies_scan_region_offset_to_current_window_rect(kc, monkeypatch):
    cfg = kc.load_config()
    cfg["scan_scope"] = "window"
    cfg["scan_window_title"] = "SomeApp"
    cfg["scan_region"] = {"left": 10, "top": 20, "width": 100, "height": 50}

    d = kc.Detector(cfg, log=lambda m: None)

    monkeypatch.setattr(kc, "find_window_by_title", lambda windows, title: 999)
    monkeypatch.setattr(kc, "is_window_valid", lambda hwnd: True)
    monkeypatch.setattr(kc, "is_window_minimized", lambda hwnd: False)
    monkeypatch.setattr(
        kc, "get_window_rect",
        lambda hwnd: {"left": 500, "top": 300, "width": 800, "height": 600},
    )

    regions, hwnd, status = d._resolve_scan_regions(None, sct=None)

    assert status == "ok"
    assert hwnd == 999
    assert regions == [{"left": 510, "top": 320, "width": 100, "height": 50}]


def test_scan_region_is_clamped_to_the_window(kc):
    # A region saved for a bigger window (or one that's since been resized smaller)
    # would otherwise scan - and trigger on - whatever sits next to the window.
    window_rect = {"left": 100, "top": 100, "width": 400, "height": 300}
    scan_region = {"left": 4, "top": 25, "width": 818, "height": 659}
    assert kc.apply_scan_region_offset(window_rect, scan_region) == {
        "left": 104, "top": 125, "width": 396, "height": 275,
    }


def test_scan_region_entirely_outside_the_window_falls_back_to_the_whole_window(kc):
    window_rect = {"left": 100, "top": 100, "width": 400, "height": 300}
    scan_region = {"left": 900, "top": 25, "width": 100, "height": 100}
    assert kc.apply_scan_region_offset(window_rect, scan_region) == window_rect


def test_resolve_scan_regions_follows_a_newly_chosen_window(kc, monkeypatch):
    # Choosing a different window only changes cfg["scan_window_title"], but the
    # cached hwnd was re-resolved only once it became invalid - so with both windows
    # still open (e.g. two RuneLite clients) it kept scanning the old one.
    cfg = kc.load_config()
    cfg["scan_scope"] = "window"
    cfg["scan_window_title"] = "RuneLite - Main"
    d = kc.Detector(cfg, log=lambda m: None)
    windows = {
        111: ("RuneLite - Main", {"left": 0, "top": 0, "width": 800, "height": 600}),
        222: ("RuneLite - Alt", {"left": 2000, "top": 0, "width": 800, "height": 600}),
    }
    monkeypatch.setattr(kc, "list_visible_windows", lambda exclude_hwnd=None: [(h, t) for h, (t, _) in windows.items()])
    monkeypatch.setattr(kc, "is_window_valid", lambda hwnd: True)
    monkeypatch.setattr(kc, "is_window_minimized", lambda hwnd: False)
    monkeypatch.setattr(kc, "get_window_rect", lambda hwnd: windows[hwnd][1])

    _, hwnd, _ = d._resolve_scan_regions(None, sct=None)
    assert hwnd == 111

    cfg["scan_window_title"] = "RuneLite - Alt"
    regions, hwnd, _ = d._resolve_scan_regions(hwnd, sct=None)

    assert hwnd == 222
    assert regions[0]["left"] == 2000


def test_resolve_scan_regions_keeps_the_window_when_its_own_title_changes(kc, monkeypatch):
    # RuneLite's title changes on login/logout ("RuneLite" <-> "RuneLite - Name").
    # Only a change of the CONFIGURED title should re-resolve, not the live one.
    cfg = kc.load_config()
    cfg["scan_scope"] = "window"
    cfg["scan_window_title"] = "RuneLite - Main"
    d = kc.Detector(cfg, log=lambda m: None)
    live_windows = [(111, "RuneLite - Main")]
    monkeypatch.setattr(kc, "list_visible_windows", lambda exclude_hwnd=None: list(live_windows))
    monkeypatch.setattr(kc, "is_window_valid", lambda hwnd: True)
    monkeypatch.setattr(kc, "is_window_minimized", lambda hwnd: False)
    monkeypatch.setattr(kc, "get_window_rect", lambda hwnd: {"left": 0, "top": 0, "width": 800, "height": 600})

    _, hwnd, _ = d._resolve_scan_regions(None, sct=None)
    live_windows[:] = [(111, "RuneLite")]  # logged out
    _, hwnd, status = d._resolve_scan_regions(hwnd, sct=None)

    assert (hwnd, status) == (111, "ok")
