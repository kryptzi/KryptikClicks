import pytest


def test_valid_input_returns_parsed_values(kc):
    result = kc.parse_settings_input("50", "150", "0.85", "0")
    assert result == {"min_delay_ms": 50.0, "max_delay_ms": 150.0, "match_threshold": 0.85, "click_limit": 0}


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
