<p align="center">
  <img src="assets/logo.png" alt="KryptikClicks" width="360">
</p>

A lightweight Windows tool with two modes: **Targeted**, which watches your
screen for a trigger you capture (any bit of text, an icon, a button, or just
a distinctive color — anywhere on screen or in one window) and clicks when it
shows up; and **Generic**, a classic fixed-interval autoclicker with no
trigger needed at all. Both click with a randomized delay between clicks.

Useful for things like: a game notification/button that needs clicking
whenever it pops up, a repetitive confirm dialog, plain repetitive clicking
tasks, or any other "click this spot every time X happens" job.

## Download (no Python required)

Grab the latest `KryptikClicks.exe` from the [Releases](../../releases) page
and run it. No installation, no Python needed.

> **Note on antivirus:** Because this tool does global keyboard-hotkey
> listening and automated clicking, Windows Defender or other antivirus may
> flag it as suspicious (a common false positive for this category of tool).
> If that happens, you'll need to allow it through / add an exclusion.

## Running from source

```
pip install -r requirements.txt
python KryptikClicks.py             # opens the settings window
python KryptikClicks.py --capture   # capture trigger + click target from a terminal, no GUI
python KryptikClicks.py --headless  # run the watcher from a terminal, no GUI
python KryptikClicks.py --version   # print the version and exit
```

## Usage

The window has two tabs. **Simple** has everything needed for the common case
(mode, click position, capture, Start/Quit) plus a one-line summary of exactly
what it's currently set up to do. **Advanced** has detection, scan area and
timing settings.

**Targeted mode** (default):
1. Select **Targeted** under Mode, then choose a click position: a **fixed
   point** (captured below) or your **current cursor position**. With cursor
   position selected, it still watches for the trigger as normal — it just
   clicks wherever your mouse already is instead of jumping it to a captured
   point.
2. Click **Capture Trigger + Click Target...** (just **Capture Trigger...**
   with cursor position, since no click point is needed). Your screen freezes
   into a snapshot. Drag a tight box around the trigger you want it to watch
   for (e.g. just the fixed part of some text — it should look the same every
   time it appears).
3. With a fixed point, click once more on the spot you want it to click when
   the trigger shows up. With cursor position, capture ends right there.
4. Press **Start (F6)**. Nothing is clicked for the first 0.75s, so you can
   move the mouse off the Start button. Then:
   - **Fixed point:** it clicks the captured spot, with a randomized delay
     between clicks, for as long as the trigger stays visible (re-checking
     with a full scan every 5 clicks), and stops when it disappears.
   - **Cursor position:** it clicks once each time the trigger appears, then
     waits for it to go away before treating the next sighting as new. If it
     is still there after 2 seconds, it clicks again.

**Generic mode:**
1. Select **Generic** under Mode, then choose a click position: a **fixed
   point** (use **Capture Click Target...** — just click the spot; your saved
   Targeted trigger is left alone) or your **current cursor position**.
2. Press **Start (F6)** — it clicks on the interval, no trigger needed, until
   you pause it or it hits the repeat limit.

**Hotkeys** (global — work even while another window has focus):
- `F6` — toggle scanning/clicking on and off
- `F9` — quit

**Advanced tab** (hover any setting label in the app for details):
- **Detection method** — **Image template match** looks for the picture you
  captured; **Color match** learns the distinctive color inside your capture
  box and fires when enough pixels of that color appear (at least half as
  many as were in the capture). Color match ignores whatever is behind the
  trigger, so it's the better choice for colored text over a changing
  background. How close a pixel must be to count is `color_tolerance` in the
  settings file (default `20` per RGB channel); recapture after changing it.
- **Scan area** — **All monitors**, or a **Specific window** picked from live
  previews (**Choose Window...**). A chosen window is tracked by its title, so
  it keeps working if the window moves or the app is restarted, and scanning
  just waits while it's minimized or closed. **Limit to Region...** narrows
  that to part of the window (e.g. just a game's viewport).
- **Min/Max delay (ms)** — the random delay range between clicks while it's
  actively clicking.
- **Trigger delay min/max (ms)** — Targeted mode only. How long to wait after
  the trigger first appears before the first click (a random time in that
  range, or set both the same for a fixed delay). It only clicks if the
  trigger stays up for the whole wait; one that goes away and comes back
  starts a new wait. `0`/`0` (the default) clicks immediately.
- **Match threshold (0-1)** — Image template match only. How closely the
  screen must match your captured picture to fire clicking. Higher =
  stricter/fewer false triggers; lower = more lenient but may misfire. `0.50`
  is the default; raise it if it fires on the wrong thing, lower it if it
  doesn't fire at all.
- **Click button** — left, right, or middle mouse button.
- **Repeat limit (0 = infinite)** — automatically pause after this many
  clicks.
- **Sound alert** — plays a short beep when it starts clicking.
- **Check for updates automatically** — the `.exe` checks GitHub for a newer
  release on launch and offers to open the download page (it never installs
  anything itself).

Mode, click position, detection method and scan area apply the moment you
change them. The numeric settings, click button and checkboxes in the
**Settings** section apply when you press **Save Settings**.

Your capture and settings are saved automatically and reloaded next time you
open the app — you only need to capture once, unless you want to change what
it's watching for (use **Recapture...**). They live next to `KryptikClicks.py`
when you run from source, and in `%APPDATA%\KryptikClicks` for the `.exe`.

## Building the standalone .exe

```
pip install pyinstaller==6.22.1
pyinstaller --onefile --windowed --name KryptikClicks --icon=assets/icon.ico --add-data "assets;assets" KryptikClicks.py
```

The built exe will be in `dist/KryptikClicks.exe`.

## Running the tests

```
pip install pytest==9.1.1
pytest
```

## Versioning

This project follows [Semantic Versioning](https://semver.org/) and keeps a
[CHANGELOG.md](CHANGELOG.md) ([Keep a Changelog](https://keepachangelog.com/)
format). The in-app version is a single `__version__` constant at the top of
`KryptikClicks.py`.

## License

MIT — see [LICENSE](LICENSE).
