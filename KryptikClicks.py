"""
KryptikClicks
-----------------------
Watches the screen for a trigger image you capture (any text, icon, or button
— found anywhere on screen, via template image matching) and, for as long as
it stays visible, repeatedly clicks a fixed point you chose during capture
(not the trigger itself) with a randomized delay between clicks.

Setup:
    pip install opencv-python mss numpy pyautogui pynput

Usage:
    python KryptikClicks.py             # open the settings window (default)
    python KryptikClicks.py --capture   # capture the template/target from a terminal, no GUI
    python KryptikClicks.py --headless  # run the watcher from a terminal, no GUI

Hotkeys (global, work even without the window focused):
    F6  - toggle scanning/clicking on and off
    F9  - quit
"""

import sys
import os
import json
import random
import threading
import time
import argparse

__version__ = "1.5.3"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """Resolves a bundled asset path, working both from source and from a
    PyInstaller --onefile exe (where bundled data is extracted to sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", SCRIPT_DIR)
    return os.path.join(base, *parts)


TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "trigger_template.png")
TARGET_PATH = os.path.join(SCRIPT_DIR, "click_target.txt")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "kryptikclicks_config.json")

# --- Defaults (overridden by kryptikclicks_config.json / the settings window) -----
DEFAULT_CONFIG = {
    "min_delay_ms": 50,
    "max_delay_ms": 150,
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
    "color_tolerance": 30,
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
TOGGLE_HOTKEY = "f6"
QUIT_HOTKEY = "f9"
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = ["cv2", "mss", "numpy", "pyautogui", "pynput", "PIL"]
PIP_INSTALL_CMD = "pip install opencv-python mss numpy pyautogui pynput Pillow"


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


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
    if cfg.get("click_button") not in CLICK_BUTTONS:
        cfg["click_button"] = DEFAULT_CONFIG["click_button"]
    if cfg.get("click_mode") not in CLICK_MODES:
        cfg["click_mode"] = DEFAULT_CONFIG["click_mode"]
    if cfg.get("click_position") not in CLICK_POSITIONS:
        cfg["click_position"] = DEFAULT_CONFIG["click_position"]
    if not isinstance(cfg.get("click_limit"), (int, float)) or cfg["click_limit"] < 0:
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
        or not all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in target_color)
    ):
        cfg["target_color"] = DEFAULT_CONFIG["target_color"]
    if not isinstance(cfg.get("color_tolerance"), (int, float)) or cfg["color_tolerance"] < 0:
        cfg["color_tolerance"] = DEFAULT_CONFIG["color_tolerance"]
    if not isinstance(cfg.get("min_color_pixels"), (int, float)) or cfg["min_color_pixels"] < 0:
        cfg["min_color_pixels"] = DEFAULT_CONFIG["min_color_pixels"]
    scan_region = cfg.get("scan_region")
    if scan_region is not None and (
        not isinstance(scan_region, dict)
        or set(scan_region.keys()) != {"left", "top", "width", "height"}
        or not all(isinstance(v, (int, float)) for v in scan_region.values())
        or scan_region["width"] <= 0
        or scan_region["height"] <= 0
    ):
        cfg["scan_region"] = DEFAULT_CONFIG["scan_region"]

    def is_number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    min_ms, max_ms, thr = cfg.get("min_delay_ms"), cfg.get("max_delay_ms"), cfg.get("match_threshold")
    if not is_number(min_ms) or not is_number(max_ms) or min_ms < 0 or max_ms < min_ms:
        cfg["min_delay_ms"] = DEFAULT_CONFIG["min_delay_ms"]
        cfg["max_delay_ms"] = DEFAULT_CONFIG["max_delay_ms"]
    if not is_number(thr) or not (0.0 < thr <= 1.0):
        cfg["match_threshold"] = DEFAULT_CONFIG["match_threshold"]
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


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
    downloadable .exe asset, else None."""
    tag = release.get("tag_name")
    if not tag or not is_newer_version(tag, current_version):
        return None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            return {
                "version": tag,
                "download_url": asset.get("browser_download_url"),
                "notes": release.get("body", ""),
            }
    return None


