# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.5.3] - 2026-08-17

### Fixed
- **Taskbar icon showed the plain Python logo instead of the app's icon when
  run from source** (`python KryptikClicks.py`, e.g. via a desktop shortcut).
  Windows groups/identifies taskbar buttons by the *hosting* process unless
  that process claims its own identity - running from source, the host is
  python.exe/pythonw.exe, so without an explicit App User Model ID the
  taskbar fell back to showing python.exe's own icon. The window's own title
  bar icon was unaffected (that's set directly, not by process identity) and
  looked correct the whole time, which made this confusing to spot. Now sets
  a distinct App User Model ID before the window is created, same fix used
  for this in other Tkinter apps.
- `assets/icon.ico` itself was also malformed independently of the above: every
  embedded resolution was non-square (e.g. "256x256" was actually 256x215),
  inherited from a source master image that wasn't square either. This is
  invalid for a Windows icon and rendered as a garbled/unrecognizable image
  in at least one shell context observed while investigating the taskbar
  issue above. Rebuilt `icon.ico` from a properly centered, square, still
  fully transparent canvas at the standard sizes (16/24/32/48/64/128/256).
  Unrelated to the transparent-background fix in v1.3.0 - that background was
  already fine here; this was a dimensions problem.
- The `iconbitmap()` call that sets the window icon silently swallowed any
  failure (`except Exception: pass`), so if it ever broke again there'd be no
  way to tell without a developer attaching a debugger. It now logs a warning
  to the Activity panel instead.
- **Picking a new scan target didn't actually take effect until Save Settings
  was clicked.** Choosing "All monitors"/"Specific window", or picking a
  window from "Choose Window...", updated the displayed selection immediately
  (looking exactly like a completed capture, which *does* take effect right
  away) but silently left the running scanner on the old scope/window until a
  separate Save Settings click. Both now commit immediately, matching the
  capture flow's existing behavior.

## [1.5.1] - 2026-08-17

### Added
- **Scan region.** When scanning a specific window, you can now further limit
  scanning to a sub-area of it via "Limit to Region..." (with a "Clear" link
  to go back to the whole window) - e.g. just the game viewport, excluding a
  sidebar or other persistent UI. Tracks the window's position live, so it
  keeps working correctly if the window moves.

### Fixed
- **Color capture could pick background instead of the trigger.** HSV
  saturation alone doesn't reliably separate foreground from background - a
  near-black pixel can have a deceptively high saturation *ratio* purely from
  being dark, without looking distinctive at all. This could make a captured
  trigger resolve to a near-black color that then matched almost an entire
  dark-themed window continuously. Capture now also requires a minimum
  brightness, not just saturation.
- **Critical: fixed-position mode could produce runaway click counts.**
  Continuous clicking while a trigger is genuinely visible is intentional,
  but there was no upper bound - combined with the false-match issue above,
  one real session produced roughly 1800 clicks. It now caps at 5 consecutive
  clicks per detection before forcing a fresh full-region re-scan, matching
  the detect → click a few times → re-verify pattern that's actually wanted.

## [1.5.0] - 2026-08-16

### Added
- **Color match detection.** A new alternative to image-template matching for
  Targeted mode: instead of correlating against a captured screenshot, it
  samples the distinctive (non-background) color from your drag-selected
  trigger and watches for enough pixels of that color to reappear. Select it
  under "Detection method" in Settings.
  - Ignores everything except the target color, so it isn't thrown off by
    background content changing behind the trigger the way template
    correlation can be - directly fixes a real case where a captured "Kuri
    Click" purple-text trigger's template match kept landing in the same
    0.5-0.6 range as an unrelated settings dropdown, making it impossible to
    pick a threshold that caught the real trigger without also matching the
    dropdown.
  - No new dependency (numpy, already used).

## [1.4.1] - 2026-08-15

### Fixed
- **Critical: cursor-position mode could go up to 36+ seconds without
  re-clicking during real use.** After clicking once, it waits for the
  local area around the trigger to read as "gone" before it's willing to
  click again - but ambient content near the trigger (not the trigger
  itself) can keep that local check reading as a match well after the real
  trigger is gone, so the wait had no upper bound. It now gives up waiting
  after 2 seconds and clicks again regardless, rather than potentially
  never re-clicking at all.

## [1.4.0] - 2026-08-15

### Added
- **Window-scoped scanning.** Targeted mode can now watch a single specific
  window instead of every monitor - pick it from a Discord-style picker
  (live thumbnail previews of every open window) under Settings > Scan area
  > Specific window. This scans only that window's bounds, eliminating
  false positives from unrelated content on other monitors entirely (rather
  than just picking the best of them, as of 1.3.4), and it's faster since
  there's far less area to check.
  - Tracks the window by title, re-resolving it live each scan (not a fixed
    handle), so it keeps working if the target app is closed and reopened.
  - If the window is minimized or closed while scanning, it idles with a
    status message and resumes automatically the moment it's back - no need
    to pause/restart manually.
  - "All monitors" (the previous behavior) is still the default.

## [1.3.5] - 2026-08-15

### Added
- **Update checking.** KryptikClicks now checks GitHub for newer releases -
  automatically on launch (toggle via "Check for updates automatically" in
  Settings, on by default) and on demand via the "Check for Updates" link at
  the bottom of the window. When a newer version is found, it shows what
  changed and offers to open the download page in your browser. Running from
  source (not the built exe) shows a reminder to `git pull` instead.
  - Deliberately does **not** auto-download and self-install: an early version
    of this feature downloaded the new exe and swapped it in automatically,
    but Windows Defender's behavior monitoring blocked it outright (a program
    downloading and replacing its own exe via a hidden helper script looks
    identical to malware self-updating, regardless of intent). Opening the
    official GitHub release page for a normal browser download avoids that
    entirely.

