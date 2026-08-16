def test_find_window_by_title_returns_matching_hwnd(kc):
    windows = [(111, "Discord"), (222, "RuneLite - Zezima")]
    assert kc.find_window_by_title(windows, "RuneLite - Zezima") == 222


def test_find_window_by_title_returns_none_when_not_found(kc):
    windows = [(111, "Discord"), (222, "RuneLite - Zezima")]
    assert kc.find_window_by_title(windows, "Notepad") is None


def test_find_window_by_title_returns_none_for_empty_list(kc):
    assert kc.find_window_by_title([], "Discord") is None


def test_find_window_by_title_is_exact_not_substring(kc):
    windows = [(111, "RuneLite - Zezima (extra text)")]
    assert kc.find_window_by_title(windows, "RuneLite - Zezima") is None


def test_find_window_by_title_returns_first_match_when_duplicated(kc):
    windows = [(111, "Chrome"), (222, "Chrome")]
    assert kc.find_window_by_title(windows, "Chrome") == 111