def fetch_latest_release():
    """Fetches the latest GitHub release info. Returns the parsed JSON dict, or None on
    any network/parsing error - being offline or rate-limited shouldn't crash the app."""
    import urllib.request

    try:
        req = urllib.request.Request(
            GITHUB_LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


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


def analyze_color_trigger(crop_img):
    """Given a PIL image crop of the drag-selected trigger, extracts the
    dominant non-background (distinctly colored, not-too-dark) color and how
    many pixels in the crop matched it - the reference signal 'color'
    detection_method looks for during scanning, instead of image template
    correlation. Falls back to treating the whole crop as the target color if
    nothing clears the saturation/brightness floor (e.g. a solid-color
    capture)."""
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
    pixel_count = int(count_color_pixels(rgb, target_color, DEFAULT_CONFIG["color_tolerance"]).sum())
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
    absolute position. Returns window_rect unchanged if scan_region is None
    (meaning "scan the whole window")."""
    if not scan_region:
        return window_rect
    return {
        "left": window_rect["left"] + scan_region["left"],
        "top": window_rect["top"] + scan_region["top"],
        "width": scan_region["width"],
        "height": scan_region["height"],
    }


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


def run_capture_ui(parent=None, require_click_point=True, label_text=None):
    """Shows the capture overlay: drag-select the trigger image, then
    (if require_click_point) click the spot to auto-click. Pass require_click_point=False
    to skip that second step - used when the click position will be the live cursor
    position instead of a captured point. Pass label_text to override the default
    step-1 instructions (e.g. reusing this same drag-select flow for defining a
    scan region instead of a trigger).

    On multi-monitor setups this shows one overlay window per physical monitor
    (each sized to just that monitor) rather than one giant window spanning
    the whole virtual desktop - a single override-redirect window sized to
    span multiple monitors was found to not actually get painted by Windows'
    compositor, leaving an invisible-but-topmost dead zone. Per-monitor
    windows are normal-sized and render reliably, and the drag/click can
    start on whichever monitor the mouse is already on.

    Returns (template_box, target_point, full_img), or (None, None, None) if cancelled.
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

    state = {
        "phase": 1, "start": None, "start_mon": None, "rect": None, "rect_canvas": None,
        "template_box": None, "target_point": None, "done": False,
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

    if state["template_box"] is None:
        return None, None, None
    return state["template_box"], state["target_point"], full_img


def save_capture(template_box, target_point, full_img):
    crop = full_img.crop(template_box)
    crop.save(TEMPLATE_PATH)
    if target_point is not None:
        with open(TARGET_PATH, "w") as f:
            f.write(f"{target_point[0]},{target_point[1]}\n")
    return crop.width, crop.height


def capture_template_cli():
    box, point, full_img = run_capture_ui(parent=None)
    if box is None:
        print("Capture cancelled.")
        sys.exit(1)
    w, h = save_capture(box, point, full_img)
    print(f"Saved template ({w}x{h}) to {TEMPLATE_PATH}")
    print(f"Saved click target {point} to {TARGET_PATH}")


def parse_settings_input(min_ms_str, max_ms_str, thr_str, click_limit_str):
    """Parses/validates the settings-form text fields. Raises ValueError with a
    user-facing message on invalid input; otherwise returns the parsed values."""
    try:
        min_ms = float(min_ms_str)
        max_ms = float(max_ms_str)
        thr = float(thr_str)
        click_limit = int(float(click_limit_str))
    except ValueError:
        raise ValueError("Enter valid numbers.")
    if min_ms < 0 or max_ms < min_ms:
        raise ValueError("Min delay must be >= 0 and <= max delay.")
    if not (0.0 < thr <= 1.0):
        raise ValueError("Threshold must be between 0 and 1.")
    if click_limit < 0:
        raise ValueError("Click limit must be 0 (infinite) or a positive number.")
    return {
        "min_delay_ms": min_ms,
        "max_delay_ms": max_ms,
        "match_threshold": thr,
        "click_limit": click_limit,
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

    def start_scanning(self):
        self.total_clicks = 0
        self.scanning_active.set()

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
        frame = np.array(shot)  # BGRA
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
        frame = np.array(shot)  # BGRA
        rgb = frame[:, :, [2, 1, 0]]
        mask = count_color_pixels(rgb, self.cfg["target_color"], self.cfg.get("color_tolerance", 30))
        count = int(mask.sum())
        if count == 0:
            return region["left"], region["top"], 0
        ys, xs = np.nonzero(mask)
        x = region["left"] + int(xs.mean())
        y = region["top"] + int(ys.mean())
        return x, y, count

    def _score_threshold(self):
        if self.cfg.get("detection_method") == "color":
            return self.cfg.get("min_color_pixels", DEFAULT_CONFIG["min_color_pixels"])
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
        target app may have been restarted, getting a new hwnd) rather than
        caching it long-term. status is "ok", "minimized", or "not_found" - the
        latter two mean regions is empty, meaning there's nothing to scan this
        tick (idle, not a miss)."""
        if self.cfg.get("scan_scope") != "window":
            monitors = sct.monitors[1:] or [sct.monitors[0]]
            return monitors, None, "ok"

        hwnd = cached_hwnd
        if hwnd is None or not is_window_valid(hwnd):
            hwnd = find_window_by_title(list_visible_windows(), self.cfg.get("scan_window_title", ""))
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

    def run(self):
        """Blocks, running the scan/click loop until stop_event is set."""
        import pyautogui
        import concurrent.futures

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0  # we control click timing ourselves

        # mss accumulates Windows GDI resources over a long-running capture loop and
        # gradually slows down; periodically recreating it keeps capture speed steady.
        MSS_REFRESH_INTERVAL = 300
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

        def scan_tick():
            nonlocal sct, scan_count
            scan_count += 1
            if scan_count % MSS_REFRESH_INTERVAL == 0:
                sct.close()
                sct = self.mss.mss()

        def safe_find_match(region):
            # A transient capture/match error shouldn't permanently kill background
            # detection - log it (rate-limited) and treat the frame as a miss.
            nonlocal last_error_log
            try:
                return self._find_match_in(sct, region)
            except Exception as e:
                now = time.monotonic()
                if now - last_error_log > 5.0:
                    self.log(f"Scan error (continuing): {e}")
                    last_error_log = now
                return None

        def safe_score_threaded(region):
            # mss instances aren't thread-safe, so each worker thread grabs its own.
            nonlocal last_error_log
            try:
                with self.mss.mss() as thread_sct:
                    return self._match_score_in(thread_sct, region)
            except Exception as e:
                now = time.monotonic()
                if now - last_error_log > 5.0:
                    self.log(f"Scan error (continuing): {e}")
                    last_error_log = now
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

        def sleep_between_clicks():
            min_d = self.cfg["min_delay_ms"] / 1000.0
            max_d = self.cfg["max_delay_ms"] / 1000.0
            time.sleep(random.uniform(min_d, max_d))

        def click_and_check_limit():
            """Clicks once; if that hits the configured limit, pauses and returns True."""
            self._click_once()
            if self._limit_reached():
                self.log(f"Reached click limit ({self.total_clicks}); stopping.")
                self.pause_scanning()
                return True
            return False

        try:
            while not self.stop_event.is_set():
                if not (self.scanning_active.is_set() and self.ready):
                    time.sleep(SCAN_INTERVAL)
                    continue

                if self.cfg.get("click_mode", "targeted") == "generic":
                    # No trigger to wait for - click on interval for as long as it's active.
                    self._beep()
                    while self.scanning_active.is_set() and not self.stop_event.is_set():
                        if click_and_check_limit():
                            break
                        sleep_between_clicks()
                    continue

                scan_tick()
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
                    time.sleep(SCAN_INTERVAL)
                    continue

                match, hit_region = scan_regions(regions)
                if match is None:
                    time.sleep(SCAN_INTERVAL)
                    continue

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
                        while match is not None and self.scanning_active.is_set() and not self.stop_event.is_set():
                            if time.monotonic() - wait_start > self.CURSOR_MODE_MAX_WAIT_SECONDS:
                                timed_out = True
                                break
                            time.sleep(SCAN_INTERVAL)
                            scan_tick()
                            match = safe_find_match(self._local_region_around(match[0], match[1], hit_region))
                        if timed_out:
                            continue  # still (probably) there - click again rather than wait longer
                        break
                    if burst_clicks >= self.MAX_CLICKS_PER_BURST:
                        break  # force a fresh full-region scan instead of trusting a stale local match
                    sleep_between_clicks()
                    scan_tick()
                    match = safe_find_match(self._local_region_around(match[0], match[1], hit_region))
                self.log(f"Stopped clicking ({self.total_clicks} clicks this session).")
        finally:
            executor.shutdown(wait=False)
            sct.close()


HOTKEY_DEBOUNCE_SECONDS = 0.3


class HotkeyListener:
    """Debounces held-key repeats and dispatches mapped hotkey actions.

    `hotkey_map` maps a key value to a zero-arg callback. `on_press`/`on_release`
    are meant to be handed straight to `pynput.keyboard.Listener`. A held key
    (repeat presses without an intervening release) never re-fires, and a
    released-then-re-pressed key is still subject to a debounce window so two
    genuine presses in quick succession don't double-fire.

    `dispatch`, if given, receives the action callable instead of the listener
    calling it directly - e.g. to marshal it onto another thread with
    `lambda action: self.root.after(0, action)`.
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

    detector = Detector(load_config())
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
        "accent": "#5865f2",
        "accent_dark": "#4752c4",
        "green": "#23a55a",
        "green_dark": "#1a8045",
        "amber": "#f0b232",
        "amber_dark": "#d1971e",
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

        self.cfg = load_config()
        self.detector = Detector(self.cfg, log=self.log)

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

        # Global hotkeys (F6/F9) work even while another window has focus.
        # Fired on the pynput listener thread - dispatch marshals the action onto the GUI thread.
        self.hotkey_map = {
            pynkeyboard.Key[TOGGLE_HOTKEY]: self.on_toggle,
            pynkeyboard.Key[QUIT_HOTKEY]: self.on_quit,
        }
        self.hotkeys = HotkeyListener(self.hotkey_map, dispatch=lambda action: self.root.after(0, action))
        self.listener = pynkeyboard.Listener(on_press=self.hotkeys.on_press, on_release=self.hotkeys.on_release)
        self.listener.start()

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

        body = tk.Frame(self.root, bg=c["bg"])
        body.grid(row=1, column=0, sticky="we")

        radio_kwargs = dict(
            bg=c["bg"], fg=c["text"], selectcolor=c["panel_bg"],
            activebackground=c["bg"], activeforeground=c["text"],
            highlightthickness=0, font=(FONT, 9),
        )

        tk.Label(body, text="MODE", bg=c["bg"], fg=c["muted"], font=(FONT, 8, "bold")).pack(
            anchor="w", padx=20, pady=(14, 6)
        )
        self.mode_var = tk.StringVar(value=self.cfg["click_mode"])
        tk.Radiobutton(
            body, text="Targeted - wait for a captured trigger image", variable=self.mode_var,
            value="targeted", command=self._on_mode_changed, **radio_kwargs,
        ).pack(anchor="w", padx=20)
        tk.Radiobutton(
            body, text="Generic - click on interval, no trigger needed", variable=self.mode_var,
            value="generic", command=self._on_mode_changed, **radio_kwargs,
        ).pack(anchor="w", padx=20)

        self.position_frame = tk.Frame(body, bg=c["bg"])
        self.position_frame.pack(fill="x", padx=20)
        self.position_var = tk.StringVar(value=self.cfg["click_position"])
        tk.Label(
            self.position_frame, text="Click position:", bg=c["bg"], fg=c["muted"], font=(FONT, 8)
        ).pack(anchor="w", pady=(6, 2))
        tk.Radiobutton(
            self.position_frame, text="Fixed point (captured below)", variable=self.position_var,
            value="fixed", command=self._refresh_template_label, **radio_kwargs,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.position_frame, text="Current cursor position", variable=self.position_var,
            value="cursor", command=self._refresh_template_label, **radio_kwargs,
        ).pack(anchor="w")

        self.detection_frame = tk.Frame(body, bg=c["bg"])
        self.detection_frame.pack(fill="x", padx=20)
        self.detection_method_var = tk.StringVar(value=self.cfg["detection_method"])
        tk.Label(
            self.detection_frame, text="Detection method:", bg=c["bg"], fg=c["muted"], font=(FONT, 8)
        ).pack(anchor="w", pady=(6, 2))
        tk.Radiobutton(
            self.detection_frame, text="Image template match", variable=self.detection_method_var,
            value="template", command=self._on_detection_method_changed, **radio_kwargs,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.detection_frame, text="Color match (e.g. distinctly colored text)",
            variable=self.detection_method_var, value="color",
            command=self._on_detection_method_changed, **radio_kwargs,
        ).pack(anchor="w")

        self.scan_scope_frame = tk.Frame(body, bg=c["bg"])
        self.scan_scope_frame.pack(fill="x", padx=20)
        self.scan_scope_var = tk.StringVar(value=self.cfg["scan_scope"])
        tk.Label(
            self.scan_scope_frame, text="Scan area:", bg=c["bg"], fg=c["muted"], font=(FONT, 8)
        ).pack(anchor="w", pady=(6, 2))
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

        self.template_var = tk.StringVar(value="No template captured yet.")
        self.template_label = tk.Label(
            body, textvariable=self.template_var, bg=c["bg"], fg=c["muted"],
            font=(FONT, 9), wraplength=380, justify="left",
        )
        self.template_label.pack(anchor="w", padx=20, pady=(10, 10))

        self.capture_var = tk.StringVar(value="Capture Template + Click Target...")
        ttk.Button(
            body, textvariable=self.capture_var, style="Accent.TButton",
            command=self.on_capture,
        ).pack(fill="x", padx=20, pady=(0, 10))

        btn_row = tk.Frame(body, bg=c["bg"])
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        self.toggle_btn = ttk.Button(
            btn_row, text="Start (F6)", style="Start.TButton", command=self.on_toggle
        )
        self.toggle_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(
            btn_row, text="Quit (F9)", style="Danger.TButton", command=self.on_quit
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        tk.Frame(body, bg=c["border"], height=1).pack(fill="x", padx=20)
        tk.Label(
            body, text="SETTINGS", bg=c["bg"], fg=c["muted"], font=(FONT, 8, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        settings = tk.Frame(body, bg=c["bg"])
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
        self.thr_row_widgets = settings_row(
            "Match threshold (0-1)", self.thr_var, 2,
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
        button_label.grid(row=3, column=0, sticky="w", pady=7)
        self._add_tooltip(button_label, "Which mouse button to click with when the trigger is detected.")
        self.button_var = tk.StringVar(value=self.cfg["click_button"])
        ttk.Combobox(
            settings, textvariable=self.button_var, values=CLICK_BUTTONS, width=7,
            style="Field.TCombobox", state="readonly",
        ).grid(row=3, column=1, pady=7, sticky="e")

        self.limit_var = tk.StringVar(value=str(self.cfg["click_limit"]))
        settings_row(
            "Repeat limit (0 = infinite)", self.limit_var, 4,
            "Automatically pause after this many clicks. Set to 0 to keep clicking with "
            "no limit until you stop it manually.",
        )

        self.sound_var = tk.BooleanVar(value=self.cfg["sound_enabled"])
        tk.Checkbutton(
            settings, text="Sound alert when it starts clicking", variable=self.sound_var,
            bg=c["bg"], fg=c["text"], selectcolor=c["panel_bg"], activebackground=c["bg"],
            activeforeground=c["text"], highlightthickness=0, font=(FONT, 9),
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=7)

        self.auto_update_var = tk.BooleanVar(value=self.cfg["auto_update_check"])
        tk.Checkbutton(
            settings, text="Check for updates automatically", variable=self.auto_update_var,
            bg=c["bg"], fg=c["text"], selectcolor=c["panel_bg"], activebackground=c["bg"],
            activeforeground=c["text"], highlightthickness=0, font=(FONT, 9),
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=7)

        ttk.Button(
            body, text="Save Settings", style="Accent.TButton", command=self.on_save_settings
        ).pack(fill="x", padx=20, pady=(10, 0))

        tk.Frame(body, bg=c["border"], height=1).pack(fill="x", padx=20, pady=(20, 0))
        tk.Label(
            body, text="ACTIVITY", bg=c["bg"], fg=c["muted"], font=(FONT, 8, "bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        self.log_list = tk.Listbox(
            body, height=7, bg=c["panel_bg"], fg=c["muted_dark"], font=("Consolas", 9),
            bd=0, highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["border"],
            selectbackground=c["accent"], selectforeground=c["text"], activestyle="none",
        )
        self.log_list.pack(fill="x", padx=20, pady=(0, 16))

        tk.Label(
            body,
            text="F6 toggles start/pause, F9 quits — both work even while another window has focus.",
            bg=c["bg"], fg=c["muted"], font=(FONT, 8),
        ).pack(anchor="w", padx=20, pady=(0, 4))

        footer = tk.Frame(body, bg=c["bg"])
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

        self._on_mode_changed()
        self._on_scan_scope_changed()
        self._on_detection_method_changed()
        self._maybe_auto_check_updates()

    def _on_mode_changed(self):
        # The click-position choice (fixed point / current cursor) applies to
        # both modes, so it's always shown - only the trigger-capture
        # requirement (Targeted needs a template; Generic doesn't) differs.
        self._refresh_template_label()

    def _on_detection_method_changed(self):
        # Match threshold only means anything for image template matching -
        # color match uses the pixel count captured with the trigger instead.
        show_threshold = self.detection_method_var.get() != "color"
        for widget in self.thr_row_widgets:
            if show_threshold:
                widget.grid()
            else:
                widget.grid_remove()
        self._refresh_template_label()

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

        self.root.withdraw()
        try:
            box, _, full_img = run_capture_ui(
                parent=self.root, require_click_point=False,
                label_text="Drag a box around the area to scan (e.g. just the game viewport, "
                            "excluding sidebars/menus). Esc to cancel.",
            )
        finally:
            self.root.deiconify()
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

    def on_clear_scan_region(self):
        self.cfg["scan_region"] = None
        save_config(self.cfg)
        self.scan_region_display_var.set(self._scan_region_display_text())
        self.log("Scan region cleared - scanning the whole window again.")

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

        capture_label = "Capture Trigger..." if needs_template and not needs_point else "Capture Trigger + Click Target..."
        recapture_label = "Recapture Trigger..." if needs_template and not needs_point else "Recapture Trigger + Click Target..."

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
        else:
            self.template_var.set("No trigger captured yet - click below to set it up (one-time).")
            self.capture_var.set(capture_label)

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

    def log(self, msg):
        self.root.after(0, self._log_ui, msg)

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
        require_point = self.position_var.get() != "cursor"
        self.root.withdraw()
        try:
            box, point, full_img = run_capture_ui(parent=self.root, require_click_point=require_point)
        finally:
            self.root.deiconify()
        if box is None:
            self.log("Capture cancelled.")
        else:
            save_capture(box, point, full_img)
            if self.cfg["detection_method"] == "color":
                target_color, pixel_count = analyze_color_trigger(full_img.crop(box))
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
            self.detector.start_scanning()
        self._refresh_status()

    def on_toggle(self):
        if self.detector.scanning_active.is_set():
            self.detector.pause_scanning()
            self.log("Paused.")
        else:
            if not self.detector.ready:
                self.messagebox.showwarning(
                    "Not ready", "Capture a template and click target first."
                )
                return
            self.detector.start_scanning()
            self.log("Scanning started.")
        self._refresh_status()

    def on_save_settings(self):
        try:
            parsed = parse_settings_input(
                self.min_var.get(), self.max_var.get(), self.thr_var.get(), self.limit_var.get()
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
            update = check_for_update(__version__)
            self.root.after(0, lambda: self._on_update_check_done(update, silent))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, update, silent):
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
