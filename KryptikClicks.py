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

__version__ = "1.3.0"

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
    "match_threshold": 0.85,
    "click_button": "left",
    "click_mode": "targeted",
    "click_position": "fixed",
    "click_limit": 0,
    "sound_enabled": False,
}
CLICK_BUTTONS = ["left", "right", "middle"]
CLICK_MODES = ["targeted", "generic"]
CLICK_POSITIONS = ["fixed", "cursor"]
SCAN_INTERVAL = 0.08      # seconds between screen scans while idle/watching
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


def canvas_point_to_absolute(canvas_x, canvas_y, monitor):
    """Converts a point picked on the capture overlay canvas (0,0 = top-left of
    the captured image) to a true absolute screen coordinate. Needed because
    mss's combined virtual-desktop origin (monitor["left"/"top"]) is non-zero
    whenever a monitor sits left of/above the primary display."""
    return (canvas_x + monitor["left"], canvas_y + monitor["top"])


def run_capture_ui(parent=None, require_click_point=True):
    """Shows the fullscreen capture overlay: drag-select the trigger image, then
    (if require_click_point) click the spot to auto-click. Pass require_click_point=False
    to skip that second step - used when the click position will be the live cursor
    position instead of a captured point.
    Returns (template_box, target_point, full_img), or (None, None, None) if cancelled.
    Pass a Tkinter root as `parent` to run modally inside an existing app; omit for standalone use.
    """
    import tkinter as tk
    from PIL import Image, ImageTk
    import mss

    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        full_img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    standalone = parent is None
    win = tk.Tk() if standalone else tk.Toplevel(parent)
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    win.configure(cursor="crosshair")
    if not standalone:
        win.grab_set()

    tk_img = ImageTk.PhotoImage(full_img, master=win)
    canvas = tk.Canvas(win, width=full_img.width, height=full_img.height, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=tk_img, anchor="nw")
    canvas.image = tk_img  # keep a reference alive

    step1_text = (
        "Step 1/2: Drag a tight box around the trigger you want it to watch for, then release. Esc to cancel."
        if require_click_point else
        "Drag a tight box around the trigger you want it to watch for, then release. Esc to cancel."
    )
    label = tk.Label(win, text=step1_text, bg="yellow")
    label.place(x=10, y=10)

    state = {"phase": 1, "start": None, "rect": None, "template_box": None, "target_point": None}

    def on_press(event):
        if state["phase"] == 1:
            state["start"] = (event.x, event.y)
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="red", width=2
            )
        elif state["phase"] == 2:
            state["target_point"] = canvas_point_to_absolute(event.x, event.y, monitor)
            canvas.create_oval(
                event.x - 6, event.y - 6, event.x + 6, event.y + 6, outline="lime", width=3
            )
            win.after(250, win.destroy)

    def on_drag(event):
        if state["phase"] != 1 or state["start"] is None:
            return
        x0, y0 = state["start"]
        canvas.coords(state["rect"], x0, y0, event.x, event.y)

    def on_release(event):
        if state["phase"] != 1 or state["start"] is None:
            return
        x0, y0 = state["start"]
        x1, y1 = event.x, event.y
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left < 3 or bottom - top < 3:
            return
        state["template_box"] = (left, top, right, bottom)
        if require_click_point:
            state["phase"] = 2
            label.config(
                text="Step 2/2: Click the spot you want it to auto-click. Esc to cancel."
            )
        else:
            win.destroy()

    def on_escape(event):
        state["template_box"] = None
        state["target_point"] = None
        win.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    win.bind("<Escape>", on_escape)

    if standalone:
        win.mainloop()
    else:
        parent.wait_window(win)

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
            return self.template is not None  # trigger still needed, but not a click point
        return self.template is not None and self.click_x is not None

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

    def _find_match_in(self, sct, region):
        shot = sct.grab(region)
        import numpy as np
        frame = np.array(shot)  # BGRA
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGRA2GRAY)
        result = self.cv2.matchTemplate(gray, self.template, self.cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = self.cv2.minMaxLoc(result)
        if max_val >= self.cfg["match_threshold"]:
            x = region["left"] + max_loc[0] + self.t_w // 2
            y = region["top"] + max_loc[1] + self.t_h // 2
            return x, y
        return None

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

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0  # we control click timing ourselves

        # mss accumulates Windows GDI resources over a long-running capture loop and
        # gradually slows down; periodically recreating it keeps capture speed steady.
        MSS_REFRESH_INTERVAL = 300
        sct = self.mss.mss()
        monitor = sct.monitors[0]
        scan_count = 0
        last_error_log = 0.0

        def scan_tick():
            nonlocal sct, monitor, scan_count
            scan_count += 1
            if scan_count % MSS_REFRESH_INTERVAL == 0:
                sct.close()
                sct = self.mss.mss()
                monitor = sct.monitors[0]

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
                match = safe_find_match(monitor)
                if match is None:
                    time.sleep(SCAN_INTERVAL)
                    continue

                self.log("Trigger detected - clicking...")
                self._beep()
                while match is not None and self.scanning_active.is_set() and not self.stop_event.is_set():
                    if click_and_check_limit():
                        break
                    sleep_between_clicks()
                    scan_tick()
                    match = safe_find_match(self._local_region_around(match[0], match[1], monitor))
                self.log(f"Stopped clicking ({self.total_clicks} clicks this session).")
        finally:
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

        self.root = tk.Tk()
        self.root.title("KryptikClicks")
        self.root.configure(bg=self.COLORS["bg"])
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)
        self.root.report_callback_exception = self._on_callback_exception
        self._enable_dark_titlebar(self.root)
        try:
            self.root.iconbitmap(resource_path("assets", "icon.ico"))
        except Exception:
            pass  # cosmetic only - fine to fall back to the default icon

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
            ttk.Entry(settings, textvariable=var, width=8, style="Field.TEntry", justify="right").grid(
                row=r, column=1, pady=7, sticky="e"
            )

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
        settings_row(
            "Match threshold (0-1)", self.thr_var, 2,
            "How closely the screen must match your captured trigger image to fire "
            "clicking (1.0 = pixel-perfect match). Higher = stricter, fewer false triggers but "
            "may miss it if rendering shifts slightly. Lower = more lenient but may misfire on "
            "similar-looking content. 0.85 is a good default.",
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

        tk.Label(
            body, text=f"v{__version__}", bg=c["bg"], fg=c["muted"], font=(FONT, 7),
        ).pack(anchor="e", padx=20, pady=(0, 16))

        self._on_mode_changed()

    def _on_mode_changed(self):
        # The click-position choice (fixed point / current cursor) applies to
        # both modes, so it's always shown - only the trigger-capture
        # requirement (Targeted needs a template; Generic doesn't) differs.
        self._refresh_template_label()

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
        # Reflects the mode/position currently selected in the form (which may not be
        # saved yet) - same "preview before Save" behavior as the other settings fields.
        mode = self.mode_var.get()
        cursor_position = self.position_var.get() == "cursor"
        needs_template = mode == "targeted"
        needs_point = not cursor_position

        capture_label = "Capture Template..." if needs_template and not needs_point else "Capture Template + Click Target..."
        recapture_label = "Recapture Template..." if needs_template and not needs_point else "Recapture Template + Click Target..."

        if not needs_template and not needs_point:
            self.template_var.set("Cursor mode selected - no capture needed. It'll click wherever your mouse is.")
            self.capture_var.set(capture_label)
            return

        have_template = self.detector.template is not None
        have_point = self.detector.click_x is not None
        ready_for_mode = (not needs_template or have_template) and (not needs_point or have_point)

        if ready_for_mode:
            if not needs_point:
                self.template_var.set(
                    f"Using saved trigger: {self.detector.t_w}x{self.detector.t_h}px. "
                    f"Clicks wherever your mouse is when it's detected."
                )
            elif not needs_template:
                self.template_var.set(f"Using saved click point ({self.detector.click_x}, {self.detector.click_y}).")
            else:
                self.template_var.set(
                    f"Using saved capture: {self.detector.t_w}x{self.detector.t_h}px template, "
                    f"click target ({self.detector.click_x}, {self.detector.click_y}). "
                    f"Reused automatically — recapture only if it stops matching."
                )
            self.capture_var.set(recapture_label)
        else:
            self.template_var.set("No template captured yet - click below to set it up (one-time).")
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
            self.detector.load()
            self._refresh_template_label()
            if point is not None:
                self.log(f"Captured new template + click target {point}.")
            else:
                self.log("Captured new template.")
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
        self.cfg["sound_enabled"] = bool(self.sound_var.get())
        save_config(self.cfg)
        self._refresh_status()
        self._refresh_template_label()
        self.log("Settings saved.")

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
