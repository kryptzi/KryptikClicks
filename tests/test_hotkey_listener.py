def test_press_dispatches_the_mapped_action(kc):
    calls = []
    listener = kc.HotkeyListener({"A": lambda: calls.append("a")})

    listener.on_press("A")

    assert calls == ["a"]


def test_held_key_does_not_refire_without_a_release(kc):
    calls = []
    listener = kc.HotkeyListener({"A": lambda: calls.append("a")})

    listener.on_press("A")
    listener.on_press("A")
    listener.on_press("A")

    assert calls == ["a"]


def test_release_then_press_fires_again(kc, monkeypatch):
    calls = []
    listener = kc.HotkeyListener({"A": lambda: calls.append("a")})

    # Advance monotonic time past the debounce window between presses so the
    # second press isn't swallowed by the debounce (as opposed to the held-key guard).
    # Start well above 0 - `_last_fired` defaults missing keys to 0, and a first
    # press at t=0.0 would otherwise look like it's within the debounce window.
    times = iter([100.0, 110.0])
    monkeypatch.setattr(kc.time, "monotonic", lambda: next(times))

    listener.on_press("A")
    listener.on_release("A")
    listener.on_press("A")

    assert calls == ["a", "a"]


def test_unmapped_key_does_nothing(kc):
    calls = []
    listener = kc.HotkeyListener({"A": lambda: calls.append("a")})

    listener.on_press("B")

    assert calls == []


def test_debounce_blocks_a_rapid_press_after_release(kc, monkeypatch):
    calls = []
    listener = kc.HotkeyListener({"A": lambda: calls.append("a")})

    times = iter([100.0, 100.1])
    monkeypatch.setattr(kc.time, "monotonic", lambda: next(times))

    listener.on_press("A")
    listener.on_release("A")
    listener.on_press("A")  # within the 0.3s debounce window - should be swallowed

    assert calls == ["a"]


def test_dispatch_callable_is_used_instead_of_calling_the_action_directly(kc):
    calls = []
    dispatched = []
    action = lambda: calls.append("a")
    listener = kc.HotkeyListener({"A": action}, dispatch=lambda act: dispatched.append(act))

    listener.on_press("A")

    assert dispatched == [action]
    assert calls == []
