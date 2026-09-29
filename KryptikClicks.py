"""
KryptikClicks
-----------------------
Targeted mode watches the screen (every monitor, or one window) for a trigger
you capture - found by image template matching or by its distinctive color -
and clicks when it appears: a fixed point chosen during capture, or wherever
the mouse already is, after an optional randomized trigger delay. Generic mode
is a plain interval autoclicker. Clicks use a randomized delay between them.

Setup:
    pip install -r requirements.txt

Usage:
    python KryptikClicks.py             # open the settings window (default)
    python KryptikClicks.py --capture   # capture the template/target from a terminal, no GUI
    python KryptikClicks.py --headless  # run the watcher from a terminal, no GUI
    python KryptikClicks.py --version   # print the version and exit

Hotkeys (global, work even without the window focused):
    F6  - toggle scanning/clicking on and off
    F9  - quit
"""

import sys
import os
import json
import math
import queue
import random
import threading
import time
import argparse

__version__ = "1.6.2"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """Resolves a bundled asset path, working both from source and from a
    PyInstaller --onefile exe (where bundled data is extracted to sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", SCRIPT_DIR)
    return os.path.join(base, *parts)


def user_data_dir():
    """Where captures and settings are kept. Run from source, that's next to the
    script, as it always has been. A --onefile exe runs from a temporary _MEI folder
    (which __file__ points into) that's deleted on exit, so the exe keeps them in
    %APPDATA%\\KryptikClicks instead - or next to the exe if that can't be created."""
    if not getattr(sys, "frozen", False):
        return SCRIPT_DIR
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return exe_dir
    path = os.path.join(appdata, "KryptikClicks")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return exe_dir
    return path


DATA_DIR = user_data_dir()
TEMPLATE_PATH = os.path.join(DATA_DIR, "trigger_template.png")
TARGET_PATH = os.path.join(DATA_DIR, "click_target.txt")
CONFIG_PATH = os.path.join(DATA_DIR, "kryptikclicks_config.json")

# --- Defaults (overridden by kryptikclicks_config.json / the settings window) -----
DEFAULT_CONFIG = {
    "min_delay_ms": 50,
    "max_delay_ms": 150,
    "trigger_delay_min_ms": 0,
    "trigger_delay_max_ms": 0,
    "match_threshold": 0.50,
    "click_button": "left",
    "click_mode": "targeted",
    "click_position": "fixed",
    "click_limit": 0,
    "sound_enabled": False,
    "auto_update_check": True,
    "scan_scope": "all_monitors",
    "scan_window_title": "",
    "detection_method": "template",
    "target_color": None,
    "color_tolerance": 20,
    "min_color_pixels": 0,
    "scan_region": None,
}
CLICK_BUTTONS = ["left", "right", "middle"]
CLICK_MODES = ["targeted", "generic"]
CLICK_POSITIONS = ["fixed", "cursor"]
SCAN_SCOPES = ["all_monitors", "window"]
DETECTION_METHODS = ["template", "color"]
COLOR_SATURATION_MIN = 60   # HSV saturation floor for "this pixel is the trigger color, not background"
COLOR_VALUE_MIN = 80        # HSV value(brightness) floor - a dark pixel can have a deceptively high
                             # saturation *ratio* purely from being dark, without looking "colorful" at all
COLOR_MATCH_FRACTION = 0.5  # live pixel count only needs to reach this fraction of the captured count
SCAN_INTERVAL = 0.02      # seconds between screen scans while idle/watching
MAX_DELAY_MS = 24 * 60 * 60 * 1000  # any delay setting; far past this, time.sleep() overflows
TOGGLE_HOTKEY = "f6"
QUIT_HOTKEY = "f9"
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = ["cv2", "mss", "numpy", "pyautogui", "pynput", "PIL"]
PIP_INSTALL_CMD = f'pip install -r "{os.path.join(SCRIPT_DIR, "requirements.txt")}"'


def check_dependencies():
    missing = []
    for mod in REQUIRED_PACKAGES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print("Missing required packages:", ", ".join(missing))
        print(f"Install them with:\n    {PIP_INSTALL_CMD}")
        sys.exit(1)


def read_config_file(path):
    """Parses the config file, which must hold a JSON object. The app writes plain
    ASCII, but a hand edit may not: accepts UTF-16 with a BOM (PowerShell 5.1's
    default for `>` and Out-File), UTF-8 with or without a BOM (-Encoding utf8 adds
    one), and otherwise falls back to the Windows locale encoding ("ANSI" editors).
    Raises OSError/ValueError if it can't be read."""
    # Antivirus/backup/sync tools can hold the file without read sharing for a
    # moment - retry briefly rather than treat a readable config as unreadable.
    for attempt in range(5):
        try:
            with open(path, "rb") as f:
                raw = f.read()
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")  # the BOM says which byte order
        else:
            text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        import locale

        text = raw.decode(locale.getpreferredencoding(False))
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("it doesn't contain a JSON object")
    return loaded


def set_aside_unreadable_config():
    """Copies the current config file next to itself with a timestamped name, so
    the defaults the app falls back to (and saves over it) can't destroy the
    user's settings. Returns the copy's path, or None if it couldn't be made."""
    import shutil

    backup = f"{CONFIG_PATH}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        shutil.copy2(CONFIG_PATH, backup)
        return backup
    except OSError:
        return None


# True while the config file on disk could be neither read nor copied aside: then
# save_config leaves it alone, rather than replace settings nobody has a copy of
# with the defaults the app fell back to.
_config_write_blocked = False


def load_config(on_warning=None):
    """Loads and validates the config file over DEFAULT_CONFIG. If the file exists
    but can't be read, it's set aside and on_warning(message) is told why."""
    global _config_write_blocked
    cfg = dict(DEFAULT_CONFIG)
    _config_write_blocked = False
    if os.path.exists(CONFIG_PATH):
        try:
            cfg.update(read_config_file(CONFIG_PATH))
        except (OSError, ValueError) as e:
            backup = set_aside_unreadable_config()
            _config_write_blocked = backup is None
            if on_warning is not None:
                if backup:
                    kept = f"Your old file was kept as {os.path.basename(backup)}."
                else:
                    kept = ("It couldn't be copied either, so it's being left exactly as it is - "
                            "changes you make won't be saved. Restart KryptikClicks to try again.")
                on_warning(f"Couldn't read {os.path.basename(CONFIG_PATH)} ({e}), so the default "
                           f"settings are in use. {kept}")
    if cfg.get("click_button") not in CLICK_BUTTONS:
        cfg["click_button"] = DEFAULT_CONFIG["click_button"]
    if cfg.get("click_mode") not in CLICK_MODES:
        cfg["click_mode"] = DEFAULT_CONFIG["click_mode"]
    if cfg.get("click_position") not in CLICK_POSITIONS:
        cfg["click_position"] = DEFAULT_CONFIG["click_position"]
    if not is_finite_number(cfg.get("click_limit")) or cfg["click_limit"] < 0:
        cfg["click_limit"] = DEFAULT_CONFIG["click_limit"]
    if not isinstance(cfg.get("sound_enabled"), bool):
        cfg["sound_enabled"] = DEFAULT_CONFIG["sound_enabled"]
    if not isinstance(cfg.get("auto_update_check"), bool):
        cfg["auto_update_check"] = DEFAULT_CONFIG["auto_update_check"]
    if cfg.get("scan_scope") not in SCAN_SCOPES:
        cfg["scan_scope"] = DEFAULT_CONFIG["scan_scope"]
    if not isinstance(cfg.get("scan_window_title"), str):
        cfg["scan_window_title"] = DEFAULT_CONFIG["scan_window_title"]
    if cfg.get("detection_method") not in DETECTION_METHODS:
        cfg["detection_method"] = DEFAULT_CONFIG["detection_method"]
    target_color = cfg.get("target_color")
    if target_color is not None and (
        not isinstance(target_color, (list, tuple))
        or len(target_color) != 3
        or not all(is_finite_number(v) and 0 <= v <= 255 for v in target_color)
    ):
        cfg["target_color"] = DEFAULT_CONFIG["target_color"]
    # Past 255 every pixel is within tolerance of any color (clicks with no trigger).
    tolerance = cfg.get("color_tolerance")
    if not is_finite_number(tolerance) or not 0 <= tolerance <= 255:
        cfg["color_tolerance"] = DEFAULT_CONFIG["color_tolerance"]
    if not is_finite_number(cfg.get("min_color_pixels")) or cfg["min_color_pixels"] < 0:
        cfg["min_color_pixels"] = DEFAULT_CONFIG["min_color_pixels"]
    if cfg["target_color"] is not None and cfg["min_color_pixels"] < 1:
        # A captured color is only half a calibration: with no usable pixel threshold
        # it would match anything, so treat it as not captured.
        cfg["target_color"] = None
        if on_warning is not None and cfg["detection_method"] == "color":
            on_warning("The saved color trigger has no valid pixel count - recapture it.")
    scan_region = cfg.get("scan_region")
    if scan_region is not None:
        if (
            not isinstance(scan_region, dict)
            or set(scan_region.keys()) != {"left", "top", "width", "height"}
            or not all(is_finite_number(v) for v in scan_region.values())
            or scan_region["width"] < 1
            or scan_region["height"] < 1
        ):
            cfg["scan_region"] = DEFAULT_CONFIG["scan_region"]
        else:
            # The capture library rejects float coordinates outright.
            cfg["scan_region"] = {k: int(v) for k, v in scan_region.items()}

    if not is_valid_delay_range(cfg.get("min_delay_ms"), cfg.get("max_delay_ms")):
        cfg["min_delay_ms"] = DEFAULT_CONFIG["min_delay_ms"]
        cfg["max_delay_ms"] = DEFAULT_CONFIG["max_delay_ms"]
    thr = cfg.get("match_threshold")
    if not is_finite_number(thr) or not (0.0 < thr <= 1.0):
        cfg["match_threshold"] = DEFAULT_CONFIG["match_threshold"]
    if not is_valid_delay_range(cfg.get("trigger_delay_min_ms"), cfg.get("trigger_delay_max_ms")):
        cfg["trigger_delay_min_ms"] = DEFAULT_CONFIG["trigger_delay_min_ms"]
        cfg["trigger_delay_max_ms"] = DEFAULT_CONFIG["trigger_delay_max_ms"]
    return cfg


def is_finite_number(v):
    """A real, finite number. Excludes bools (True passes isinstance(v, int)) and
    NaN/inf, which slip through naive range checks since every comparison with NaN
    is False - and json happily loads NaN/Infinity from a config file. An int too big
    to convert to float (309+ digits) counts as not finite rather than raising."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def is_valid_delay_range(min_ms, max_ms):
    """True if (min_ms, max_ms) is safe to feed time.sleep(random.uniform(...)):
    finite numbers with 0 <= min <= max <= MAX_DELAY_MS. NaN/inf would make
    time.sleep raise on the worker thread, killing detection while the UI still
    says Scanning."""
    return is_finite_number(min_ms) and is_finite_number(max_ms) and 0 <= min_ms <= max_ms <= MAX_DELAY_MS


def save_config(cfg):
    """Writes to a temp file and swaps it into place, so a crash or kill mid-write
    can't leave a truncated config behind (open("w") empties the file at once)."""
    if _config_write_blocked:
        return  # see load_config: the file on disk is the only copy of those settings
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Antivirus/indexers can hold the file for a moment on Windows, making the
        # swap fail with PermissionError - retry briefly before giving up.
        for attempt in range(5):
            try:
                os.replace(tmp, CONFIG_PATH)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/kryptzi/KryptikClicks/releases/latest"


def parse_version(v):
    """Parses a version string like 'v1.3.4' or '1.3.4' into a comparable tuple."""
    v = v.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    return tuple(int(p) for p in v.split("."))


def is_newer_version(remote, local):
    """True if `remote` version string is strictly newer than `local`."""
    return parse_version(remote) > parse_version(local)


