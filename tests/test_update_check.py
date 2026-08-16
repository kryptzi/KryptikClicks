import pytest


def test_parse_version_handles_v_prefix(kc):
    assert kc.parse_version("v1.3.4") == (1, 3, 4)


def test_parse_version_handles_no_prefix(kc):
    assert kc.parse_version("1.3.4") == (1, 3, 4)


def test_is_newer_version_true_when_remote_is_greater(kc):
    assert kc.is_newer_version("v1.3.5", "1.3.4") is True


def test_is_newer_version_false_when_equal(kc):
    assert kc.is_newer_version("v1.3.4", "1.3.4") is False


def test_is_newer_version_false_when_remote_is_older(kc):
    assert kc.is_newer_version("v1.2.9", "1.3.4") is False


def test_is_newer_version_handles_minor_version_bump_correctly(kc):
    # A naive string comparison would get this wrong ("1.10.0" < "1.9.0" as strings).
    assert kc.is_newer_version("v1.10.0", "1.9.0") is True


def test_find_update_returns_none_when_no_tag_name(kc):
    assert kc.find_update({}, "1.3.4") is None


def test_find_update_returns_none_when_remote_is_not_newer(kc):
    release = {"tag_name": "v1.3.4", "assets": [{"name": "KryptikClicks.exe", "browser_download_url": "x"}]}
    assert kc.find_update(release, "1.3.4") is None


def test_find_update_returns_none_when_newer_but_no_exe_asset(kc):
    release = {"tag_name": "v1.3.5", "assets": [{"name": "source.zip", "browser_download_url": "x"}]}
    assert kc.find_update(release, "1.3.4") is None


def test_find_update_returns_update_info_when_newer_with_exe_asset(kc):
    release = {
        "tag_name": "v1.3.5",
        "body": "release notes here",
        "assets": [{"name": "KryptikClicks.exe", "browser_download_url": "https://example/KryptikClicks.exe"}],
    }
    result = kc.find_update(release, "1.3.4")
    assert result == {
        "version": "v1.3.5",
        "download_url": "https://example/KryptikClicks.exe",
        "notes": "release notes here",
    }


def test_check_for_update_returns_none_when_fetch_fails(kc):
    assert kc.check_for_update("1.3.4", fetcher=lambda: None) is None


def test_check_for_update_returns_update_info_when_fetch_succeeds_with_newer_release(kc):
    release = {
        "tag_name": "v1.3.5",
        "body": "notes",
        "assets": [{"name": "KryptikClicks.exe", "browser_download_url": "https://example/KryptikClicks.exe"}],
    }
    result = kc.check_for_update("1.3.4", fetcher=lambda: release)
    assert result["version"] == "v1.3.5"
