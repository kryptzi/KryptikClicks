import os

import pytest


def test_default_config_has_generic_mode_settings(kc):
    cfg = kc.load_config()
    assert cfg["click_mode"] == "targeted"
    assert cfg["click_position"] == "fixed"
    assert cfg["click_limit"] == 0
    assert cfg["sound_enabled"] is False
    assert cfg["auto_update_check"] is True
    assert cfg["scan_scope"] == "all_monitors"
    assert cfg["scan_window_title"] == ""
    assert cfg["detection_method"] == "template"
    assert cfg["target_color"] is None
    assert cfg["color_tolerance"] == 20
    assert cfg["min_color_pixels"] == 0
    assert cfg["scan_region"] is None


def test_load_config_accepts_valid_scan_region(kc):
    kc.save_config({"scan_region": {"left": 10, "top": 20, "width": 300, "height": 400}})
    cfg = kc.load_config()
    assert cfg["scan_region"] == {"left": 10, "top": 20, "width": 300, "height": 400}


def test_load_config_rejects_malformed_scan_region(kc):
    kc.save_config({"scan_region": {"left": 10, "top": 20}})  # missing width/height
    cfg = kc.load_config()
    assert cfg["scan_region"] is None

    kc.save_config({"scan_region": {"left": 10, "top": 20, "width": 0, "height": 400}})
    cfg = kc.load_config()
    assert cfg["scan_region"] is None

    kc.save_config({"scan_region": "nope"})
    cfg = kc.load_config()
    assert cfg["scan_region"] is None


def test_load_config_rejects_invalid_detection_method(kc):
    kc.save_config({"detection_method": "bogus"})
    cfg = kc.load_config()
    assert cfg["detection_method"] == "template"


def test_load_config_rejects_malformed_target_color(kc):
    kc.save_config({"target_color": [1, 2]})
    cfg = kc.load_config()
    assert cfg["target_color"] is None

    kc.save_config({"target_color": [1, 2, 300]})
    cfg = kc.load_config()
    assert cfg["target_color"] is None

    kc.save_config({"target_color": "purple"})
    cfg = kc.load_config()
    assert cfg["target_color"] is None


def test_load_config_accepts_valid_target_color(kc):
    kc.save_config({"target_color": [118, 52, 171]})
    cfg = kc.load_config()
    assert cfg["target_color"] == [118, 52, 171]


def test_load_config_rejects_negative_color_tolerance(kc):
    kc.save_config({"color_tolerance": -5})
    cfg = kc.load_config()
    assert cfg["color_tolerance"] == 20


def test_load_config_rejects_negative_min_color_pixels(kc):
    kc.save_config({"min_color_pixels": -1})
    cfg = kc.load_config()
    assert cfg["min_color_pixels"] == 0


def test_load_config_rejects_invalid_scan_scope(kc):
    kc.save_config({"scan_scope": "bogus"})
    cfg = kc.load_config()
    assert cfg["scan_scope"] == "all_monitors"


def test_load_config_rejects_non_string_scan_window_title(kc):
    kc.save_config({"scan_window_title": 12345})
    cfg = kc.load_config()
    assert cfg["scan_window_title"] == ""


def test_load_config_rejects_non_bool_auto_update_check(kc):
    kc.save_config({"auto_update_check": "yes"})
    cfg = kc.load_config()
    assert cfg["auto_update_check"] is True


def test_load_config_rejects_invalid_click_mode(kc):
    kc.save_config({"click_mode": "bogus"})
    cfg = kc.load_config()
    assert cfg["click_mode"] == "targeted"


def test_load_config_rejects_invalid_click_position(kc):
    kc.save_config({"click_position": "bogus"})
    cfg = kc.load_config()
    assert cfg["click_position"] == "fixed"


def test_load_config_rejects_negative_click_limit(kc):
    kc.save_config({"click_limit": -5})
    cfg = kc.load_config()
    assert cfg["click_limit"] == 0