def find_update(release, current_version):
    """Given a GitHub 'latest release' API response dict, returns
    {"version", "download_url", "notes"} if it's newer than current_version and has a
    downloadable .exe asset, else None. It's a network response, so anything not
    shaped as expected (including a tag that isn't plain X.Y.Z) counts as no update."""
    if not isinstance(release, dict):
        return None
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        return None
    try:
        if not is_newer_version(tag, current_version):
            return None
    except ValueError:
        return None
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if isinstance(name, str) and name.lower().endswith(".exe") and isinstance(url, str) and url:
            notes = release.get("body")
            return {"version": tag, "download_url": url, "notes": notes if isinstance(notes, str) else ""}
    return None


def fetch_latest_release():
    """Fetches the latest GitHub release info as parsed JSON. Raises on any network,
    HTTP or parsing error rather than returning None, so the caller can tell
    "couldn't check" (offline, rate-limited) apart from "no newer release"; the
    update-check thread catches it, so it never crashes the app."""
    import urllib.request

    req = urllib.request.Request(
        GITHUB_LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_for_update(current_version, fetcher=fetch_latest_release):
    release = fetcher()
    if release is None:
        return None
    return find_update(release, current_version)


def count_color_pixels(rgb_array, target_color, tolerance):
    """Returns a boolean mask of pixels in `rgb_array` (an HxWx3 array) within
    `tolerance` (per-channel absolute difference) of target_color."""
    import numpy as np

    diff = np.abs(rgb_array.astype(np.int16) - np.array(target_color, dtype=np.int16))
    return np.all(diff <= tolerance, axis=-1)


def color_match_bgra(frame, target_color, tolerance):
    """Counts the pixels of a BGRA frame within `tolerance` (per channel) of the RGB
    target_color. Returns (count, cx, cy) - cx/cy being the truncated mean position
    of those pixels - or (0, 0, 0) if there are none.

    Gives exactly what count_color_pixels() on the RGB channels plus a numpy
    nonzero().mean() gives (the scan loop's original implementation), in one
    cv2.inRange pass instead of ~6 full-frame numpy passes and copies: measured
    ~10x faster on an 818x659 region, i.e. less CPU taken from the game."""
    import cv2
    import numpy as np

    if tolerance != tolerance:  # NaN: `diff <= nan` never matches
        return 0, 0, 0
    # Same float->int truncation the int16 numpy version applies to the target, and
    # for integer pixel differences |d| <= tol is exactly |d| <= floor(tol).
    r, g, b = (int(v) for v in np.array(target_color, dtype=np.int16))
    k = 255 if tolerance >= 255 else math.floor(tolerance)
    lower = (max(b - k, 0), max(g - k, 0), max(r - k, 0), 0)
    upper = (min(b + k, 255), min(g + k, 255), min(r + k, 255), 255)
    mask = cv2.inRange(frame, lower, upper)
    count = cv2.countNonZero(mask)
    if count == 0:
        return 0, 0, 0
    # Centroid from per-column/row counts: exact integer sums, then the same single
    # division numpy's mean does - so truncation can't come out differently.
    cols = cv2.reduce(mask, 0, cv2.REDUCE_SUM, dtype=cv2.CV_32S).ravel() // 255
    rows = cv2.reduce(mask, 1, cv2.REDUCE_SUM, dtype=cv2.CV_32S).ravel() // 255
    sum_x = int(np.dot(cols.astype(np.int64), np.arange(cols.size, dtype=np.int64)))
    sum_y = int(np.dot(rows.astype(np.int64), np.arange(rows.size, dtype=np.int64)))
    return count, int(sum_x / count), int(sum_y / count)


def analyze_color_trigger(crop_img, tolerance=None):
    """Given a PIL image crop of the drag-selected trigger, extracts the
    dominant non-background (distinctly colored, not-too-dark) color and how
    many pixels in the crop matched it - the reference signal 'color'
    detection_method looks for during scanning, instead of image template
    correlation. Falls back to treating the whole crop as the target color if
    nothing clears the saturation/brightness floor (e.g. a solid-color
    capture). Pass the color_tolerance scanning will use, so the pixel count
    (which min_color_pixels is derived from) is measured the same way."""
    import numpy as np

    rgb = np.array(crop_img.convert("RGB"))
    hsv = np.array(crop_img.convert("HSV"))
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    # Saturation alone isn't enough: a near-black pixel can have a high
    # saturation *ratio* purely from being dark, without looking distinctive at
    # all - requiring real brightness too keeps dark background out.
    candidates = rgb[(saturation > COLOR_SATURATION_MIN) & (value > COLOR_VALUE_MIN)]
    if len(candidates) == 0:
        candidates = rgb.reshape(-1, 3)
    target_color = tuple(int(v) for v in np.median(candidates, axis=0))
    if tolerance is None:
        tolerance = DEFAULT_CONFIG["color_tolerance"]
    pixel_count = int(count_color_pixels(rgb, target_color, tolerance).sum())
    return target_color, pixel_count


def compute_scan_region_offset(box_abs, window_rect):
    """Given an absolute-screen box (left, top, right, bottom) and the target
    window's current absolute rect, returns the box as an offset relative to
    the window's own top-left corner - so it can be reapplied against the
    window's current position on each scan tick even if the window has moved
    since this was captured."""
    left, top, right, bottom = box_abs
    return {
        "left": left - window_rect["left"],
        "top": top - window_rect["top"],
        "width": right - left,
        "height": bottom - top,
    }


def apply_scan_region_offset(window_rect, scan_region):
    """Re-anchors a captured scan_region offset onto the window's current
    absolute position, clipped to the window so a region saved for a bigger (or
    since-resized) window never scans what's beside it. Returns window_rect
    unchanged if scan_region is None (meaning "scan the whole window") or if the
    region doesn't overlap the window at all."""
    if not scan_region:
        return window_rect
    left = max(window_rect["left"], window_rect["left"] + scan_region["left"])
    top = max(window_rect["top"], window_rect["top"] + scan_region["top"])
    right = min(window_rect["left"] + window_rect["width"],
                window_rect["left"] + scan_region["left"] + scan_region["width"])
    bottom = min(window_rect["top"] + window_rect["height"],
                 window_rect["top"] + scan_region["top"] + scan_region["height"])
    if right <= left or bottom <= top:
        return window_rect
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def describe_current_setup(cfg, ready, captured_desc=""):
    """Plain-language sentence describing what KryptikClicks is currently set
    up to do, for the Simple tab - so a casual/non-technical viewer doesn't
    need to parse the Advanced tab's settings to understand current behavior."""
    if not ready:
        if cfg.get("click_mode") == "generic":
            return "Capture a click target to get started."  # Generic has no trigger
        return "Capture a trigger to get started."

    position_phrase = (
        "wherever your mouse already is" if cfg.get("click_position") == "cursor"
        else "at your saved click spot"
    )

    if cfg.get("click_mode") == "generic":
        min_ms = int(cfg.get("min_delay_ms", 0))
        max_ms = int(cfg.get("max_delay_ms", 0))
        return f"Clicking automatically {position_phrase} every {min_ms}-{max_ms}ms."

    if cfg.get("scan_scope") == "window":
        location_phrase = f'in "{cfg.get("scan_window_title", "")}"'
    else:
        location_phrase = "anywhere on your screen"

    trigger_min = int(cfg.get("trigger_delay_min_ms", 0))
    trigger_max = int(cfg.get("trigger_delay_max_ms", 0))
    if trigger_max <= 0:
        timing_phrase = "when it's found"
    elif trigger_min == trigger_max:
        timing_phrase = f"{trigger_max}ms after it's found"
    else:
        timing_phrase = f"{trigger_min}-{trigger_max}ms after it's found"

    return f"Watching for {captured_desc} {location_phrase}, clicking {position_phrase} {timing_phrase}."


def find_window_by_title(windows, title):
    """Given a [(hwnd, title), ...] list (as returned by list_visible_windows()),
    returns the hwnd of the first exact title match, or None."""
    for hwnd, win_title in windows:
        if win_title == title:
            return hwnd
    return None


def list_visible_windows(exclude_hwnd=None):
    """Enumerates visible, titled top-level windows for the window-scoped scan
    picker. Skips windows with no title, DWM-cloaked windows (background UWP
    apps that report as visible but aren't actually shown), and exclude_hwnd
    (KryptikClicks' own window, so it can't target itself)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    DWMWA_CLOAKED = 14

    windows = []

    def is_cloaked(hwnd):
        cloaked = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return cloaked.value != 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_handler(hwnd, lparam):
        if exclude_hwnd is not None and hwnd == exclude_hwnd:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        if is_cloaked(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            windows.append((hwnd, title))
        return True

    user32.EnumWindows(enum_handler, 0)
    return windows


def get_window_rect(hwnd):
    """Returns a monitor-shaped dict (left/top/width/height) for hwnd's current
    on-screen bounds, via DWM's extended frame bounds (more accurate than
    GetWindowRect - excludes the invisible resize-border padding Windows
    10/11 adds), falling back to GetWindowRect if that call fails."""
    import ctypes
    from ctypes import wintypes

    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    rect = wintypes.RECT()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
    )
    if result != 0:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {
        "left": rect.left,
        "top": rect.top,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
    }


def is_window_valid(hwnd):
    import ctypes
    return bool(ctypes.windll.user32.IsWindow(hwnd))


def is_window_minimized(hwnd):
    import ctypes
    return bool(ctypes.windll.user32.IsIconic(hwnd))


def capture_window_thumbnail(hwnd, max_size=(160, 100)):
    """Captures hwnd's current appearance (even if occluded or behind other
    windows) via PrintWindow, returning a PIL Image thumbnail. Returns None if
    the window has no size, or the capture comes back blank - some
    GPU-accelerated windows (some games/browsers) don't render via
    PrintWindow, and a blank thumbnail isn't useful for picking."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    try:
        PW_RENDERFULLCONTENT = 2
        user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # negative = top-down DIB, matches PIL's row order
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        buf = (ctypes.c_ubyte * (width * height * 4))()
        gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(header), 0)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)

    img = Image.frombuffer("RGB", (width, height), bytes(buf), "raw", "BGRX", 0, 1)
    if img.getbbox() is None:  # fully blank - PrintWindow didn't actually render anything
        return None
    img.thumbnail(max_size)
    return img


def canvas_point_to_absolute(canvas_x, canvas_y, monitor):
    """Converts a point picked on the capture overlay canvas (0,0 = top-left of
    the captured image) to a true absolute screen coordinate. Needed because
    mss's combined virtual-desktop origin (monitor["left"/"top"]) is non-zero
    whenever a monitor sits left of/above the primary display."""
    return (canvas_x + monitor["left"], canvas_y + monitor["top"])


