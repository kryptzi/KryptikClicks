# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/kryptzi/KryptikClicks/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/kryptzi/KryptikClicks/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kryptzi/KryptikClicks/releases/tag/v1.0.0
