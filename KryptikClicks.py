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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "trigger_template.png")
TARGET_PATH = os.path.join(SCRIPT_DIR, "click_target.txt")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "kryptikclicks_config.json")

# --- Defaults (overridden by kryptikclicks_config.json / the settings window) -----
DEFAULT_CONFIG = {
    "min_delay_ms": 50,
    "max_delay_ms": 150,
    "match_threshold": 0.85,
}
SCAN_INTERVAL = 0.08      # seconds between screen scans while idle/watching
TOGGLE_HOTKEY = "f6"
QUIT_HOTKEY = "f9"
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = ["cv2", "mss", "numpy", "pyautogui", "pynput"]
PIP_INSTALL_CMD = "pip install opencv-python mss numpy pyautogui pynput"


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
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def run_capture_ui(parent=None):
    """Shows the fullscreen capture overlay (template drag-select + click-target pick).
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

    label = tk.Label(
        win,
        text="Step 1/2: Drag a tight box around the trigger you want it to watch for, then release. Esc to cancel.",
        bg="yellow",
    )
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
            state["target_point"] = (event.x, event.y)
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
        state["phase"] = 2
        label.config(
            text="Step 2/2: Click the spot you want it to auto-click. Esc to cancel."
        )

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

    if state["template_box"] is None or state["target_point"] is None:
        return None, None, None
    return state["template_box"], state["target_point"], full_img


def save_capture(template_box, target_point, full_img):
    crop = full_img.crop(template_box)
    crop.save(TEMPLATE_PATH)
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
        self.load()

        self.scanning_active = threading.Event()
        self.stop_event = threading.Event()

    @property
    def ready(self):
        return self.template is not None and self.click_x is not None

    def load(self):
        if os.path.exists(TEMPLATE_PATH):
            self.template = self.cv2.imread(TEMPLATE_PATH, self.cv2.IMREAD_GRAYSCALE)
            if self.template is not None:
                self.t_h, self.t_w = self.template.shape[:2]
        if os.path.exists(TARGET_PATH):
            with open(TARGET_PATH) as f:
                self.click_x, self.click_y = map(int, f.read().strip().split(","))

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

        def scan_tick():
            nonlocal sct, monitor, scan_count
            scan_count += 1
            if scan_count % MSS_REFRESH_INTERVAL == 0:
                sct.close()
                sct = self.mss.mss()
                monitor = sct.monitors[0]

        try:
            while not self.stop_event.is_set():
                if not (self.scanning_active.is_set() and self.ready):
                    time.sleep(SCAN_INTERVAL)
                    continue

                scan_tick()
                match = self._find_match_in(sct, monitor)
                if match is None:
                    time.sleep(SCAN_INTERVAL)
                    continue

                self.log("Trigger detected - clicking...")
                clicks = 0
                while match is not None and self.scanning_active.is_set() and not self.stop_event.is_set():
                    pyautogui.click(self.click_x, self.click_y)
                    clicks += 1
                    min_d = self.cfg["min_delay_ms"] / 1000.0
                    max_d = self.cfg["max_delay_ms"] / 1000.0
                    time.sleep(random.uniform(min_d, max_d))
                    scan_tick()
                    match = self._find_match_in(sct, self._local_region_around(match[0], match[1], monitor))
                self.log(f"Stopped clicking ({clicks} clicks).")
        finally:
            sct.close()


def run_headless():
    from pynput import keyboard as pynkeyboard

    detector = Detector(load_config())
    if not detector.ready:
        print(f"No template/click-target found.")
        print("Run with --capture first: python KryptikClicks.py --capture")
        sys.exit(1)

    print(f"Template loaded: {detector.t_w}x{detector.t_h} px from {TEMPLATE_PATH}")
    print(f"Click target: ({detector.click_x}, {detector.click_y})")
    print(f"Press {TOGGLE_HOTKEY.upper()} to start/pause scanning, {QUIT_HOTKEY.upper()} to quit.")

    def toggle_scanning():
        if detector.scanning_active.is_set():
            detector.scanning_active.clear()
            print("[paused] scanning off")
        else:
            detector.scanning_active.set()
            print("[active] scanning on")

    def request_quit():
        print("Quitting...")
        detector.stop_event.set()

    hotkey_map = {
        pynkeyboard.Key[TOGGLE_HOTKEY]: toggle_scanning,
        pynkeyboard.Key[QUIT_HOTKEY]: request_quit,
    }
    held_keys = set()
    last_fired = {}
    DEBOUNCE_SECONDS = 0.3

    def on_press(key):
        if key in held_keys:
            return
        held_keys.add(key)
        action = hotkey_map.get(key)
        if action is None:
            return
        now = time.monotonic()
        if now - last_fired.get(key, 0) < DEBOUNCE_SECONDS:
            return
        last_fired[key] = now
        action()

    def on_release(key):
        held_keys.discard(key)

    listener = pynkeyboard.Listener(on_press=on_press, on_release=on_release)
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
        self._enable_dark_titlebar(self.root)

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
        self.held_keys = set()
        self.last_fired = {}
        self.hotkey_map = {
            pynkeyboard.Key[TOGGLE_HOTKEY]: self.on_toggle,
            pynkeyboard.Key[QUIT_HOTKEY]: self.on_quit,
        }
        self.listener = pynkeyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self.listener.start()

        self.worker_thread = threading.Thread(target=self.detector.run, daemon=True)
        self.worker_thread.start()

        self.root.mainloop()

    @staticmethod
    def _enable_dark_titlebar(window):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new/old builds)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                ) == 0:
                    break
        except Exception:
            pass  # best-effort cosmetic touch; fine if unsupported

    # --- hotkeys (run on the pynput listener thread; marshal into the GUI thread) ---
    def _on_key_press(self, key):
        if key in self.held_keys:
            return
        self.held_keys.add(key)
        action = self.hotkey_map.get(key)
        if action is None:
            return
        now = time.monotonic()
        if now - self.last_fired.get(key, 0) < 0.3:
            return
        self.last_fired[key] = now
        self.root.after(0, action)

    def _on_key_release(self, key):
        self.held_keys.discard(key)

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
        tk.Label(
            header, text="KryptikClicks", bg=c["bg"], fg=c["text"],
            font=(FONT, 14, "normal"),
        ).pack(anchor="w", padx=20, pady=(20, 4))
        self.status_var = tk.StringVar(value="● Idle")
        self.status_label = tk.Label(
            header, textvariable=self.status_var, bg=c["bg"], fg=c["muted"],
            font=(FONT, 9, "bold"),
        )
        self.status_label.pack(anchor="w", padx=20, pady=(0, 16))

        body = tk.Frame(self.root, bg=c["bg"])
        body.grid(row=1, column=0, sticky="we")

        self.template_var = tk.StringVar(value="No template captured yet.")
        tk.Label(
            body, textvariable=self.template_var, bg=c["bg"], fg=c["muted"],
            font=(FONT, 9), wraplength=380, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 10))

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
        ).pack(anchor="w", padx=20, pady=(0, 20))

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
        if self.detector.ready:
            self.template_var.set(
                f"Using saved capture: {self.detector.t_w}x{self.detector.t_h}px template, "
                f"click target ({self.detector.click_x}, {self.detector.click_y}). "
                f"Reused automatically — recapture only if it stops matching."
            )
            self.capture_var.set("Recapture Template + Click Target...")
        else:
            self.template_var.set("No template captured yet - click below to set it up (one-time).")
            self.capture_var.set("Capture Template + Click Target...")

    def _refresh_status(self):
        c = self.COLORS
        if self.detector.scanning_active.is_set():
            self.status_var.set("● Scanning")
            self.status_label.config(fg=c["green"])
            self.toggle_btn.config(text="Pause (F6)", style="Pause.TButton")
        else:
            ready = self.detector.ready
            self.status_var.set("● Idle" if ready else "● Not ready")
            self.status_label.config(fg=(c["muted"] if ready else c["red"]))
            self.toggle_btn.config(text="Start (F6)", style="Start.TButton")

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
        self.detector.scanning_active.clear()
        self.root.withdraw()
        try:
            box, point, full_img = run_capture_ui(parent=self.root)
        finally:
            self.root.deiconify()
        if box is None:
            self.log("Capture cancelled.")
        else:
            save_capture(box, point, full_img)
            self.detector.load()
            self._refresh_template_label()
            self.log(f"Captured new template + click target {point}.")
        if was_scanning and self.detector.ready:
            self.detector.scanning_active.set()
        self._refresh_status()

    def on_toggle(self):
        if self.detector.scanning_active.is_set():
            self.detector.scanning_active.clear()
            self.log("Paused.")
        else:
            if not self.detector.ready:
                self.messagebox.showwarning(
                    "Not ready", "Capture a template and click target first."
                )
                return
            self.detector.scanning_active.set()
            self.log("Scanning started.")
        self._refresh_status()

    def on_save_settings(self):
        try:
            min_ms = float(self.min_var.get())
            max_ms = float(self.max_var.get())
            thr = float(self.thr_var.get())
            if min_ms < 0 or max_ms < min_ms:
                raise ValueError("Min delay must be >= 0 and <= max delay.")
            if not (0.0 < thr <= 1.0):
                raise ValueError("Threshold must be between 0 and 1.")
        except ValueError as e:
            self.messagebox.showerror("Invalid settings", str(e) or "Enter valid numbers.")
            return
        self.cfg["min_delay_ms"] = min_ms
        self.cfg["max_delay_ms"] = max_ms
        self.cfg["match_threshold"] = thr
        save_config(self.cfg)
        self.log("Settings saved.")

    def on_quit(self):
        self.detector.stop_event.set()
        self.detector.scanning_active.clear()
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