def run_capture_ui(parent=None, require_click_point=True, label_text=None, require_trigger=True):
    """Shows the capture overlay: drag-select the trigger image, then
    (if require_click_point) click the spot to auto-click. Pass require_click_point=False
    to skip that second step - used when the click position will be the live cursor
    position instead of a captured point. Pass require_trigger=False to skip the
    first step instead - Generic mode only needs the click point. Pass label_text to
    override the default step-1 instructions (e.g. reusing this same drag-select
    flow for defining a scan region instead of a trigger).

    On multi-monitor setups this shows one overlay window per physical monitor
    (each sized to just that monitor) rather than one giant window spanning
    the whole virtual desktop - a single override-redirect window sized to
    span multiple monitors was found to not actually get painted by Windows'
    compositor, leaving an invisible-but-topmost dead zone. Per-monitor
    windows are normal-sized and render reliably, and the drag/click can
    start on whichever monitor the mouse is already on.

    Returns (template_box, target_point, full_img) - template_box is None when
    require_trigger is False - or (None, None, None) if cancelled.
    Pass a Tkinter root as `parent` to run modally inside an existing app; omit for standalone use.
    """
    import tkinter as tk
    from PIL import Image, ImageTk
    import mss

    with mss.mss() as sct:
        virtual = sct.monitors[0]
        shot = sct.grab(virtual)
        full_img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        physical_monitors = sct.monitors[1:] or [virtual]

    standalone = parent is None
    controller = tk.Tk() if standalone else tk.Toplevel(parent)
    controller.withdraw()  # invisible; just coordinates the per-monitor windows and blocks until done

    step1_text = label_text or (
        "Step 1/2: Drag a tight box around the trigger you want it to watch for, then release. Esc to cancel."
        if require_click_point else
        "Drag a tight box around the trigger you want it to watch for, then release. Esc to cancel."
    )

    if not require_trigger:
        step1_text = "Click the spot you want it to auto-click. Esc to cancel."

    state = {
        "phase": 1 if require_trigger else 2, "start": None, "start_mon": None, "rect": None,
        "rect_canvas": None, "template_box": None, "target_point": None, "done": False,
    }
    windows = []
    labels = []

    def set_label_text(text):
        for lbl in labels:
            lbl.config(text=text)

    def finish():
        if state["done"]:
            return
        state["done"] = True
        for w in windows:
            w.destroy()
        controller.destroy()

    def on_escape(_event):
        state["template_box"] = None
        state["target_point"] = None
        finish()

    def make_handlers(mon, canvas):
        def on_press(event):
            if state["phase"] == 1:
                state["start"] = (event.x, event.y)
                state["start_mon"] = mon
                if state["rect"] is not None:
                    state["rect_canvas"].delete(state["rect"])
                state["rect"] = canvas.create_rectangle(
                    event.x, event.y, event.x, event.y, outline="red", width=2
                )
                state["rect_canvas"] = canvas
            elif state["phase"] == 2:
                state["target_point"] = canvas_point_to_absolute(event.x, event.y, mon)
                canvas.create_oval(
                    event.x - 6, event.y - 6, event.x + 6, event.y + 6, outline="lime", width=3
                )
                controller.after(250, finish)

        def on_drag(event):
            if state["phase"] != 1 or state["start"] is None or state["start_mon"] is not mon:
                return
            x0, y0 = state["start"]
            canvas.coords(state["rect"], x0, y0, event.x, event.y)

        def on_release(event):
            if state["phase"] != 1 or state["start"] is None or state["start_mon"] is not mon:
                return
            x0, y0 = state["start"]
            x1, y1 = event.x, event.y
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            if right - left < 3 or bottom - top < 3:
                return
            abs_left, abs_top = canvas_point_to_absolute(left, top, mon)
            abs_right, abs_bottom = canvas_point_to_absolute(right, bottom, mon)
            # template_box indexes into full_img, which starts at the virtual desktop's own origin.
            state["template_box"] = (
                abs_left - virtual["left"], abs_top - virtual["top"],
                abs_right - virtual["left"], abs_bottom - virtual["top"],
            )
            if require_click_point:
                state["phase"] = 2
                set_label_text("Step 2/2: Click the spot you want it to auto-click. Esc to cancel.")
            else:
                controller.after(0, finish)

        return on_press, on_drag, on_release

    for mon in physical_monitors:
        left = mon["left"] - virtual["left"]
        top = mon["top"] - virtual["top"]
        crop = full_img.crop((left, top, left + mon["width"], top + mon["height"]))

        w = tk.Toplevel(controller)
        w.overrideredirect(True)
        w.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
        w.attributes("-topmost", True)
        w.configure(cursor="crosshair")

        tk_img = ImageTk.PhotoImage(crop, master=w)
        canvas = tk.Canvas(w, width=mon["width"], height=mon["height"], highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=tk_img, anchor="nw")
        canvas.image = tk_img  # keep a reference alive

        label = tk.Label(w, text=step1_text, bg="yellow")
        label.place(x=10, y=10)
        labels.append(label)

        on_press, on_drag, on_release = make_handlers(mon, canvas)
        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        w.bind("<Escape>", on_escape)
        windows.append(w)

    if windows:
        windows[0].focus_force()
    if not standalone:
        controller.grab_set()

    if standalone:
        controller.mainloop()
    else:
        parent.wait_window(controller)

    captured = state["template_box"] if require_trigger else state["target_point"]
    if captured is None:
        return None, None, None
    return state["template_box"], state["target_point"], full_img


def save_click_point(target_point):
    with open(TARGET_PATH, "w") as f:
        f.write(f"{target_point[0]},{target_point[1]}\n")


def save_capture(template_box, target_point, full_img):
    crop = full_img.crop(template_box)
    crop.save(TEMPLATE_PATH)
    if target_point is not None:
        save_click_point(target_point)
    return crop.width, crop.height


def capture_template_cli():
    box, point, full_img = run_capture_ui(parent=None)
    if box is None:
        print("Capture cancelled.")
        sys.exit(1)
    w, h = save_capture(box, point, full_img)
    print(f"Saved template ({w}x{h}) to {TEMPLATE_PATH}")
    print(f"Saved click target {point} to {TARGET_PATH}")


def parse_settings_input(min_ms_str, max_ms_str, thr_str, click_limit_str,
                         trigger_min_str="0", trigger_max_str="0"):
    """Parses/validates the settings-form text fields. Raises ValueError with a
    user-facing message on invalid input; otherwise returns the parsed values."""
    try:
        min_ms = float(min_ms_str)
        max_ms = float(max_ms_str)
        thr = float(thr_str)
        click_limit = int(float(click_limit_str))
        trigger_min = float(trigger_min_str)
        trigger_max = float(trigger_max_str)
    except (ValueError, OverflowError):  # int(float("inf")) raises OverflowError
        raise ValueError("Enter valid numbers.")
    if not is_valid_delay_range(trigger_min, trigger_max):
        raise ValueError("Trigger delay min must be >= 0 and <= trigger delay max (at most 24 hours).")
    if not is_valid_delay_range(min_ms, max_ms):
        raise ValueError("Min delay must be >= 0 and <= max delay (at most 24 hours).")
    if not (0.0 < thr <= 1.0):
        raise ValueError("Threshold must be between 0 and 1.")
    if click_limit < 0:
        raise ValueError("Click limit must be 0 (infinite) or a positive number.")
    return {
        "min_delay_ms": min_ms,
        "max_delay_ms": max_ms,
        "match_threshold": thr,
        "click_limit": click_limit,
        "trigger_delay_min_ms": trigger_min,
        "trigger_delay_max_ms": trigger_max,
    }


