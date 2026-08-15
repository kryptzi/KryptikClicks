<p align="center">
  <img src="assets/logo.png" alt="KryptikClicks" width="360">
</p>

A lightweight Windows tool with two modes: **Targeted**, which watches your
screen for a trigger you capture (any bit of text, an icon, a button —
anywhere on screen) and clicks a spot for as long as that trigger stays
visible; and **Generic**, a classic fixed-interval autoclicker with no
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

**Targeted mode** (default):
1. Open KryptikClicks, select **Targeted** under Mode, then choose a click
   position: a **fixed point** (captured below) or your **current cursor
   position**. With cursor position selected, it still watches for the
   trigger as normal — it just clicks wherever your mouse already is instead
   of jumping it to a captured point.
2. Click **Capture Template + Click Target...** (this reads just **Capture
   Template...** if you chose cursor position, since no click point needs to
   be captured). Your screen freezes into a snapshot. Drag a tight box
   around the trigger you want it to watch for (e.g. just the fixed part of
   some text — the trigger image should look the same every time it
   appears).
3. If you chose a fixed point, click once more on the spot you want it to
   click when the trigger shows up. If you chose cursor position, capture
   ends right there — there's no second step.
4. Press **Start (F6)**. It'll click — the captured spot, or your live
   cursor position if you chose that — with a randomized delay between
   clicks, for as long as the trigger stays visible, and stop automatically
   when it disappears.

**Generic mode:**
1. Select **Generic** under Mode, then choose a click position: a **fixed
   point** (captured the same way as above) or your **current cursor
   position**.
2. Press **Start (F6)** — it clicks immediately on interval, no trigger
   needed, until you pause it or it hits the repeat limit.

**Hotkeys** (global — work even while another window has focus):
- `F6` — toggle scanning/clicking on and off
- `F9` — quit

**Settings** (hover any label in the app for details):
- **Min/Max delay (ms)** — the random delay range between clicks while it's
  actively clicking.
- **Match threshold (0-1)** — Targeted mode only. How closely the screen must
  match your captured trigger image to fire clicking. Higher = stricter/fewer
  false triggers; lower = more lenient but may misfire. `0.85` is a good
  default.
- **Click position** — a fixed captured point, or your current cursor
  position. Available in both modes: in Targeted mode with cursor position
  selected, it still watches for the trigger as normal, it just clicks
  wherever the mouse already is instead of jumping it to a captured point.
- **Click button** — left, right, or middle mouse button.
- **Repeat limit (0 = infinite)** — automatically pause after this many
  clicks.
- **Sound alert** — plays a short beep when it starts clicking.

Your capture and settings are saved automatically and reloaded next time you
open the app — you only need to capture once, unless you want to change what
it's watching for (use **Recapture...**).

## Building the standalone .exe

```
pip install pyinstaller
pyinstaller --onefile --windowed --name KryptikClicks --icon=assets/icon.ico --add-data "assets;assets" KryptikClicks.py
```

The built exe will be in `dist/KryptikClicks.exe`.

## Running the tests

```
pip install pytest
pytest
```

## Versioning

This project follows [Semantic Versioning](https://semver.org/) and keeps a
[CHANGELOG.md](CHANGELOG.md) ([Keep a Changelog](https://keepachangelog.com/)
format). The in-app version is a single `__version__` constant at the top of
`KryptikClicks.py`.

## License

MIT — see [LICENSE](LICENSE).