def test_load_config_rejects_non_numeric_delay_values(kc):
    # A hand-edited or otherwise corrupted config with non-numeric delay/threshold
    # values would otherwise crash the background thread's sleep_between_clicks()
    # the first time it runs (self.cfg["min_delay_ms"] / 1000.0 on a string).
    kc.save_config({"min_delay_ms": "fast", "max_delay_ms": None, "match_threshold": "high"})
    cfg = kc.load_config()
    assert cfg["min_delay_ms"] == kc.DEFAULT_CONFIG["min_delay_ms"]
    assert cfg["max_delay_ms"] == kc.DEFAULT_CONFIG["max_delay_ms"]
    assert cfg["match_threshold"] == kc.DEFAULT_CONFIG["match_threshold"]


def test_load_config_rejects_threshold_out_of_range(kc):
    kc.save_config({"match_threshold": 1.5})
    cfg = kc.load_config()
    assert cfg["match_threshold"] == kc.DEFAULT_CONFIG["match_threshold"]


def test_load_config_rejects_max_delay_below_min_delay(kc):
    kc.save_config({"min_delay_ms": 200, "max_delay_ms": 50})
    cfg = kc.load_config()
    assert cfg["min_delay_ms"] == kc.DEFAULT_CONFIG["min_delay_ms"]
    assert cfg["max_delay_ms"] == kc.DEFAULT_CONFIG["max_delay_ms"]


def test_default_config_has_no_trigger_delay(kc):
    # Off by default, so existing setups keep clicking the instant a trigger shows up.
    cfg = kc.load_config()
    assert cfg["trigger_delay_min_ms"] == 0
    assert cfg["trigger_delay_max_ms"] == 0


def test_load_config_accepts_valid_trigger_delay(kc):
    kc.save_config({"trigger_delay_min_ms": 250, "trigger_delay_max_ms": 600})
    cfg = kc.load_config()
    assert cfg["trigger_delay_min_ms"] == 250
    assert cfg["trigger_delay_max_ms"] == 600


@pytest.mark.parametrize("bad", [
    {"trigger_delay_min_ms": -1, "trigger_delay_max_ms": 100},
    {"trigger_delay_min_ms": 300, "trigger_delay_max_ms": 100},
    {"trigger_delay_min_ms": "slow", "trigger_delay_max_ms": 100},
    {"trigger_delay_min_ms": True, "trigger_delay_max_ms": 100},
    {"trigger_delay_min_ms": 0, "trigger_delay_max_ms": float("inf")},
    {"trigger_delay_min_ms": float("nan"), "trigger_delay_max_ms": 100},
])
def test_load_config_resets_invalid_trigger_delay_pair_to_defaults(kc, bad):
    # Both values feed time.sleep(random.uniform(min, max)) on the worker thread -
    # a NaN/inf/negative there raises and silently kills detection, so a bad pair
    # falls back to "no delay" rather than being trusted.
    kc.save_config(bad)
    cfg = kc.load_config()
    assert cfg["trigger_delay_min_ms"] == 0
    assert cfg["trigger_delay_max_ms"] == 0


@pytest.mark.parametrize("bad", [
    {"min_delay_ms": float("nan"), "max_delay_ms": 150},
    {"min_delay_ms": 50, "max_delay_ms": float("inf")},
    {"min_delay_ms": True, "max_delay_ms": 150},
    {"min_delay_ms": 0, "max_delay_ms": 1e300},  # finite, but overflows time.sleep
])
def test_load_config_resets_non_finite_or_absurd_click_delays(kc, bad):
    kc.save_config(bad)
    cfg = kc.load_config()
    assert cfg["min_delay_ms"] == kc.DEFAULT_CONFIG["min_delay_ms"]
    assert cfg["max_delay_ms"] == kc.DEFAULT_CONFIG["max_delay_ms"]


def test_load_config_keeps_a_long_generic_click_interval(kc):
    # e.g. an anti-idle click every ~4-5 minutes is a legitimate Generic-mode setup.
    kc.save_config({"min_delay_ms": 240000, "max_delay_ms": 300000})
    cfg = kc.load_config()
    assert (cfg["min_delay_ms"], cfg["max_delay_ms"]) == (240000, 300000)


