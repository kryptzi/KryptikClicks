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
