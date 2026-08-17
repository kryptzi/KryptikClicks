def test_not_ready_shows_get_started_message(kc):
    cfg = kc.load_config()
    assert kc.describe_current_setup(cfg, ready=False) == "Capture a trigger to get started."


def test_targeted_template_all_monitors_cursor(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["detection_method"] = "template"
    cfg["scan_scope"] = "all_monitors"
    cfg["click_position"] = "cursor"

    result = kc.describe_current_setup(cfg, ready=True, captured_desc="the picture you captured")

    assert result == (
        "Watching for the picture you captured anywhere on your screen, "
        "clicking wherever your mouse already is when it's found."
    )


def test_targeted_color_window_scope_fixed_position(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "targeted"
    cfg["detection_method"] = "color"
    cfg["scan_scope"] = "window"
    cfg["scan_window_title"] = "RuneLite"
    cfg["click_position"] = "fixed"

    result = kc.describe_current_setup(cfg, ready=True, captured_desc="the color you captured")

    assert result == (
        'Watching for the color you captured in "RuneLite", '
        "clicking at your saved click spot when it's found."
    )


def test_generic_fixed_position(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["click_position"] = "fixed"
    cfg["min_delay_ms"] = 50
    cfg["max_delay_ms"] = 150

    result = kc.describe_current_setup(cfg, ready=True)

    assert result == "Clicking automatically at your saved click spot every 50-150ms."


def test_generic_cursor_position(kc):
    cfg = kc.load_config()
    cfg["click_mode"] = "generic"
    cfg["click_position"] = "cursor"
    cfg["min_delay_ms"] = 100
    cfg["max_delay_ms"] = 350

    result = kc.describe_current_setup(cfg, ready=True)

    assert result == "Clicking automatically wherever your mouse already is every 100-350ms."