OWNER_LIKE_CONFIG = (
    '{"detection_method": "color", "target_color": [102, 46, 143], '
    '"min_color_pixels": 7175, "scan_scope": "window", "scan_window_title": "RuneLite - ItzKryptik"}'
)


def _backups(kc):
    folder = os.path.dirname(kc.CONFIG_PATH)
    name = os.path.basename(kc.CONFIG_PATH)
    return [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith(name + ".unreadable")]


@pytest.mark.parametrize("broken", [
    OWNER_LIKE_CONFIG[:-1] + ',}',  # one stray comma from a hand edit
    OWNER_LIKE_CONFIG[:40],         # truncated mid-write
    "null",
    "42",
    "[1, 2]",
])
def test_unreadable_config_is_set_aside_with_a_warning_not_silently_lost(kc, broken):
    # It used to fall back to defaults silently - and the GUI saves on startup, so the
    # user's calibration was overwritten for good. Keep a copy and say what happened.
    with open(kc.CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(broken)
    warnings = []

    cfg = kc.load_config(on_warning=warnings.append)

    assert cfg["detection_method"] == kc.DEFAULT_CONFIG["detection_method"]
    backups = _backups(kc)
    assert len(backups) == 1
    with open(backups[0], encoding="utf-8") as f:
        assert f.read() == broken
    assert warnings and os.path.basename(backups[0]) in warnings[0]


def test_config_saved_with_a_utf8_bom_loads(kc):
    # PowerShell 5.1's Set-Content -Encoding utf8 / Out-File write a BOM.
    with open(kc.CONFIG_PATH, "w", encoding="utf-8-sig") as f:
        f.write(OWNER_LIKE_CONFIG)
    cfg = kc.load_config()
    assert cfg["target_color"] == [102, 46, 143]
    assert _backups(kc) == []


def test_config_written_by_older_versions_in_the_locale_encoding_still_loads(kc):
    import locale

    legacy = '{"scan_window_title": "RuneLite - José"}'.encode(locale.getpreferredencoding(False))
    with open(kc.CONFIG_PATH, "wb") as f:
        f.write(legacy)
    cfg = kc.load_config()
    assert cfg["scan_window_title"] == "RuneLite - José"


def test_non_ascii_window_titles_round_trip_through_the_config_file(kc):
    kc.save_config({"scan_window_title": "RuneLite - José"})
    with open(kc.CONFIG_PATH, "rb") as f:
        f.read().decode("utf-8")  # readable by any tool, whatever the Windows locale
    assert kc.load_config()["scan_window_title"] == "RuneLite - José"


def test_a_save_that_dies_midway_leaves_the_previous_config_intact(kc, monkeypatch):
    # open(path, "w") truncates immediately, so a crash/kill during json.dump used to
    # leave a half-written (or empty) config behind.
    kc.save_config({"target_color": [102, 46, 143], "min_color_pixels": 7175})

    def dying_dump(obj, f, **kwargs):
        f.write('{"target_col')
        raise OSError("process killed mid-write")

    # A nested context, NOT monkeypatch.undo(): that would also undo the kc fixture's
    # redirect of CONFIG_PATH and point the rest of the test at the real config file.
    with monkeypatch.context() as m:
        m.setattr(kc.json, "dump", dying_dump)
        with pytest.raises(OSError):
            kc.save_config({"target_color": [1, 2, 3]})

    assert kc.load_config()["target_color"] == [102, 46, 143]
    assert not os.path.exists(kc.CONFIG_PATH + ".tmp")


def test_save_retries_when_the_file_is_briefly_locked(kc, monkeypatch):
    # On Windows an antivirus/indexer can hold the file for a moment, making the
    # swap-in fail with PermissionError.
    real_replace = os.replace
    attempts = []

    def locked_once(src, dst):
        attempts.append(dst)
        if len(attempts) == 1:
            raise PermissionError("in use by another process")
        return real_replace(src, dst)

    with monkeypatch.context() as m:
        m.setattr(kc.os, "replace", locked_once)
        kc.save_config({"min_color_pixels": 42})

    assert kc.load_config()["min_color_pixels"] == 42
    assert len(attempts) == 2
