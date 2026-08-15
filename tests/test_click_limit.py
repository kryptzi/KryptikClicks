def test_total_clicks_starts_at_zero(kc):
    cfg = kc.load_config()
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.total_clicks == 0


def test_limit_not_reached_when_limit_is_zero_infinite(kc):
    cfg = kc.load_config()
    cfg["click_limit"] = 0
    d = kc.Detector(cfg, log=lambda m: None)
    d.total_clicks = 10_000
    assert d._limit_reached() is False


def test_limit_reached_once_total_clicks_hits_limit(kc):
    cfg = kc.load_config()
    cfg["click_limit"] = 5
    d = kc.Detector(cfg, log=lambda m: None)
    d.total_clicks = 4
    assert d._limit_reached() is False
    d.total_clicks = 5
    assert d._limit_reached() is True


def test_start_scanning_resets_click_count_and_activates(kc):
    cfg = kc.load_config()
    d = kc.Detector(cfg, log=lambda m: None)
    d.total_clicks = 7
    d.start_scanning()
    assert d.total_clicks == 0
    assert d.scanning_active.is_set() is True


def test_pause_scanning_deactivates_without_resetting_count(kc):
    cfg = kc.load_config()
    d = kc.Detector(cfg, log=lambda m: None)
    d.start_scanning()
    d.total_clicks = 3
    d.pause_scanning()
    assert d.scanning_active.is_set() is False
    assert d.total_clicks == 3
