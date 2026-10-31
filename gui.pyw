"""Jungle Leopard Dashboard - small control window for the cooler LCD."""
import os
import sys
import tkinter as tk
from tkinter import colorchooser, ttk

from PIL import ImageTk

import app
import lights
import settings

BG, PANEL, FG, DIM, ACCENT = "#0c0e1a", "#161a2c", "#f0f4ff", "#7882a0", "#d97757"
STARTUP = os.path.join(
    os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "JungleLeopardDash.vbs"
)
HERE = os.path.dirname(os.path.abspath(__file__))
PREVIEW = (341, 200)  # 1024x600 scaled down


class Gui:
    def __init__(self, root, minimized=False):
        self.root = root
        self.cfg = settings.load()
        self.runner = app.Runner(
            self.cfg["brightness"], self.cfg["rotate_seconds"], self.cfg["screens"], self.cfg["pinned"]
        )
        self.runner.start()
        self.lights = lights.Lights(self.cfg["lights"])
        self.cfg["lights"] = self.lights.cfg  # shared, so edits persist
        self.lights.start()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        if minimized:
            root.iconify()
        self.tick()

    # ---- layout ----
    def _build(self):
        r = self.root
        r.title("Jungle Leopard Dashboard")
        r.configure(bg=BG)
        r.resizable(False, False)
        st = ttk.Style()
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, font=("Segoe UI", 10))
        st.configure("Card.TFrame", background=PANEL)
        st.configure("Card.TLabel", background=PANEL, foreground=FG)
        st.configure("Dim.TLabel", background=PANEL, foreground=DIM)
        st.configure("Head.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 15))
        st.configure("Status.TLabel", background=BG, foreground=DIM)
        st.configure("TCheckbutton", background=PANEL, foreground=FG)
        st.map("TCheckbutton", background=[("active", PANEL)])
        st.configure("TScale", background=PANEL, troughcolor="#2a2f4a")
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", borderwidth=0, padding=6)
        st.map("Accent.TButton", background=[("active", "#e88a6b")])

        top = ttk.Frame(r, padding=(16, 14, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Jungle Leopard Dashboard", style="Head.TLabel").pack(side="left")
        self.status = tk.StringVar(value="starting")
        self.dot = tk.Canvas(top, width=14, height=14, bg=BG, highlightthickness=0)
        self.dot.pack(side="right")
        self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill=DIM, outline="")
        ttk.Label(top, textvariable=self.status, style="Status.TLabel").pack(side="right", padx=6)

        body = ttk.Frame(r, padding=(16, 8, 16, 16))
        body.pack()

        # preview
        pv = ttk.Frame(body, style="Card.TFrame", padding=8)
        pv.grid(row=0, column=0, sticky="n", padx=(0, 12))
        self.preview = tk.Label(pv, bg=PANEL, bd=0)
        self.preview.pack()
        self.pv_name = tk.StringVar()
        ttk.Label(pv, textvariable=self.pv_name, style="Dim.TLabel").pack(pady=(6, 0))
        self.pause_btn = ttk.Button(pv, text="Pause", style="Accent.TButton", command=self.toggle_pause)
        self.pause_btn.pack(fill="x", pady=(8, 0))

        # controls
        c = ttk.Frame(body, style="Card.TFrame", padding=14)
        c.grid(row=0, column=1, sticky="n")
        ttk.Label(c, text="Screens", style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(row=0, column=0, sticky="w")
        self.enabled = {}
        for i, name in enumerate(app.SCREENS):
            v = tk.BooleanVar(value=name in self.cfg["screens"])
            self.enabled[name] = v
            ttk.Checkbutton(c, text=name.title(), variable=v, command=self.apply_screens).grid(row=1 + i, column=0, sticky="w")

        ttk.Label(c, text="Show", style="Card.TLabel").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.pin = tk.StringVar(value=self.cfg["pinned"].title() if self.cfg["pinned"] else "Rotate all")
        cb = ttk.Combobox(c, textvariable=self.pin, state="readonly", width=14,
                          values=["Rotate all"] + [n.title() for n in app.SCREENS])
        cb.grid(row=6, column=0, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_pin())

        self.secs = tk.IntVar(value=self.cfg["rotate_seconds"])
        self.secs_lbl = ttk.Label(c, style="Card.TLabel")
        self.secs_lbl.grid(row=7, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(c, from_=3, to=60, variable=self.secs, length=190, command=lambda v: self.apply_secs()).grid(row=8, column=0, sticky="w")

        self.bright = tk.IntVar(value=self.cfg["brightness"])
        self.bright_lbl = ttk.Label(c, style="Card.TLabel")
        self.bright_lbl.grid(row=9, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(c, from_=0, to=100, variable=self.bright, length=190, command=lambda v: self.apply_bright()).grid(row=10, column=0, sticky="w")

        self.auto = tk.BooleanVar(value=os.path.exists(STARTUP))
        ttk.Checkbutton(c, text="Start with Windows", variable=self.auto, command=self.toggle_auto).grid(row=11, column=0, sticky="w", pady=(14, 0))

        self._build_lights(body)
        self.apply_secs()
        self.apply_bright()

    def _build_lights(self, body):
        lc = self.lights.cfg
        f = ttk.Frame(body, style="Card.TFrame", padding=14)
        f.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(f, text="Fan lights", style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(row=0, column=0, sticky="w")
        self.lstatus = tk.StringVar()
        ttk.Label(f, textvariable=self.lstatus, style="Dim.TLabel").grid(row=0, column=1, columnspan=3, sticky="e")

        self.l_on = tk.BooleanVar(value=lc["enabled"])
        ttk.Checkbutton(f, text="Control fan lights", variable=self.l_on, command=self.apply_lights).grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.l_effect = tk.StringVar(value=lc["effect"])
        cb = ttk.Combobox(f, textvariable=self.l_effect, state="readonly", width=12, values=lights.EFFECTS)
        cb.grid(row=1, column=1, padx=8, pady=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_lights())

        self.l_swatch = tk.Button(f, width=4, relief="flat", command=self.pick_color, bd=0)
        self.l_swatch.grid(row=1, column=2, padx=(0, 8), pady=(6, 0))
        self._paint_swatch()

        ttk.Label(f, text="Speed", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.l_speed = tk.IntVar(value=lc["speed"])
        ttk.Scale(f, from_=1, to=100, variable=self.l_speed, length=150, command=lambda v: self.apply_lights()).grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=(8, 0))

        ttk.Label(f, text="LEDs on header", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.l_leds = tk.IntVar(value=lc["leds"])
        ttk.Spinbox(f, from_=1, to=64, width=5, textvariable=self.l_leds, command=self.apply_lights).grid(row=3, column=1, sticky="w", padx=8, pady=(8, 0))
        self.l_leds.trace_add("write", lambda *a: self.apply_lights())

    # ---- actions ----
    def save(self):
        settings.save(self.cfg)

    def apply_screens(self):
        self.cfg["screens"] = [n for n in app.SCREENS if self.enabled[n].get()] or list(app.SCREENS)
        self.runner.screens = self.cfg["screens"]
        self.save()

    def apply_pin(self):
        v = self.pin.get()
        self.cfg["pinned"] = None if v == "Rotate all" else v.lower()
        self.runner.pinned = self.cfg["pinned"]
        self.save()

    def apply_secs(self):
        n = int(round(self.secs.get()))
        self.secs_lbl.config(text=f"Switch every {n} s")
        self.cfg["rotate_seconds"] = self.runner.rotate_seconds = n
        self.save()

    def apply_bright(self):
        n = int(round(self.bright.get()))
        self.bright_lbl.config(text=f"Backlight {n}%")
        self.cfg["brightness"] = self.runner.brightness = n
        self.save()

    def _paint_swatch(self):
        r, g, b = self.lights.cfg["color"]
        self.l_swatch.config(bg="#%02x%02x%02x" % (r, g, b), activebackground="#%02x%02x%02x" % (r, g, b))

    def pick_color(self):
        rgb, _ = colorchooser.askcolor(color="#%02x%02x%02x" % tuple(self.lights.cfg["color"]), parent=self.root)
        if rgb:
            self.lights.cfg["color"] = [int(x) for x in rgb]
            self._paint_swatch()
            self.apply_lights()

    def apply_lights(self):
        c = self.lights.cfg
        c["enabled"] = bool(self.l_on.get())
        c["effect"] = self.l_effect.get()
        c["speed"] = int(round(self.l_speed.get()))
        try:
            c["leds"] = max(1, min(64, int(self.l_leds.get())))
        except (tk.TclError, ValueError):
            pass  # mid-typing in the spinbox
        self.save()

    def toggle_pause(self):
        self.runner.paused = not self.runner.paused
        self.pause_btn.config(text="Resume" if self.runner.paused else "Pause")

    def toggle_auto(self):
        if self.auto.get():
            pyw = sys.executable.replace("python.exe", "pythonw.exe")
            script = os.path.join(HERE, "gui.pyw")
            with open(STARTUP, "w") as f:
                f.write('CreateObject("WScript.Shell").Run """%s"" ""%s"" --minimized", 0, False\n' % (pyw, script))
        elif os.path.exists(STARTUP):
            os.remove(STARTUP)

    # ---- refresh ----
    def tick(self):
        s = self.runner.status
        self.status.set(s)
        self.lstatus.set(self.lights.status)
        self.dot.itemconfig(self.dot_id, fill="#46d282" if s == "running" else "#fabe3c" if s == "paused" else "#fa5a5a")
        name = self.runner.current
        if name in app.SCREENS and self.root.state() != "iconic":
            try:
                img = app.SCREENS[name]().resize(PREVIEW)
                self._photo = ImageTk.PhotoImage(img)
                self.preview.config(image=self._photo)
                self.pv_name.set("Now showing: " + name.title())
            except Exception:
                pass
        self.root.after(1000, self.tick)

    def quit(self):
        self.lights.shutdown()
        self.runner.shutdown()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Gui(root, minimized="--minimized" in sys.argv)
    root.mainloop()
