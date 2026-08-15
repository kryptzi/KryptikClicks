# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/kryptzi/KryptikClicks/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kryptzi/KryptikClicks/releases/tag/v1.0.0
