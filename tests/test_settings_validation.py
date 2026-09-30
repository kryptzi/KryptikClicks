import pytest


def test_valid_input_returns_parsed_values(kc):
    result = kc.parse_settings_input("50", "150", "0.85", "0")
    assert result == {
        "min_delay_ms": 50.0, "max_delay_ms": 150.0, "match_threshold": 0.85, "click_limit": 0,
        "trigger_delay_min_ms": 0.0, "trigger_delay_max_ms": 0.0, "reclick_wait_ms": 2000.0,
    }


def test_rejects_min_greater_than_max(kc):
    with pytest.raises(ValueError):
        kc.parse_settings_input("200", "100", "0.85", "0")


def test_rejects_negative_min_delay(kc):
    with pytest.raises(ValueError):
        kc.parse_settings_input("-10", "100", "0.85", "0")


def test_rejects_threshold_out_of_range(kc):
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "1.5", "0")
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "0", "0")


def test_rejects_negative_click_limit(kc):
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "0.85", "-3")


def test_accepts_positive_click_limit(kc):
    result = kc.parse_settings_input("50", "150", "0.85", "10")
    assert result["click_limit"] == 10


def test_rejects_non_numeric_input(kc):
    with pytest.raises(ValueError):
        kc.parse_settings_input("abc", "150", "0.85", "0")


def test_parses_trigger_delay_range(kc):
    result = kc.parse_settings_input("50", "150", "0.85", "0", trigger_min_str="200", trigger_max_str="450")
    assert result["trigger_delay_min_ms"] == 200.0
    assert result["trigger_delay_max_ms"] == 450.0


def test_trigger_delay_min_equal_to_max_is_a_fixed_delay(kc):
    result = kc.parse_settings_input("50", "150", "0.85", "0", trigger_min_str="300", trigger_max_str="300")
    assert result["trigger_delay_min_ms"] == result["trigger_delay_max_ms"] == 300.0


@pytest.mark.parametrize("trigger_min, trigger_max", [
    ("500", "100"),   # min > max
    ("-5", "100"),    # negative
    ("soon", "100"),  # non-numeric
    ("nan", "100"),   # float() accepts these, time.sleep() doesn't
    ("0", "inf"),
])
def test_rejects_invalid_trigger_delay(kc, trigger_min, trigger_max):
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "0.85", "0", trigger_min_str=trigger_min, trigger_max_str=trigger_max)


@pytest.mark.parametrize("min_ms, max_ms", [
    ("nan", "150"),
    ("50", "inf"),
    ("50", "1e400"),   # float() turns this into inf
    ("0", "1e300"),    # finite, but overflows time.sleep
])
def test_rejects_non_finite_or_absurd_click_delays(kc, min_ms, max_ms):
    with pytest.raises(ValueError):
        kc.parse_settings_input(min_ms, max_ms, "0.85", "0")


@pytest.mark.parametrize("limit", ["inf", "nan", "1e400"])
def test_rejects_non_finite_click_limit_with_a_friendly_error(kc, limit):
    # int(float("inf")) raises OverflowError, not ValueError - that escaped as a raw
    # "OverflowError: cannot convert float infinity to integer" dialog.
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "0.85", limit)


def test_rejects_absurd_trigger_delay(kc):
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "0.85", "0", trigger_min_str="0", trigger_max_str="1e300")


def test_parses_the_reclick_wait(kc):
    result = kc.parse_settings_input("50", "150", "0.85", "0", reclick_wait_str="700")
    assert result["reclick_wait_ms"] == 700.0


@pytest.mark.parametrize("bad", ["-5", "nan", "inf", "soon"])
def test_rejects_an_invalid_reclick_wait(kc, bad):
    with pytest.raises(ValueError):
        kc.parse_settings_input("50", "150", "0.85", "0", reclick_wait_str=bad)