## [1.3.4] - 2026-08-15

### Fixed
- **Regression from 1.3.3:** the new per-monitor parallel scan picked whichever
  monitor's scan thread finished first, not whichever actually had the
  strongest match. Ordinary desktop content on an unrelated monitor (icons,
  taskbar, wallpaper) can score close enough to a real match to clear a
  normal threshold, so a false positive on the wrong monitor could beat the
  real detection to the finish line - making it seem like detection wasn't
  working at all, even at a very low match threshold. It now waits for every
  monitor's scan and picks the single best-scoring match across all of them,
  instead of racing.

## [1.3.3] - 2026-08-15

### Changed
- Detection latency reduced sharply on multi-monitor setups: the app used to
  scan one region spanning the entire multi-monitor desktop for the trigger,
  which took 350-450ms per scan on a 3-monitor desktop — long enough that a
  trigger that only flashes on screen briefly could be missed entirely, or
  detected so late the click landed well after it appeared. It now scans each
  physical monitor in parallel instead, cutting that down to roughly the cost
  of scanning the single slowest monitor (~130-140ms measured on a 3-monitor
  desktop) rather than the sum of all of them. The idle poll interval between
  scans was also lowered (80ms to 20ms) now that it's no longer the dominant
  source of delay.

## [1.3.2] - 2026-08-15

### Changed
- Default match threshold lowered from 0.85 to 0.50. 0.85 was too strict for
  most captured triggers in practice and commonly resulted in the app never
  detecting anything until the user manually lowered it.

### Fixed
- In Targeted mode with cursor-position clicking, once the trigger was
  detected it kept re-clicking every cycle for as long as the trigger stayed
  on screen. This is correct when clicking the fixed target point (the click
  itself usually makes the trigger go away), but cursor-position mode clicks
  wherever the mouse already is, not on the trigger — so a trigger that isn't
  removed by clicking caused runaway spam-clicking. It now clicks once per
  detection, then waits for the trigger to actually disappear before it's
  eligible to trigger another click.

## [1.3.1] - 2026-08-15