class Detector:
    """Loads the template/target and does the screen-matching + clicking work.
    Shared by both the GUI and the headless CLI mode."""

    # In cursor-position mode, the longest we'll wait for the local region around
    # a detected trigger to read as "gone" before clicking again anyway. Ambient
    # game content near the trigger (not the trigger itself) can keep scoring as
    # a match indefinitely, which without this cap can starve real re-clicks for
    # a very long time (observed: 36+ seconds during actual gameplay).
    CURSOR_MODE_MAX_WAIT_SECONDS = 2.0

    # In fixed-position mode, the most consecutive clicks a single detection
    # will fire before forcing a fresh full-region scan, even if the local
    # region around the last click still reads as a match. Continuous
    # clicking while a trigger is genuinely visible is intentional, but this
    # caps how far a stale or overly-broad match (e.g. a bad color capture
    # that matches most of the window) can run before being re-verified.
    MAX_CLICKS_PER_BURST = 5

    # How long after Start is pressed before a real click can fire. Cursor-
    # position mode clicks wherever the mouse currently is - right after
    # pressing Start, that's still resting on the Start button - so an
    # immediate match (or Generic mode, which has no trigger to wait for)
    # could click that same button and pause the scan that just started.
    # This gives the user a moment to move the mouse away first.
    START_CLICK_GRACE_SECONDS = 0.75

    # In cursor-position mode, how many consecutive re-checks must miss before the
    # trigger counts as gone. One dropped sample (an animation frame, a brief
    # occlusion) otherwise ended the wait, and the next full scan re-detected it
    # as a brand-new trigger and clicked again straight away.
    GONE_AFTER_MISSES = 3

    # mss accumulates Windows GDI resources over a long-running capture loop and
    # gradually slows down; recreating it every this-many scan ticks keeps capture
    # speed steady.
    MSS_REFRESH_INTERVAL = 300

    def __init__(self, cfg, log=print):
        import cv2
        import mss

        self.cv2 = cv2
        self.mss = mss
        self.cfg = cfg
        self.log = log

        self.template = None
        self.t_w = self.t_h = 0
        self.click_x = self.click_y = None
        self.total_clicks = 0
        self.load()

        self.scanning_active = threading.Event()
        self.stop_event = threading.Event()
        self._started_at = 0.0
        self._resolved_window_title = None  # the scan_window_title the cached hwnd was found by

    def start_scanning(self):
        self.total_clicks = 0
        self.resume_scanning()

    def resume_scanning(self):
        """Carries on after a pause the app made itself (around a capture/selection
        overlay): re-arms the start grace period, but keeps the click count, so the
        Repeat limit still counts clicks from before the pause."""
        self._started_at = time.monotonic()
        self.scanning_active.set()

    def _grace_period_active(self):
        return time.monotonic() - self._started_at < self.START_CLICK_GRACE_SECONDS

    def pause_scanning(self):
        self.scanning_active.clear()

    def _limit_reached(self):
        limit = self.cfg.get("click_limit", 0)
        return bool(limit) and self.total_clicks >= limit

    @property
    def ready(self):
        cursor_position = self.cfg.get("click_position") == "cursor"
        if self.cfg.get("click_mode", "targeted") == "generic":
            if cursor_position:
                return True  # no capture needed at all
            return self.click_x is not None  # fixed position needs a captured point, not a template
        if cursor_position:
            return self._trigger_ready()  # trigger still needed, but not a click point
        return self._trigger_ready() and self.click_x is not None

    def _trigger_ready(self):
        if self.cfg.get("detection_method") == "color":
            return self.cfg.get("target_color") is not None
        return self.template is not None

    def load(self):
        if os.path.exists(TEMPLATE_PATH):
            self.template = self.cv2.imread(TEMPLATE_PATH, self.cv2.IMREAD_GRAYSCALE)
            if self.template is not None:
                self.t_h, self.t_w = self.template.shape[:2]
            else:
                self.log(f"Warning: {TEMPLATE_PATH} is corrupted/unreadable - recapture needed.")
        if os.path.exists(TARGET_PATH):
            try:
                with open(TARGET_PATH) as f:
                    x, y = map(int, f.read().strip().split(","))
                self.click_x, self.click_y = x, y
            except (OSError, ValueError):
                self.log(f"Warning: {TARGET_PATH} is corrupted/unreadable - recapture needed.")
                self.click_x = self.click_y = None

    def _resolve_click_position(self):
        if self.cfg.get("click_position") == "cursor":
            import pyautogui
            return pyautogui.position()
        return (self.click_x, self.click_y)

    def _click_once(self):
        import pyautogui
        try:
            x, y = self._resolve_click_position()
            pyautogui.click(x, y, button=self.cfg.get("click_button", "left"))
        except Exception as e:
            self.log(f"Click error (continuing): {e}")
        self.total_clicks += 1

    def _beep(self):
        if not self.cfg.get("sound_enabled", False):
            return
        try:
            import winsound
            winsound.Beep(880, 120)
        except Exception:
            pass

    def _match_score_in(self, sct, region):
        """Grabs and matches `region`, returning (x, y, score) for the best spot
        found - regardless of whether it clears the configured threshold. Score is
        directly comparable across separate regions/monitors, unlike a plain
        hit/miss result. Dispatches to whichever detection_method is configured."""
        if self.cfg.get("detection_method") == "color":
            return self._color_match_score_in(sct, region)
        return self._template_match_score_in(sct, region)

    def _template_match_score_in(self, sct, region):
        shot = sct.grab(region)
        import numpy as np
        frame = np.asarray(shot)  # BGRA, a zero-copy view of the grab's own buffer
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGRA2GRAY)
        result = self.cv2.matchTemplate(gray, self.template, self.cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = self.cv2.minMaxLoc(result)
        x = region["left"] + max_loc[0] + self.t_w // 2
        y = region["top"] + max_loc[1] + self.t_h // 2
        return x, y, max_val

    def _color_match_score_in(self, sct, region):
        """Counts pixels matching the captured target color instead of correlating
        against a template image - ignores everything except that specific color,
        so it isn't thrown off by background content changing behind the trigger
        the way template correlation can be."""
        shot = sct.grab(region)
        import numpy as np
        frame = np.asarray(shot)  # BGRA, a zero-copy view of the grab's own buffer
        count, cx, cy = color_match_bgra(
            frame, self.cfg["target_color"], self.cfg.get("color_tolerance", DEFAULT_CONFIG["color_tolerance"])
        )
        if count == 0:
            return region["left"], region["top"], 0
        return region["left"] + cx, region["top"] + cy, count

    def _score_threshold(self):
        if self.cfg.get("detection_method") == "color":
            # Floor of 1: a frame with no target-colored pixels scores 0, and a 0
            # threshold (load_config's fallback for a bad value) would count it as a hit.
            return max(1, self.cfg.get("min_color_pixels", DEFAULT_CONFIG["min_color_pixels"]))
        return self.cfg.get("match_threshold", DEFAULT_CONFIG["match_threshold"])

    def _find_match_in(self, sct, region):
        x, y, score = self._match_score_in(sct, region)
        if score >= self._score_threshold():
            return x, y
        return None

    def _resolve_scan_regions(self, cached_hwnd, sct):
        """Returns (regions, hwnd, status) - the region(s) to scan this tick.
        In "all_monitors" mode (default), regions is every physical monitor from
        the given (already-open) mss instance, unchanged from before
        window-scoped scanning existed. In "window" mode, regions is a
        single-item list for the configured target window's live bounds,
        re-resolving cached_hwnd by title whenever it's no longer valid (the
        target app may have been restarted, getting a new hwnd) or a different
        window has been chosen since. It deliberately doesn't re-check the live
        window title each tick - RuneLite's changes on login/logout. status is "ok", "minimized", or "not_found" - the
        latter two mean regions is empty, meaning there's nothing to scan this
        tick (idle, not a miss)."""
        if self.cfg.get("scan_scope") != "window":
            monitors = sct.monitors[1:] or [sct.monitors[0]]
            return monitors, None, "ok"

        title = self.cfg.get("scan_window_title", "")
        hwnd = cached_hwnd
        if hwnd is None or title != self._resolved_window_title or not is_window_valid(hwnd):
            hwnd = find_window_by_title(list_visible_windows(), title)
            self._resolved_window_title = title
        if hwnd is None:
            return [], None, "not_found"
        if is_window_minimized(hwnd):
            return [], hwnd, "minimized"
        window_rect = get_window_rect(hwnd)
        region = apply_scan_region_offset(window_rect, self.cfg.get("scan_region"))
        return [region], hwnd, "ok"

    def _local_region_around(self, x, y, monitor):
        pad = 60
        left = max(monitor["left"], x - self.t_w // 2 - pad)
        top = max(monitor["top"], y - self.t_h // 2 - pad)
        right = min(monitor["left"] + monitor["width"], x + self.t_w // 2 + pad)
        bottom = min(monitor["top"] + monitor["height"], y + self.t_h // 2 + pad)
        # Guard against a region smaller than the template near screen edges/corners
        # (cv2.matchTemplate raises if the search image is smaller than the template).
        if right - left < self.t_w:
            right = min(monitor["left"] + monitor["width"], left + self.t_w)
            left = max(monitor["left"], right - self.t_w)
        if bottom - top < self.t_h:
            bottom = min(monitor["top"] + monitor["height"], top + self.t_h)
            top = max(monitor["top"], bottom - self.t_h)
        return {"left": left, "top": top, "width": right - left, "height": bottom - top}

    def _recheck_region(self, match, hit_region):
        """Where to look to see whether a detected trigger is still there. Template
        mode tracks that one spot. Color mode re-counts the whole region it was found
        in: its match point is the centroid of ALL matching pixels, so with any other
        target-colored content on screen it can sit on empty space between them,
        and a small box there would wrongly read as "gone"."""
        if self.cfg.get("detection_method") == "color":
            return hit_region
        return self._local_region_around(match[0], match[1], hit_region)

    def run(self):
        """Blocks, running the scan/click loop until stop_event is set."""
        import pyautogui
        import concurrent.futures

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0  # we control click timing ourselves

        sct = self.mss.mss()
        scan_count = 0
        last_error_log = 0.0
        cached_hwnd = None
        last_window_status = None
        # Scanning one region spanning every monitor at once is slow (hundreds of ms on
        # a large multi-monitor desktop) and can miss a trigger that only flashes briefly.
        # Scanning each physical monitor in its own thread instead cuts that latency
        # roughly to the slowest single monitor rather than the sum of all of them. Sized
        # from the monitor count regardless of scan_scope - window mode only ever submits
        # one task, so a bigger pool just sits idle rather than causing any problem.
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(sct.monitors[1:])))

        def log_error(prefix, e):
            # Rate-limited so a persistent failure doesn't flood the Activity log.
            nonlocal last_error_log
            now = time.monotonic()
            if now - last_error_log > 5.0:
                self.log(f"{prefix} (continuing): {e}")
                last_error_log = now

        def scan_tick():
            nonlocal sct, scan_count
            scan_count += 1
            if scan_count % self.MSS_REFRESH_INTERVAL == 0:
                # Build the replacement before closing the old one - if that fails
                # (e.g. mid display change), keep capturing with the old instance.
                try:
                    fresh = self.mss.mss()
                except Exception as e:
                    log_error("Capture refresh error", e)
                    return
                sct.close()
                sct = fresh

        def safe_find_match(region):
            # A transient capture/match error shouldn't permanently kill background
            # detection - log it (rate-limited) and treat the frame as a miss.
            try:
                return self._find_match_in(sct, region)
            except Exception as e:
                log_error("Scan error", e)
                return None

        def safe_score_threaded(region):
            # mss instances aren't thread-safe, so each worker thread grabs its own.
            try:
                with self.mss.mss() as thread_sct:
                    return self._match_score_in(thread_sct, region)
            except Exception as e:
                log_error("Scan error", e)
                return None

        def scan_regions(regions):
            """Checks the given region(s) for the trigger and returns (match_xy,
            region) for whichever has the strongest match, or (None, None) if none
            clear the threshold. Waits for every region rather than racing to
            whichever finishes first - ordinary content in an unrelated region can
            score close to a real match, so taking the fastest result instead of
            the best one can pick a false positive over the real match elsewhere."""
            if len(regions) == 1:
                return safe_find_match(regions[0]), regions[0]
            futures = {executor.submit(safe_score_threaded, r): r for r in regions}
            best = None  # (max_val, x, y, region)
            for future, r in futures.items():
                result = future.result()
                if result is None:
                    continue
                x, y, max_val = result
                if max_val >= self._score_threshold() and (best is None or max_val > best[0]):
                    best = (max_val, x, y, r)
            if best is None:
                return None, None
            _, x, y, r = best
            return (x, y), r

        def scan_for_trigger():
            """Resolves this tick's region(s) (logging window found/lost transitions)
            and scans them. Returns (match_xy, region), or (None, None)."""
            nonlocal cached_hwnd, last_window_status
            regions, cached_hwnd, status = self._resolve_scan_regions(cached_hwnd, sct)
            if status != last_window_status:
                if status == "not_found":
                    title = self.cfg.get("scan_window_title", "")
                    self.log(f'Target window "{title}" not found - waiting...')
                elif status == "minimized":
                    self.log("Target window is minimized - waiting...")
                elif status == "ok" and last_window_status in ("not_found", "minimized"):
                    self.log("Target window found - resuming scan.")
                last_window_status = status
            if not regions:
                return None, None
            return scan_regions(regions)

        def click_delay():
            return random.uniform(self.cfg["min_delay_ms"], self.cfg["max_delay_ms"]) / 1000.0

        def wait_while_active(seconds, still_wanted=lambda: True):
            """Waits up to `seconds`, giving up early if scanning is paused, the app quits
            or still_wanted() turns False. Returns True only if the whole wait elapsed.
            Sleeps in short time.sleep() slices rather than Event.wait() (which rounds up
            to Windows' ~15ms timer tick), timed with perf_counter: before Python 3.13,
            time.monotonic() has that same ~15.6ms resolution on Windows."""
            deadline = time.perf_counter() + seconds
            while self.scanning_active.is_set() and not self.stop_event.is_set() and still_wanted():
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return True
                time.sleep(min(remaining, SCAN_INTERVAL))
            return False

        def watch(seconds, match, hit_region, full_scan=False):
            """Waits `seconds` while re-checking the trigger every SCAN_INTERVAL, then
            makes sure it's still there. Returns (match, region) from a fresh sighting,
            or (None, region) if scanning stopped or the trigger was missed
            GONE_AFTER_MISSES times in a row - at any point, so one that goes away and
            comes back during the wait is a new appearance (and pays the trigger delay),
            while a single dropped frame isn't. full_scan re-resolves the whole scan area
            each time (the window may move or be minimized during a trigger delay)
            instead of re-checking where the trigger was."""
            deadline = time.perf_counter() + seconds
            misses, fresh = 0, False
            while self.scanning_active.is_set() and not self.stop_event.is_set():
                remaining = deadline - time.perf_counter()
                if remaining <= 0 and fresh:
                    return match, hit_region
                time.sleep(min(remaining, SCAN_INTERVAL) if remaining > 0 else SCAN_INTERVAL)
                scan_tick()
                if full_scan:
                    seen, seen_region = scan_for_trigger()
                else:
                    seen, seen_region = safe_find_match(self._recheck_region(match, hit_region)), hit_region
                if seen is not None:
                    match, hit_region, misses, fresh = seen, seen_region, 0, True
                    continue
                fresh = False
                misses += 1
                if misses >= self.GONE_AFTER_MISSES:
                    return None, hit_region
            return None, hit_region

        def click_and_check_limit():
            """Clicks once; if that hits the configured limit, pauses and returns True."""
            self._click_once()
            if self._limit_reached():
                self.log(f"Reached click limit ({self.total_clicks}); stopping.")
                self.pause_scanning()
                return True
            return False

        # True while the trigger from the previous burst was still on screen when that
        # burst ended (fixed mode's MAX_CLICKS_PER_BURST re-scan) - that's the same
        # appearance continuing, so the trigger delay mustn't be paid again for it.
        # Only GONE_AFTER_MISSES misses in a row end it, not one dropped frame.
        trigger_still_showing = False
        misses_since_burst = 0

        try:
            while not self.stop_event.is_set():
                # Anything unexpected (ctypes window calls, capture, ...) must not end the
                # thread - that silently stops all detection while the UI says Scanning.
                try:
                    if not (self.scanning_active.is_set() and self.ready) or self._grace_period_active():
                        trigger_still_showing = False
                        time.sleep(SCAN_INTERVAL)
                        continue

                    if self.cfg.get("click_mode", "targeted") == "generic":
                        # No trigger to wait for - click on interval for as long as it's active
                        # (and still Generic: the Mode radio applies instantly, even mid-run,
                        # so the interval wait stops as soon as it's switched away).
                        trigger_still_showing = False  # whatever shows up afterwards is new
                        self._beep()

                        def still_generic():
                            return self.cfg.get("click_mode") == "generic"

                        while self.scanning_active.is_set() and not self.stop_event.is_set() and still_generic():
                            if click_and_check_limit():
                                break
                            wait_while_active(click_delay(), still_generic)
                        continue

                    scan_tick()
                    match, hit_region = scan_for_trigger()
                    if match is None:
                        misses_since_burst += 1
                        if misses_since_burst >= self.GONE_AFTER_MISSES:
                            trigger_still_showing = False
                        time.sleep(SCAN_INTERVAL)
                        continue
                    misses_since_burst = 0

                    trigger_delay = 0.0 if trigger_still_showing else random.uniform(
                        self.cfg.get("trigger_delay_min_ms", 0), self.cfg.get("trigger_delay_max_ms", 0)
                    ) / 1000.0
                    if trigger_delay > 0:
                        self.log(f"Trigger detected - clicking in {round(trigger_delay * 1000)}ms...")
                        # Keep watching the whole scan area through the delay: the click only
                        # happens if the trigger stays up for all of it.
                        match, hit_region = watch(trigger_delay, match, hit_region, full_scan=True)
                        if match is None:
                            if self.scanning_active.is_set() and not self.stop_event.is_set():
                                self.log("Trigger disappeared during the delay - not clicking.")
                            continue  # (or paused/quit mid-wait - either way, no click)
                    else:
                        self.log("Trigger detected - clicking...")
                    self._beep()
                    cursor_mode = self.cfg.get("click_position") == "cursor"
                    burst_clicks = 0
                    while match is not None and self.scanning_active.is_set() and not self.stop_event.is_set():
                        if click_and_check_limit():
                            break
                        burst_clicks += 1
                        if cursor_mode:
                            # Cursor-position mode clicks wherever the mouse already is, not on
                            # the trigger - so unlike fixed-position mode, clicking doesn't make
                            # the trigger go away on its own. Wait for it to actually disappear
                            # before treating a later sighting as a new detection, instead of
                            # re-clicking every cycle while it just sits there. But don't wait
                            # forever - ambient content near the trigger can keep the local
                            # region reading as a match well after the real trigger is gone.
                            wait_start = time.monotonic()
                            timed_out = False
                            misses = 0
                            while self.scanning_active.is_set() and not self.stop_event.is_set():
                                if time.monotonic() - wait_start > self.CURSOR_MODE_MAX_WAIT_SECONDS:
                                    timed_out = True
                                    break
                                time.sleep(SCAN_INTERVAL)
                                scan_tick()
                                seen = safe_find_match(self._recheck_region(match, hit_region))
                                if seen is not None:
                                    match, misses = seen, 0
                                    continue
                                misses += 1
                                if misses >= self.GONE_AFTER_MISSES:
                                    match = None
                                    break
                            if timed_out:
                                # Still (probably) there - click again rather than wait longer,
                                # if it stays there through the click delay.
                                match, hit_region = watch(click_delay(), match, hit_region)
                                continue
                            break
                        match, hit_region = watch(click_delay(), match, hit_region)
                        if match is not None and burst_clicks >= self.MAX_CLICKS_PER_BURST:
                            break  # force a fresh full-region scan instead of trusting a stale local match
                    trigger_still_showing = match is not None
                    misses_since_burst = 0
                    self.log(f"Stopped clicking ({self.total_clicks} clicks this session).")
                except Exception as e:
                    log_error("Unexpected error", e)
                    trigger_still_showing = False
                    time.sleep(SCAN_INTERVAL)
        finally:
            executor.shutdown(wait=False)
            sct.close()


HOTKEY_DEBOUNCE_SECONDS = 0.3
UI_QUEUE_POLL_MS = 25  # how often the GUI runs calls handed over from other threads


class HotkeyListener:
    """Debounces held-key repeats and dispatches mapped hotkey actions.

    `hotkey_map` maps a key value to a zero-arg callback. `on_press`/`on_release`
    are meant to be handed straight to `pynput.keyboard.Listener`. A held key
    (repeat presses without an intervening release) never re-fires, and a
    released-then-re-pressed key is still subject to a debounce window so two
    genuine presses in quick succession don't double-fire.

    `dispatch`, if given, receives the action callable instead of the listener
    calling it directly - e.g. to marshal it onto the GUI thread.
    """

    def __init__(self, hotkey_map, dispatch=None):
        self.hotkey_map = hotkey_map
        self.dispatch = dispatch if dispatch is not None else (lambda action: action())
        self._held_keys = set()
        self._last_fired = {}

    def on_press(self, key):
        if key in self._held_keys:
            return
        self._held_keys.add(key)
        action = self.hotkey_map.get(key)
        if action is None:
            return
        now = time.monotonic()
        if now - self._last_fired.get(key, 0) < HOTKEY_DEBOUNCE_SECONDS:
            return
        self._last_fired[key] = now
        self.dispatch(action)

    def on_release(self, key):
        self._held_keys.discard(key)


def run_headless():
    from pynput import keyboard as pynkeyboard

    detector = Detector(load_config(on_warning=print))
    if not detector.ready:
        print("No template/click-target found.")
        print("Run with --capture first: python KryptikClicks.py --capture")
        sys.exit(1)

    print(f"Template loaded: {detector.t_w}x{detector.t_h} px from {TEMPLATE_PATH}")
    print(f"Click target: ({detector.click_x}, {detector.click_y})")
    print(f"Press {TOGGLE_HOTKEY.upper()} to start/pause scanning, {QUIT_HOTKEY.upper()} to quit.")

    def toggle_scanning():
        if detector.scanning_active.is_set():
            detector.pause_scanning()
            print("[paused] scanning off")
        else:
            detector.start_scanning()
            print("[active] scanning on")

    def request_quit():
        print("Quitting...")
        detector.stop_event.set()

    hotkey_map = {
        pynkeyboard.Key[TOGGLE_HOTKEY]: toggle_scanning,
        pynkeyboard.Key[QUIT_HOTKEY]: request_quit,
    }
    hotkeys = HotkeyListener(hotkey_map)

    listener = pynkeyboard.Listener(on_press=hotkeys.on_press, on_release=hotkeys.on_release)
    listener.start()

    detector.run()
    listener.stop()
    print("Stopped.")


class KryptikClicksGUI:
    COLORS = {
        "bg": "#1e1f22",
        "panel_bg": "#2b2d31",
        "border": "#3f4147",
        "text": "#f2f3f5",
        "muted": "#80848e",
        "muted_dark": "#b5bac1",
        "accent": "#8700FF",
        "accent_dark": "#5800A6",
        "green": "#10B981",
        "green_dark": "#059669",
        "amber": "#D97706",
        "amber_dark": "#B45309",
        "red": "#f23f42",
        "red_dark": "#da373c",
    }
    FONT = "Segoe UI"

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk, messagebox
        from pynput import keyboard as pynkeyboard

        self.tk = tk
        self.messagebox = messagebox
        self._quitting = False
        # Calls handed over from other threads (detector worker, hotkey listener,
        # update check) for the Tk thread to run - see _on_ui_thread.
        self._ui_calls = queue.SimpleQueue()

        startup_warnings = []
        self.cfg = load_config(on_warning=startup_warnings.append)

        # Windows groups/identifies taskbar buttons by the *hosting* process
        # unless the process claims its own identity. Run from source, that
        # host is python.exe/pythonw.exe - so without this, Windows can show
        # python.exe's own icon on the taskbar button instead of the icon we
        # set on the window below, even though the window's own title bar
        # (unaffected by this) shows ours correctly. Must be set before the
        # first window is created. No-op effect if it fails - not required
        # for the window itself to work, just for taskbar icon/grouping.
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kryptzi.KryptikClicks")
            except Exception:
                pass  # cosmetic only - fine to fall back to default taskbar grouping

        self.root = tk.Tk()
        # Only after the root exists: Detector.load() logs a warning for an unreadable
        # capture file, and log() goes through self.root.
        self.detector = Detector(self.cfg, log=self.log)
        self.root.title("KryptikClicks")
        self.root.configure(bg=self.COLORS["bg"])
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)
        self.root.report_callback_exception = self._on_callback_exception
        self._enable_dark_titlebar(self.root)
        try:
            self.root.iconbitmap(resource_path("assets", "icon.ico"))
        except Exception as e:
            # Cosmetic only - fine to fall back to the default icon, but silently
            # swallowing this meant a broken icon.ico could go unnoticed indefinitely
            # (this has happened before - see CHANGELOG v1.3.0). Surface it instead.
            self.log(f"Warning: couldn't load window icon ({e}).")

        self._style = ttk.Style(self.root)
        try:
            self._style.theme_use("clam")
        except tk.TclError:
            pass
        self._configure_styles()

        self._build_ui(tk, ttk)
        self._refresh_template_label()
        self._refresh_status()
        for warning in startup_warnings:
            self.log(warning)
            self.root.after(0, lambda w=warning: self.messagebox.showwarning("KryptikClicks - settings", w))

        # Global hotkeys (F6/F9) work even while another window has focus.
        # Fired on the pynput listener thread - dispatch marshals the action onto the GUI thread.
        self.hotkey_map = {
            pynkeyboard.Key[TOGGLE_HOTKEY]: self.on_toggle,
            pynkeyboard.Key[QUIT_HOTKEY]: self.on_quit,
        }
        self.hotkeys = HotkeyListener(self.hotkey_map, dispatch=self._on_ui_thread)
        self.listener = pynkeyboard.Listener(on_press=self.hotkeys.on_press, on_release=self.hotkeys.on_release)
        self.listener.start()

        self._drain_ui_calls()
        self.worker_thread = threading.Thread(target=self.detector.run, daemon=True)
        self.worker_thread.start()

        self._poll_status()
        self.root.mainloop()

    def _load_emblem(self):
        try:
            from PIL import Image, ImageTk
            path = resource_path("assets", "emblem_small.png")
            if not os.path.exists(path):
                return None
            return ImageTk.PhotoImage(Image.open(path), master=self.root)
        except Exception:
            return None  # cosmetic only - fine to skip if unavailable

    @staticmethod
    def _enable_dark_titlebar(window):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            value = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new/old builds)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                ) == 0:
                    break
        except Exception:
            pass  # best-effort cosmetic touch; fine if unsupported

    def _on_callback_exception(self, exc_type, exc_value, exc_tb):
        # Tkinter callback errors otherwise print to stderr, which is invisible in the
        # --windowed exe (no console) - surface them instead of failing silently.
        import traceback

        traceback.print_exception(exc_type, exc_value, exc_tb)
        try:
            self.messagebox.showerror("KryptikClicks - unexpected error", f"{exc_type.__name__}: {exc_value}")
        except Exception:
            pass

    # --- styling ---
    def _configure_styles(self):
        c = self.COLORS
        s = self._style

        s.configure(
            "Field.TEntry",
            padding=8,
            relief="flat",
            fieldbackground=c["panel_bg"],
            foreground=c["text"],
            insertcolor=c["text"],
            bordercolor=c["border"],
            lightcolor=c["panel_bg"],
            darkcolor=c["panel_bg"],
        )
        s.map("Field.TEntry", bordercolor=[("focus", c["accent"])])

        s.configure(
            "Field.TCombobox",
            padding=6,
            relief="flat",
            fieldbackground=c["panel_bg"],
            background=c["panel_bg"],
            foreground=c["text"],
            arrowcolor=c["muted"],
            bordercolor=c["border"],
            lightcolor=c["panel_bg"],
            darkcolor=c["panel_bg"],
        )
        s.map(
            "Field.TCombobox",
            fieldbackground=[("readonly", c["panel_bg"])],
            foreground=[("readonly", c["text"])],
            bordercolor=[("focus", c["accent"])],
        )
        self.root.option_add("*TCombobox*Listbox.background", c["panel_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["text"])

        s.configure("TNotebook", background=c["bg"], borderwidth=0)
        s.configure(
            "TNotebook.Tab",
            background=c["bg"],
            foreground=c["muted"],
            padding=(16, 8),
            borderwidth=0,
            font=(self.FONT, 9, "bold"),
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", c["panel_bg"])],
            foreground=[("selected", c["accent"])],
        )

        for name, base, dark in (
            ("Accent", c["accent"], c["accent_dark"]),
            ("Start", c["green"], c["green_dark"]),
            ("Pause", c["amber"], c["amber_dark"]),
            ("Danger", c["panel_bg"], c["red"]),
        ):
            s.configure(
                f"{name}.TButton",
                background=base,
                foreground=c["text"] if name == "Danger" else "white",
                font=(self.FONT, 10, "bold"),
                padding=(10, 9),
                borderwidth=0,
                focuscolor=base,
            )
            s.map(
                f"{name}.TButton",
                background=[("active", dark), ("pressed", dark)],
                foreground=[("disabled", c["muted"])],
            )

    # --- UI construction ---
    def _build_ui(self, tk, ttk):
        c = self.COLORS
        FONT = self.FONT

        header = tk.Frame(self.root, bg=c["bg"])
        header.grid(row=0, column=0, sticky="we")

        title_row = tk.Frame(header, bg=c["bg"])
        title_row.pack(anchor="w", padx=20, pady=(18, 4))
        self._emblem_img = self._load_emblem()
        if self._emblem_img is not None:
            tk.Label(title_row, image=self._emblem_img, bg=c["bg"]).pack(side="left", padx=(0, 8))
        tk.Label(
            title_row, text="KryptikClicks", bg=c["bg"], fg=c["text"],
            font=(FONT, 14, "normal"),
        ).pack(side="left")

        self.status_var = tk.StringVar(value="● Idle")
        self.status_label = tk.Label(
            header, textvariable=self.status_var, bg=c["bg"], fg=c["muted"],
            font=(FONT, 9, "bold"),
        )
        self.status_label.pack(anchor="w", padx=20, pady=(0, 16))

        # Simple tab = everything needed for the common case (capture + start/stop);
        # Advanced tab = detection/scan tuning and numeric settings. Splitting these
        # keeps the default view approachable instead of showing every configuration
        # axis at once.
        notebook = ttk.Notebook(self.root, style="TNotebook")
        notebook.grid(row=1, column=0, sticky="we")
        simple_tab = tk.Frame(notebook, bg=c["bg"])
        advanced_tab = tk.Frame(notebook, bg=c["bg"])
        notebook.add(simple_tab, text="Simple")
        notebook.add(advanced_tab, text="Advanced")

        radio_kwargs = dict(
            bg=c["bg"], fg=c["text"], selectcolor=c["panel_bg"],
            activebackground=c["bg"], activeforeground=c["text"],
            highlightthickness=0, font=(FONT, 9),
        )

        # --- Simple tab ---
        self.summary_var = tk.StringVar(value="")
        tk.Label(
            simple_tab, textvariable=self.summary_var, bg=c["bg"], fg=c["text"],
            font=(FONT, 10), wraplength=400, justify="left",
        ).pack(anchor="w", padx=20, pady=(16, 14))

        tk.Label(simple_tab, text="MODE", bg=c["bg"], fg=c["muted"], font=(FONT, 8, "bold")).pack(
            anchor="w", padx=20, pady=(0, 6)
        )
        self.mode_var = tk.StringVar(value=self.cfg["click_mode"])
        tk.Radiobutton(
            simple_tab, text="Targeted - wait for a captured trigger image", variable=self.mode_var,
            value="targeted", command=self._on_mode_changed, **radio_kwargs,
        ).pack(anchor="w", padx=20)
        tk.Radiobutton(
            simple_tab, text="Generic - click on interval, no trigger needed", variable=self.mode_var,
            value="generic", command=self._on_mode_changed, **radio_kwargs,
        ).pack(anchor="w", padx=20)

        self.position_frame = tk.Frame(simple_tab, bg=c["bg"])
        self.position_frame.pack(fill="x", padx=20)
        self.position_var = tk.StringVar(value=self.cfg["click_position"])
        tk.Label(
            self.position_frame, text="Click position:", bg=c["bg"], fg=c["muted"], font=(FONT, 8)
        ).pack(anchor="w", pady=(6, 2))
        tk.Radiobutton(
            self.position_frame, text="Fixed point (captured below)", variable=self.position_var,
            value="fixed", command=self._on_click_position_changed, **radio_kwargs,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.position_frame, text="Current cursor position", variable=self.position_var,
            value="cursor", command=self._on_click_position_changed, **radio_kwargs,
        ).pack(anchor="w")

        self.template_var = tk.StringVar(value="No template captured yet.")
        self.template_label = tk.Label(
            simple_tab, textvariable=self.template_var, bg=c["bg"], fg=c["muted"],
            font=(FONT, 9), wraplength=380, justify="left",
        )
        self.template_label.pack(anchor="w", padx=20, pady=(10, 10))

        self.capture_var = tk.StringVar(value="Capture Template + Click Target...")
        ttk.Button(
            simple_tab, textvariable=self.capture_var, style="Accent.TButton",
            command=self.on_capture,
        ).pack(fill="x", padx=20, pady=(0, 10))

        btn_row = tk.Frame(simple_tab, bg=c["bg"])
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        self.toggle_btn = ttk.Button(
            btn_row, text="Start (F6)", style="Start.TButton", command=self.on_toggle
        )
        self.toggle_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(
            btn_row, text="Quit (F9)", style="Danger.TButton", command=self.on_quit
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        # --- Advanced tab ---
        self.detection_frame = tk.Frame(advanced_tab, bg=c["bg"])
        self.detection_frame.pack(fill="x", padx=20, pady=(16, 0))
        self.detection_method_var = tk.StringVar(value=self.cfg["detection_method"])
        self.detection_label = tk.Label(
            self.detection_frame, text="Detection method:", bg=c["bg"], fg=c["muted"], font=(FONT, 8),
            cursor="question_arrow",
        )
        self.detection_label.pack(anchor="w", pady=(6, 2))
        self._add_tooltip(
            self.detection_label,
            "How it recognizes the trigger. Image template match looks for the picture you "
            "captured. Color match learns the distinctive color inside your capture box and "
            "fires when enough pixels of it appear - better for colored text over a changing "
            "background. Applies immediately.",
        )
        tk.Radiobutton(
            self.detection_frame, text="Image template match", variable=self.detection_method_var,
            value="template", command=self._on_detection_method_changed, **radio_kwargs,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.detection_frame, text="Color match (e.g. distinctly colored text)",
            variable=self.detection_method_var, value="color",
            command=self._on_detection_method_changed, **radio_kwargs,
        ).pack(anchor="w")

        self.scan_scope_frame = tk.Frame(advanced_tab, bg=c["bg"])
        self.scan_scope_frame.pack(fill="x", padx=20)
        self.scan_scope_var = tk.StringVar(value=self.cfg["scan_scope"])
        self.scan_area_label = tk.Label(
            self.scan_scope_frame, text="Scan area:", bg=c["bg"], fg=c["muted"], font=(FONT, 8),
            cursor="question_arrow",
        )
        self.scan_area_label.pack(anchor="w", pady=(6, 2))
        self._add_tooltip(
            self.scan_area_label,
            "Where to look for the trigger: every monitor, or just one window (found by its "
            "title, so it follows the window if it moves). Limit to Region narrows that to part "
            "of the window. Applies immediately.",
        )
        tk.Radiobutton(
            self.scan_scope_frame, text="All monitors", variable=self.scan_scope_var,
            value="all_monitors", command=self._on_scan_scope_changed, **radio_kwargs,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.scan_scope_frame, text="Specific window", variable=self.scan_scope_var,
            value="window", command=self._on_scan_scope_changed, **radio_kwargs,
        ).pack(anchor="w")

        self.scan_window_title_var = tk.StringVar(value=self.cfg["scan_window_title"])
        self.scan_window_display_var = tk.StringVar(
            value=self._scan_window_display_text(self.cfg["scan_window_title"])
        )
        self.scan_window_row = tk.Frame(self.scan_scope_frame, bg=c["bg"])
        tk.Label(
            self.scan_window_row, textvariable=self.scan_window_display_var, bg=c["bg"],
            fg=c["muted"], font=(FONT, 9), wraplength=260, justify="left",
        ).pack(side="left")
        ttk.Button(
            self.scan_window_row, text="Choose Window...", command=self.on_choose_window,
        ).pack(side="right")

        self.scan_region_display_var = tk.StringVar(value=self._scan_region_display_text())
        self.scan_region_row = tk.Frame(self.scan_scope_frame, bg=c["bg"])
        tk.Label(
            self.scan_region_row, textvariable=self.scan_region_display_var, bg=c["bg"],
            fg=c["muted"], font=(FONT, 9), wraplength=200, justify="left",
        ).pack(side="left")
        ttk.Button(
            self.scan_region_row, text="Limit to Region...", command=self.on_define_scan_region,
        ).pack(side="right")
        clear_region_link = tk.Label(
            self.scan_region_row, text="Clear", bg=c["bg"], fg=c["accent"], font=(FONT, 8, "underline"),
            cursor="hand2",
        )
        clear_region_link.pack(side="right", padx=(0, 8))
        clear_region_link.bind("<Button-1>", lambda e: self.on_clear_scan_region())

        self.advanced_divider = tk.Frame(advanced_tab, bg=c["border"], height=1)
        self.advanced_divider.pack(fill="x", padx=20, pady=(10, 0))
        tk.Label(
            advanced_tab, text="SETTINGS", bg=c["bg"], fg=c["muted"], font=(FONT, 8, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        settings = tk.Frame(advanced_tab, bg=c["bg"])
        settings.pack(fill="x", padx=20)
        settings.grid_columnconfigure(1, weight=1)

        def settings_row(label_text, var, r, tooltip_text):
            label = tk.Label(
                settings, text=label_text, bg=c["bg"], fg=c["text"], font=(FONT, 9),
                cursor="question_arrow",
            )
            label.grid(row=r, column=0, sticky="w", pady=7)
            self._add_tooltip(label, tooltip_text)
            entry = ttk.Entry(settings, textvariable=var, width=8, style="Field.TEntry", justify="right")
            entry.grid(row=r, column=1, pady=7, sticky="e")
            return label, entry

        self.min_var = tk.StringVar(value=str(self.cfg["min_delay_ms"]))
        self.max_var = tk.StringVar(value=str(self.cfg["max_delay_ms"]))
        self.thr_var = tk.StringVar(value=str(self.cfg["match_threshold"]))
        settings_row(
            "Min delay (ms)", self.min_var, 0,
            "Shortest random pause between clicks while it's actively clicking. "
            "Each click waits a random time between Min and Max delay. Lower = faster clicking.",
        )
        settings_row(
            "Max delay (ms)", self.max_var, 1,
            "Longest random pause between clicks while it's actively clicking. "
            "Must be >= Min delay.",
        )
        self.trigger_min_var = tk.StringVar(value=str(self.cfg["trigger_delay_min_ms"]))
        self.trigger_max_var = tk.StringVar(value=str(self.cfg["trigger_delay_max_ms"]))
        self.trigger_delay_row_widgets = settings_row(
            "Trigger delay min (ms)", self.trigger_min_var, 2,
            "How long to wait after the trigger first appears before the first click - "
            "a random time between Trigger delay min and max, like a human reaction time. "
            "It only clicks if the trigger stays up for the whole wait. "
            "0 and 0 = click immediately. Targeted mode only.",
        ) + settings_row(
            "Trigger delay max (ms)", self.trigger_max_var, 3,
            "Longest wait after the trigger first appears before the first click. "
            "Must be >= Trigger delay min. Set both to the same value for a fixed delay.",
        )
        self.thr_row_widgets = settings_row(
            "Match threshold (0-1)", self.thr_var, 4,
            "How closely the screen must match your captured trigger image to fire "
            "clicking (1.0 = pixel-perfect match). Higher = stricter, fewer false triggers but "
            "may miss it if rendering shifts slightly. Lower = more lenient but may misfire on "
            "similar-looking content. 0.50 is a good default; raise it if it fires on the "
            "wrong thing, lower it if it doesn't fire at all. Only used by Image template match - "
            "Color match uses the color/pixel-count captured with the trigger instead.",
        )

        button_label = tk.Label(
            settings, text="Click button", bg=c["bg"], fg=c["text"], font=(FONT, 9),
            cursor="question_arrow",
        )
        button_label.grid(row=5, column=0, sticky="w", pady=7)
        self._add_tooltip(button_label, "Which mouse button to click with when the trigger is detected.")
        self.button_var = tk.StringVar(value=self.cfg["click_button"])
        ttk.Combobox(
            settings, textvariable=self.button_var, values=CLICK_BUTTONS, width=7,
            style="Field.TCombobox", state="readonly",
        ).grid(row=5, column=1, pady=7, sticky="e")

        self.limit_var = tk.StringVar(value=str(self.cfg["click_limit"]))
        settings_row(
            "Repeat limit (0 = infinite)", self.limit_var, 6,
            "Automatically pause after this many clicks. Set to 0 to keep clicking with "
            "no limit until you stop it manually.",
        )

        self.sound_var = tk.BooleanVar(value=self.cfg["sound_enabled"])
        self.sound_check = tk.Checkbutton(
            settings, text="Sound alert when it starts clicking", variable=self.sound_var,
            bg=c["bg"], fg=c["text"], selectcolor=c["panel_bg"], activebackground=c["bg"],
            activeforeground=c["text"], highlightthickness=0, font=(FONT, 9),
        )
        self.sound_check.grid(row=7, column=0, columnspan=2, sticky="w", pady=7)
        self._add_tooltip(
            self.sound_check,
            "Plays a short beep each time it starts clicking on a trigger (or when Generic "
            "mode starts clicking).",
        )

        self.auto_update_var = tk.BooleanVar(value=self.cfg["auto_update_check"])
        self.auto_update_check = tk.Checkbutton(
            settings, text="Check for updates automatically", variable=self.auto_update_var,
            bg=c["bg"], fg=c["text"], selectcolor=c["panel_bg"], activebackground=c["bg"],
            activeforeground=c["text"], highlightthickness=0, font=(FONT, 9),
        )
        self.auto_update_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=7)
        self._add_tooltip(
            self.auto_update_check,
            "When running the .exe, checks GitHub for a newer release on launch and offers to "
            "open the download page. It never installs anything by itself.",
        )

        ttk.Button(
            advanced_tab, text="Save Settings", style="Accent.TButton", command=self.on_save_settings
        ).pack(fill="x", padx=20, pady=(10, 16))

        # --- Shared (outside the tabs): Activity log + footer ---
        bottom = tk.Frame(self.root, bg=c["bg"])
        bottom.grid(row=2, column=0, sticky="we")

        tk.Frame(bottom, bg=c["border"], height=1).pack(fill="x", padx=20, pady=(4, 0))
        tk.Label(
            bottom, text="ACTIVITY", bg=c["bg"], fg=c["muted"], font=(FONT, 8, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        self.log_list = tk.Listbox(
            bottom, height=7, bg=c["panel_bg"], fg=c["muted_dark"], font=("Consolas", 9),
            bd=0, highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["border"],
            selectbackground=c["accent"], selectforeground=c["text"], activestyle="none",
        )
        self.log_list.pack(fill="x", padx=20, pady=(0, 16))

        tk.Label(
            bottom,
            text="F6 toggles start/pause, F9 quits — both work even while another window has focus.",
            bg=c["bg"], fg=c["muted"], font=(FONT, 8),
        ).pack(anchor="w", padx=20, pady=(0, 4))

        footer = tk.Frame(bottom, bg=c["bg"])
        footer.pack(fill="x", padx=20, pady=(0, 16))

        self.update_status_label = tk.Label(
            footer, text="", bg=c["bg"], fg=c["muted"], font=(FONT, 7),
        )
        self.update_status_label.pack(side="left")

        tk.Label(
            footer, text=f"v{__version__}", bg=c["bg"], fg=c["muted"], font=(FONT, 7),
        ).pack(side="right")

        check_updates_link = tk.Label(
            footer, text="Check for Updates", bg=c["bg"], fg=c["accent"], font=(FONT, 7, "underline"),
            cursor="hand2",
        )
        check_updates_link.pack(side="right", padx=(0, 10))
        check_updates_link.bind("<Button-1>", lambda e: self.on_check_updates())

        self._on_scan_scope_changed()
        self._on_detection_method_changed()
        self._on_mode_changed()
        self._maybe_auto_check_updates()

    def _on_mode_changed(self):
        # Commit immediately - this now lives on the Simple tab, and Save Settings is on
        # a different tab entirely, so a casual user would have no reason to look for it.
        self.cfg["click_mode"] = self.mode_var.get()
        save_config(self.cfg)
        # Detection method/Scan area are meaningless in Generic mode (Detector.ready/run()
        # never consult them there) - hide them so Advanced doesn't show inert controls.
        is_generic = self.mode_var.get() == "generic"
        if is_generic:
            self.detection_frame.pack_forget()
            self.scan_scope_frame.pack_forget()
        elif not self.detection_frame.winfo_manager():
            # A plain pack() after pack_forget() appends to the END of the tab (below
            # Save Settings) - put them back above the settings divider where they started.
            self.detection_frame.pack(fill="x", padx=20, pady=(16, 0), before=self.advanced_divider)
            self.scan_scope_frame.pack(fill="x", padx=20, before=self.advanced_divider)
        self._apply_settings_row_visibility()
        # The click-position choice (fixed point / current cursor) applies to
        # both modes, so it's always shown - only the trigger-capture
        # requirement (Targeted needs a template; Generic doesn't) differs.
        self._refresh_template_label()
        self._refresh_summary()

    def _threshold_applies(self):
        # Match threshold only means anything for image template matching - color
        # match uses the pixel count captured with the trigger, Generic has no trigger.
        return self.mode_var.get() == "targeted" and self.detection_method_var.get() == "template"

    def _trigger_delay_applies(self):
        return self.mode_var.get() == "targeted"  # Generic has no trigger to react to

    def _apply_settings_row_visibility(self):
        """Shows each Advanced settings row only where it does something - in one
        place, since it depends on both Mode and Detection method."""
        for widgets, shown in (
            (self.thr_row_widgets, self._threshold_applies()),
            (self.trigger_delay_row_widgets, self._trigger_delay_applies()),
        ):
            for widget in widgets:
                if shown:
                    widget.grid()
                else:
                    widget.grid_remove()

    def _on_click_position_changed(self):
        # Commit immediately - same reasoning as _on_mode_changed (Simple tab control).
        self.cfg["click_position"] = self.position_var.get()
        save_config(self.cfg)
        self._refresh_template_label()
        self._refresh_summary()

    def _on_detection_method_changed(self):
        # Commit immediately, matching _on_scan_scope_changed's existing pattern.
        self.cfg["detection_method"] = self.detection_method_var.get()
        save_config(self.cfg)
        self._apply_settings_row_visibility()
        self._refresh_template_label()
        self._refresh_summary()

    def _on_scan_scope_changed(self):
        # Commit immediately (like on_capture already does for click_mode/click_position/
        # detection_method) rather than waiting for a separate Save Settings click - the
        # UI otherwise looks live (the visible row toggles right away) while scanning
        # would silently keep using the old scope until Save Settings was pressed.
        self.cfg["scan_scope"] = self.scan_scope_var.get()
        save_config(self.cfg)
        if self.scan_scope_var.get() == "window":
            self.scan_window_row.pack(fill="x", pady=(4, 0))
            self.scan_region_row.pack(fill="x", pady=(4, 0))
        else:
            self.scan_window_row.pack_forget()
            self.scan_region_row.pack_forget()
        self._refresh_summary()

    def _scan_window_display_text(self, title):
        if not title:
            return "No window selected."
        try:
            open_titles = {t for _, t in list_visible_windows()}
        except Exception:
            open_titles = set()
        if title in open_titles:
            return f'Target: "{title}"'
        return f'Target: "{title}" (not currently open)'

    def _scan_region_display_text(self):
        sr = self.cfg.get("scan_region")
        if not sr:
            return "Scanning the whole window."
        return f"Scan region: {sr['width']}x{sr['height']}px within the window."

    def on_define_scan_region(self):
        title = self.scan_window_title_var.get()
        if not title:
            self.messagebox.showwarning("No window selected", "Choose a window first.")
            return
        hwnd = find_window_by_title(list_visible_windows(), title)
        if hwnd is None:
            self.messagebox.showwarning(
                "Window not found", f'"{title}" isn\'t currently open - open it, then try again.'
            )
            return
        window_rect = get_window_rect(hwnd)

        # Pause like on_capture does: the overlay is a frozen snapshot that can still
        # show the trigger, and clicking would land mid-drag.
        was_scanning = self.detector.scanning_active.is_set()
        self.detector.pause_scanning()
        self.root.withdraw()
        try:
            box, _, full_img = run_capture_ui(
                parent=self.root, require_click_point=False,
                label_text="Drag a box around the area to scan (e.g. just the game viewport, "
                            "excluding sidebars/menus). Esc to cancel.",
            )
        finally:
            if not self._quitting:
                self.root.deiconify()
                if was_scanning and self.detector.ready:
                    self.detector.resume_scanning()
        if self._quitting:
            return  # F9 during the overlay - the window is already gone
        if box is None:
            self.log("Scan region selection cancelled.")
            return

        import mss
        with mss.mss() as sct:
            virtual = sct.monitors[0]
        box_abs = (
            box[0] + virtual["left"], box[1] + virtual["top"],
            box[2] + virtual["left"], box[3] + virtual["top"],
        )
        self.cfg["scan_region"] = compute_scan_region_offset(box_abs, window_rect)
        save_config(self.cfg)
        self.scan_region_display_var.set(self._scan_region_display_text())
        sr = self.cfg["scan_region"]
        self.log(f"Scan region set: {sr['width']}x{sr['height']}px within the tracked window.")
        self._refresh_summary()

    def on_clear_scan_region(self):
        self.cfg["scan_region"] = None
        save_config(self.cfg)
        self.scan_region_display_var.set(self._scan_region_display_text())
        self.log("Scan region cleared - scanning the whole window again.")
        self._refresh_summary()

    def on_choose_window(self):
        import ctypes
        from tkinter import ttk

        tk = self.tk
        c = self.COLORS
        FONT = self.FONT

        picker = tk.Toplevel(self.root)
        picker.title("Choose a window")
        picker.configure(bg=c["bg"])
        picker.transient(self.root)
        picker.grab_set()
        self._enable_dark_titlebar(picker)

        # No clicking while picking (cursor mode would click on the picker itself);
        # resume once it closes, however it closes.
        was_scanning = self.detector.scanning_active.is_set()
        self.detector.pause_scanning()

        def on_picker_closed(event):
            if event.widget is picker and was_scanning and self.detector.ready:
                self.detector.resume_scanning()

        picker.bind("<Destroy>", on_picker_closed)

        canvas = tk.Canvas(picker, bg=c["bg"], highlightthickness=0, width=560, height=420)
        scrollbar = ttk.Scrollbar(picker, orient="vertical", command=canvas.yview)
        grid_frame = tk.Frame(canvas, bg=c["bg"])
        grid_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=grid_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", pady=10)

        button_row = tk.Frame(picker, bg=c["bg"])
        button_row.pack(fill="x", padx=10, pady=(0, 10))
        thumb_refs = []  # keep PhotoImage references alive for the picker's lifetime

        def select(title):
            self.scan_window_title_var.set(title)
            self.scan_window_display_var.set(self._scan_window_display_text(title))
            # Commit immediately (see _on_scan_scope_changed) - the display updates right
            # away just like a completed capture does, so this must actually take effect
            # right away too, not silently wait for a separate Save Settings click.
            self.cfg["scan_window_title"] = title
            save_config(self.cfg)
            self._refresh_summary()
            picker.destroy()

        def populate():
            for widget in grid_frame.winfo_children():
                widget.destroy()
            thumb_refs.clear()

            main_hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            picker_hwnd = ctypes.windll.user32.GetParent(picker.winfo_id()) or picker.winfo_id()
            windows = [
                w for w in list_visible_windows(exclude_hwnd=main_hwnd) if w[0] != picker_hwnd
            ]

            if not windows:
                tk.Label(
                    grid_frame, text="No other windows found. Open the app you want to\n"
                    "monitor, then click Refresh.", bg=c["bg"], fg=c["muted"], font=(FONT, 9),
                    justify="left",
                ).grid(row=0, column=0, padx=10, pady=10, sticky="w")
                return

            cols = 3
            from PIL import ImageTk
            for i, (hwnd, title) in enumerate(windows):
                cell = tk.Frame(grid_frame, bg=c["panel_bg"], cursor="hand2")
                cell.grid(row=i // cols, column=i % cols, padx=6, pady=6)
                img = capture_window_thumbnail(hwnd)
                if img is not None:
                    photo = ImageTk.PhotoImage(img, master=picker)
                    thumb_refs.append(photo)
                    thumb_label = tk.Label(cell, image=photo, bg=c["panel_bg"])
                else:
                    thumb_label = tk.Label(
                        cell, text="(preview unavailable)", bg=c["panel_bg"], fg=c["muted"],
                        width=20, height=6,
                    )
                thumb_label.pack(padx=4, pady=(4, 2))
                name_label = tk.Label(
                    cell, text=title, bg=c["panel_bg"], fg=c["text"], font=(FONT, 8),
                    wraplength=150,
                )
                name_label.pack(padx=4, pady=(0, 4))
                for widget in (cell, thumb_label, name_label):
                    widget.bind("<Button-1>", lambda e, t=title: select(t))

        ttk.Button(button_row, text="Refresh", command=populate).pack(side="left")
        ttk.Button(button_row, text="Cancel", command=picker.destroy).pack(side="right")

        populate()

    def _add_tooltip(self, widget, text):
        tk = self.tk
        c = self.COLORS
        state = {"win": None}

        def show(_event=None):
            if state["win"] is not None:
                return
            x = widget.winfo_rootx() + 4
            y = widget.winfo_rooty() + widget.winfo_height() + 6
            win = tk.Toplevel(widget)
            win.wm_overrideredirect(True)
            win.wm_geometry(f"+{x}+{y}")
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
            tk.Label(
                win, text=text, bg=c["panel_bg"], fg=c["muted_dark"], font=(self.FONT, 8),
                wraplength=260, justify="left", padx=9, pady=7,
                highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["border"],
            ).pack()
            state["win"] = win

        def hide(_event=None):
            if state["win"] is not None:
                state["win"].destroy()
                state["win"] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def _refresh_template_label(self):
        # Reflects the mode/position/detection-method currently selected in the form
        # (which may not be saved yet) - same "preview before Save" behavior as the
        # other settings fields.
        mode = self.mode_var.get()
        cursor_position = self.position_var.get() == "cursor"
        color_mode = self.detection_method_var.get() == "color"
        needs_template = mode == "targeted"
        needs_point = not cursor_position

        if not needs_template:
            what = "Click Target"  # Generic: capture only ever sets the click point
        elif needs_point:
            what = "Trigger + Click Target"
        else:
            what = "Trigger"
        capture_label, recapture_label = f"Capture {what}...", f"Recapture {what}..."

        if not needs_template and not needs_point:
            self.template_var.set("Cursor mode selected - no capture needed. It'll click wherever your mouse is.")
            self.capture_var.set(capture_label)
            return

        have_trigger = (
            self.cfg.get("target_color") is not None if color_mode else self.detector.template is not None
        )
        have_point = self.detector.click_x is not None
        ready_for_mode = (not needs_template or have_trigger) and (not needs_point or have_point)

        if ready_for_mode:
            if color_mode:
                trigger_desc = f"color RGB{tuple(self.cfg['target_color'])}"
            else:
                trigger_desc = f"{self.detector.t_w}x{self.detector.t_h}px template"
            if not needs_point:
                self.template_var.set(
                    f"Using saved trigger: {trigger_desc}. "
                    f"Clicks wherever your mouse is when it's detected."
                )
            elif not needs_template:
                self.template_var.set(f"Using saved click point ({self.detector.click_x}, {self.detector.click_y}).")
            else:
                self.template_var.set(
                    f"Using saved capture: {trigger_desc}, "
                    f"click target ({self.detector.click_x}, {self.detector.click_y}). "
                    f"Reused automatically — recapture only if it stops matching."
                )
            self.capture_var.set(recapture_label)
        elif not needs_template:
            self.template_var.set("No click point captured yet - click below to set it (one-time).")
            self.capture_var.set(capture_label)
        else:
            self.template_var.set("No trigger captured yet - click below to set it up (one-time).")
            self.capture_var.set(capture_label)

    def _refresh_summary(self):
        captured_desc = (
            "the color you captured" if self.cfg.get("detection_method") == "color"
            else "the picture you captured"
        )
        self.summary_var.set(describe_current_setup(self.cfg, self.detector.ready, captured_desc))

    def _refresh_status(self):
        c = self.COLORS
        if self.detector.scanning_active.is_set():
            self.status_var.set(f"● Scanning ({self.detector.total_clicks} clicks)")
            self.status_label.config(fg=c["green"])
            self.toggle_btn.config(text="Pause (F6)", style="Pause.TButton")
        else:
            ready = self.detector.ready
            self.status_var.set("● Idle" if ready else "● Not ready")
            self.status_label.config(fg=(c["muted"] if ready else c["red"]))
            self.toggle_btn.config(text="Start (F6)", style="Start.TButton")

    def _poll_status(self):
        self._refresh_status()
        self.root.after(300, self._poll_status)

    def _on_ui_thread(self, fn, *args):
        """Runs fn(*args) on the Tk thread, from any thread. Tk calls from other
        threads (even root.after) block until the Tk thread gets round to them - so a
        busy UI would stall the detector and delay its clicks - and raise once the
        mainloop isn't running. Other threads hand calls over through a queue instead."""
        if threading.current_thread() is threading.main_thread():
            self.root.after(0, fn, *args)
        else:
            self._ui_calls.put((fn, args))

    def _drain_ui_calls(self):
        # Once quitting, the window is (being) destroyed: anything still queued - e.g.
        # the worker's "Stopped clicking" log right after F9 - has nothing to update.
        if self._quitting:
            return
        # Reschedule first, so one failing call (reported by Tk) can't stop the pump.
        self.root.after(UI_QUEUE_POLL_MS, self._drain_ui_calls)
        while not self._quitting:
            try:
                fn, args = self._ui_calls.get_nowait()
            except queue.Empty:
                return
            fn(*args)

    def log(self, msg):
        self._on_ui_thread(self._log_ui, msg)

    def _log_ui(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_list.insert("end", f"[{ts}] {msg}")
        self.log_list.yview_moveto(1.0)
        if self.log_list.size() > 200:
            self.log_list.delete(0)

    # --- actions ---
    def on_capture(self):
        was_scanning = self.detector.scanning_active.is_set()
        self.detector.pause_scanning()
        # The capture flow (how many steps, whether a click point is needed)
        # depends on the currently selected mode/position - apply those now
        # rather than leaving them as an unsaved preview, so Detector.ready
        # reflects reality immediately after capturing instead of requiring
        # a separate "Save Settings" click first.
        self.cfg["click_mode"] = self.mode_var.get()
        self.cfg["click_position"] = self.position_var.get()
        self.cfg["detection_method"] = self.detection_method_var.get()
        save_config(self.cfg)
        # Generic mode has no trigger - capture only the click point, and leave the
        # saved Targeted trigger (template/color calibration) untouched.
        capture_trigger = self.mode_var.get() == "targeted"
        require_point = not capture_trigger or self.position_var.get() != "cursor"
        self.root.withdraw()
        try:
            box, point, full_img = run_capture_ui(
                parent=self.root, require_click_point=require_point, require_trigger=capture_trigger,
            )
        finally:
            if not self._quitting:
                self.root.deiconify()
        if self._quitting:
            return  # F9 during the overlay - the window is already gone
        if box is None and point is None:
            self.log("Capture cancelled.")
        elif not capture_trigger:
            save_click_point(point)
            self.detector.load()
            self._refresh_template_label()
            self.log(f"Captured new click target {point}.")
        else:
            save_capture(box, point, full_img)
            if self.cfg["detection_method"] == "color":
                target_color, pixel_count = analyze_color_trigger(
                    full_img.crop(box), tolerance=self.cfg["color_tolerance"],
                )
                self.cfg["target_color"] = list(target_color)
                self.cfg["min_color_pixels"] = max(1, int(pixel_count * COLOR_MATCH_FRACTION))
                save_config(self.cfg)
                trigger_desc = f"color RGB{target_color}"
            else:
                trigger_desc = "template"
            self.detector.load()
            self._refresh_template_label()
            if point is not None:
                self.log(f"Captured new {trigger_desc} trigger + click target {point}.")
            else:
                self.log(f"Captured new {trigger_desc} trigger.")
        if was_scanning and self.detector.ready:
            self.detector.resume_scanning()
        self._refresh_status()
        self._refresh_summary()

    def on_toggle(self):
        if self.detector.scanning_active.is_set():
            self.detector.pause_scanning()
            self.log("Paused.")
        else:
            if not self.detector.ready:
                if self.mode_var.get() == "generic":
                    needed = "click target"
                elif self.position_var.get() == "cursor":
                    needed = "trigger"
                else:
                    needed = "trigger and click target"
                self.messagebox.showwarning("Not ready", f"Capture a {needed} first.")
                return
            self.detector.start_scanning()
            self.log("Scanning started.")
        self._refresh_status()

    def on_save_settings(self):
        # A hidden field keeps its saved value - an invalid leftover in a field the
        # user can't currently see mustn't block saving everything else.
        thr = self.thr_var.get() if self._threshold_applies() else str(self.cfg["match_threshold"])
        if self._trigger_delay_applies():
            trigger_min, trigger_max = self.trigger_min_var.get(), self.trigger_max_var.get()
        else:
            trigger_min = str(self.cfg["trigger_delay_min_ms"])
            trigger_max = str(self.cfg["trigger_delay_max_ms"])
        try:
            parsed = parse_settings_input(
                self.min_var.get(), self.max_var.get(), thr, self.limit_var.get(),
                trigger_min_str=trigger_min, trigger_max_str=trigger_max,
            )
        except ValueError as e:
            self.messagebox.showerror("Invalid settings", str(e))
            return
        self.cfg.update(parsed)
        self.cfg["click_button"] = self.button_var.get()
        self.cfg["click_mode"] = self.mode_var.get()
        self.cfg["click_position"] = self.position_var.get()
        self.cfg["detection_method"] = self.detection_method_var.get()
        self.cfg["sound_enabled"] = bool(self.sound_var.get())
        self.cfg["auto_update_check"] = bool(self.auto_update_var.get())
        self.cfg["scan_scope"] = self.scan_scope_var.get()
        self.cfg["scan_window_title"] = self.scan_window_title_var.get()
        save_config(self.cfg)
        self._refresh_status()
        self._refresh_template_label()
        self._refresh_summary()
        self.log("Settings saved.")

    def _maybe_auto_check_updates(self):
        if not getattr(sys, "frozen", False) or not self.cfg.get("auto_update_check", True):
            return
        self.root.after(1500, lambda: self._run_update_check(silent=True))

    def on_check_updates(self):
        if not getattr(sys, "frozen", False):
            self.messagebox.showinfo(
                "Running from source",
                "You're running KryptikClicks from source, not the built exe - "
                "use `git pull` to get the latest changes.",
            )
            return
        self.update_status_label.config(text="Checking for updates...")
        self._run_update_check(silent=False)

    def _run_update_check(self, silent):
        def worker():
            # Always report back - otherwise "Checking for updates..." stays up forever.
            try:
                update, failed = check_for_update(__version__), False
            except Exception:
                update, failed = None, True
            self._on_ui_thread(self._on_update_check_done, update, silent, failed)

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, update, silent, failed=False):
        if failed:
            self.update_status_label.config(text="" if silent else "Couldn't check for updates.")
            return
        if update is None:
            self.update_status_label.config(text="" if silent else "You're up to date.")
            return
        self.update_status_label.config(text=f"{update['version']} is available.")
        if self.messagebox.askyesno(
            "Update available",
            f"KryptikClicks {update['version']} is available (you have v{__version__}).\n\n"
            f"{update['notes']}\n\nOpen the download page in your browser?",
        ):
            import webbrowser
            webbrowser.open(update["download_url"])

    def on_quit(self):
        # F9 can arrive while a capture overlay's nested event loop is running; the
        # flow that opened it checks this before touching the destroyed window.
        self._quitting = True
        self.detector.stop_event.set()
        self.detector.pause_scanning()
        self.listener.stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="KryptikClicks")
    parser.add_argument(
        "--capture", action="store_true", help="Capture the template/click-target from a terminal (no GUI)"
    )
    parser.add_argument(
        "--headless", action="store_true", help="Run the watcher from a terminal, no GUI"
    )
    parser.add_argument("--version", action="version", version=f"KryptikClicks {__version__}")
    args = parser.parse_args()

    check_dependencies()

    if args.capture:
        capture_template_cli()
    elif args.headless:
        run_headless()
    else:
        KryptikClicksGUI()


if __name__ == "__main__":
    main()
