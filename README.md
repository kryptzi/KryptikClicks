# KryptikClicks

A lightweight Windows tool that watches your screen for a trigger you capture
(any bit of text, an icon, a button — anywhere on screen) and automatically
clicks a spot you choose for as long as that trigger stays visible, waiting a
randomized delay between clicks.

Useful for things like: a game notification/button that needs clicking
whenever it pops up, a repetitive confirm dialog, or any other "click this
spot every time that appears" task.

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
```

## Usage

1. Open KryptikClicks and click **Capture Template + Click Target...**
2. Your screen freezes into a snapshot. Drag a tight box around the trigger
   you want it to watch for (e.g. just the fixed part of some text — the
   trigger image should look the same every time it appears).
3. Click once more on the spot you want it to click when the trigger shows up.
4. Press **Start (F6)** (or click Start). It'll click that spot, with a
   randomized delay between clicks, for as long as the trigger stays visible,
   and stop automatically when it disappears.

**Hotkeys** (global — work even while another window has focus):
- `F6` — toggle scanning/clicking on and off
- `F9` — quit

**Settings** (hover any label in the app for details):
- **Min/Max delay (ms)** — the random delay range between clicks while it's
  actively clicking.
- **Match threshold (0-1)** — how closely the screen must match your captured
  trigger image to fire clicking. Higher = stricter/fewer false triggers;
  lower = more lenient but may misfire. `0.85` is a good default.

Your capture and settings are saved automatically and reloaded next time you
open the app — you only need to capture once, unless you want to change what
it's watching for (use **Recapture...**).

## Building the standalone .exe

```
pip install pyinstaller
pyinstaller --onefile --windowed --name KryptikClicks KryptikClicks.py
```

The built exe will be in `dist/KryptikClicks.exe`.

## License

MIT — see [LICENSE](LICENSE).