### Fixed
- On multi-monitor setups, the capture overlay (drag-select the trigger,
  pick a click point) was a single window sized to span every monitor at
  once. Windows' compositor silently failed to actually paint a window that
  large, leaving it reachable only on whichever monitor a small leftover
  sliver happened to land on — forcing you to drag other windows onto that
  specific screen just to use it. Replaced with one normal-sized overlay
  window per physical monitor, so capture now works starting from whichever
  screen your mouse is already on.

## [1.3.0] - 2026-08-15

### Changed
- **Targeted mode** now supports the same click-position choice as Generic
  mode: a fixed captured point, or the current cursor position. With cursor
  position selected, Targeted mode still watches for the trigger as normal,
  but clicks wherever the mouse already is instead of jumping it to a
  captured point.
- The capture flow (drag-select the trigger, then click a target point) now
  skips the second step entirely when cursor position is selected, since no
  click point needs to be captured.
- Deduplicated the hotkey debounce/dispatch logic (previously implemented
  separately in the GUI and headless mode) into a single `HotkeyListener`.

### Fixed
- Captured click points were stored as canvas-relative pixels with no
  correction for mss's virtual-desktop origin, so on multi-monitor setups
  where a display sits left of/above the primary, clicks landed offset from
  the intended target.
- `Detector.load()` silently left the trigger template unset if the PNG was
  corrupted/unreadable, instead of logging a warning like the parallel
  click-target handling already did.
- A second unguarded `pyautogui` call (`pyautogui.position()`, used by
  cursor-position mode) could silently kill the background scan/click thread
  the same way an earlier unguarded `pyautogui.click()` call once did.
- `load_config()` didn't validate `min_delay_ms`/`max_delay_ms`/
  `match_threshold`, so a hand-edited or corrupted config with non-numeric
  values there would crash the background thread.
- The app icon, in-app emblem, and README banner had an opaque dark
  background baked in (from the source art's checkered placeholder) instead
  of a transparent one, so the taskbar/title-bar icon showed as a solid
  square instead of blending in. Rebuilt all three with a real transparent
  background.

## [1.2.0] - 2026-08-15

### Added
- **Generic click mode**: a classic fixed-interval autoclicker requiring no
  trigger image, selectable alongside the existing Targeted mode. Choose to
  click a fixed captured point or the current cursor position.
- **Repeat limit** setting — automatically pause after a configured number of
  clicks (0 = infinite, the previous behavior).
- **Sound alert** setting — plays a short beep when it starts clicking.
- Live click counter shown in the status line while scanning.
- App icon and in-app emblem/branding.
- `--version` CLI flag; in-app version footer.
- Automated test suite (pytest) covering the detection/click/config logic.

### Changed
- Settings save/validation now goes through a single, tested
  `parse_settings_input` function.

## [1.1.0] - 2026-08-15

### Fixed
- Pillow was silently required by the capture flow but missing from the
  dependency check/requirements — now checked properly.
- `Detector.load()` no longer crashes on a corrupted `click_target.txt`.
- The local re-scan region could be smaller than the template near screen
  edges/corners, which crashed `cv2.matchTemplate`; now clamped.
- The scan/click loop is now wrapped in error handling so a transient
  capture/click error logs and continues instead of silently killing
  background detection.
- Unexpected GUI errors now show a message box instead of vanishing into
  stderr, which is invisible in the `--windowed` exe build.

### Added
- Click-button setting (left/right/middle).

## [1.0.0] - 2026-08-14

### Added
- Initial release: Targeted-mode screen-trigger autoclicker with a
  dark-themed settings GUI, global F6/F9 hotkeys, randomized click delay,
  and a standalone Windows exe build.

[Unreleased]: https://github.com/kryptzi/KryptikClicks/compare/v1.5.3...HEAD
[1.5.3]: https://github.com/kryptzi/KryptikClicks/compare/v1.5.1...v1.5.3
[1.5.1]: https://github.com/kryptzi/KryptikClicks/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/kryptzi/KryptikClicks/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.5...v1.4.0
[1.3.5]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.4...v1.3.5
[1.3.4]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.3...v1.3.4
[1.3.3]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kryptzi/KryptikClicks/releases/tag/v1.0.0
