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
    cfg["click_position"] = "fixed"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is True  # no template captured, but that's fine in generic mode


def test_generic_fixed_mode_not_ready_without_click_point(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["click_position"] = "fixed"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is False


def test_generic_cursor_mode_always_ready(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["click_position"] = "cursor"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is True  # no capture needed at all


def test_targeted_cursor_mode_needs_template_but_not_click_point(kc):
    from PIL import Image

    Image.new("L", (20, 20), 128).save(kc.TEMPLATE_PATH)

    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["click_position"] = "cursor"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is True  # trigger template captured, no click point needed


def test_targeted_cursor_mode_not_ready_without_template(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["click_position"] = "cursor"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is False


def test_targeted_color_mode_needs_target_color_not_template(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["click_position"] = "cursor"
    cfg["detection_method"] = "color"
    d = kc.Detector(cfg, log=lambda m: None)
    assert d.ready is False  # no target color captured yet

    cfg["target_color"] = [118, 52, 171]
    d2 = kc.Detector(cfg, log=lambda m: None)
    assert d2.ready is True  # color captured, no template file needed at all
