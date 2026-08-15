def test_targeted_mode_requires_template_and_click_point(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is False  # nothing captured yet


def test_targeted_mode_ready_once_template_and_point_present(kc, tmp_path):
    from PIL import Image

    Image.new("L", (20, 20), 128).save(kc.TEMPLATE_PATH)
    with open(kc.TARGET_PATH, "w") as f:
        f.write("100,200")

    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is True


def test_generic_fixed_mode_needs_click_point_but_not_template(kc):
    with open(kc.TARGET_PATH, "w") as f:
        f.write("100,200")

    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["generic_position"] = "fixed"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is True  # no template captured, but that's fine in generic mode


def test_generic_fixed_mode_not_ready_without_click_point(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["generic_position"] = "fixed"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is False


def test_generic_cursor_mode_always_ready(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["generic_position"] = "cursor"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is True  # no capture needed at all
