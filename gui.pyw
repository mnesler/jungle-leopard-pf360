"""Jungle Leopard Dashboard - control window for the cooler LCD and fan lights."""
import os
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import ImageTk

import app
import gallery as gal
import hwapp
import lights
import screens
import sensors
import settings

BG, PANEL, FG, DIM, ACCENT = "#0c0e1a", "#161a2c", "#f0f4ff", "#7882a0", "#d97757"
RAISED, HOVER = "#1f2440", "#1a1f38"
GOOD, WARN, BAD = "#46d282", "#fabe3c", "#fa5a5a"
STARTUP = os.path.join(
    os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "JungleLeopardDash.vbs"
)
HERE = os.path.dirname(os.path.abspath(__file__))
PREVIEW = (432, 253)  # 1024x600 scaled down
LEGACY = ["system", "claude"]  # screens that existed before order/known were saved
PRESETS = [("Claude", (217, 119, 87)), ("Blue", (0, 120, 255)), ("Green", (40, 220, 120)),
           ("Purple", (160, 90, 255)), ("Red", (255, 40, 40)), ("White", (255, 255, 255))]


def round_rect(c, x1, y1, x2, y2, r, fill="", **kw):
    """Pill/rounded rectangle from two arcs and a bar (crisper than a smoothed polygon)."""
    r = min(r, (y2 - y1) / 2)
    c.create_oval(x1, y1, x1 + 2 * r, y2, fill=fill, outline="")
    c.create_oval(x2 - 2 * r, y1, x2, y2, fill=fill, outline="")
    c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")


class TabBar(tk.Canvas):
    """Flat pill-style tab bar: the active tab is a filled accent pill, hover lightens the others."""

    def __init__(self, parent, names, on_change):
        super().__init__(parent, height=46, bg=BG, highlightthickness=0, bd=0)
        self.names, self.on_change, self.active, self.hover = names, on_change, 0, None
        self.font = tkfont.Font(family="Segoe UI Semibold", size=10)
        self.boxes = []
        x = 4
        for n in names:
            w = self.font.measure(n) + 34
            self.boxes.append((x, 6, x + w, 40))
            x += w + 6
        self.config(width=x)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)
        self.draw()

    def _at(self, e):
        for i, (x1, y1, x2, y2) in enumerate(self.boxes):
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                return i
        return None

    def _motion(self, e):
        self._set_hover(self._at(e))

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.config(cursor="hand2" if i is not None else "")
            self.draw()

    def _click(self, e):
        i = self._at(e)
        if i is not None and i != self.active:
            self.select(i)

    def select(self, i):
        self.active = i
        self.draw()
        self.on_change(i)

    def draw(self):
        self.delete("all")
        for i, (x1, y1, x2, y2) in enumerate(self.boxes):
            if i == self.active:
                round_rect(self, x1, y1, x2, y2, 17, fill=ACCENT, outline="")
                col = "#ffffff"
            else:
                if i == self.hover:
                    round_rect(self, x1, y1, x2, y2, 17, fill=RAISED, outline="")
                col = FG if i == self.hover else DIM
            self.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=self.names[i], fill=col, font=self.font)


class Gui:
    def __init__(self, root, minimized=False):
        self.root = root
        self.cfg = settings.load()
        self._init_screens()
        self.gallery = gal.gallery
        self.gallery.image_seconds = self.cfg["gallery"]["image_seconds"]
        self.gallery.set_items(self.cfg["gallery"]["items"])
        self.runner = app.Runner(self.cfg["brightness"], self.cfg["rotate_seconds"], self.enabled_ordered(), self.cfg["pinned"])
        self.runner.start()
        self.lights = lights.Lights(self.cfg["lights"])
        self.cfg["lights"] = self.lights.cfg  # shared, so edits persist
        self.lights.start()
        self._style()
        self._menu()
        self._tabs()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        if minimized:
            root.iconify()
        self.tick()

    # ---------- state ----------
    def _migrate(self):
        c = self.cfg
        if c.get("v", 1) < 2:  # status screen removed, 'usage' renamed to 'claude'
            for key in ("order", "screens", "known"):
                if c.get(key):
                    c[key] = ["claude" if n == "usage" else n for n in c[key] if n != "claude"]
            if c.get("pinned") == "claude":
                c["pinned"] = None
            elif c.get("pinned") == "usage":
                c["pinned"] = "claude"
        if c.get("v", 1) < 3:  # 'media' -> 'music' (now playing), 'photo' -> 'gallery'
            ren = {"media": "music", "photo": "gallery"}
            for key in ("order", "screens", "known"):
                if c.get(key):
                    c[key] = [ren.get(n, n) for n in c[key]]
            c["pinned"] = ren.get(c.get("pinned"), c.get("pinned"))
            if c.get("media_path") and not c["gallery"]["items"]:
                c["gallery"]["items"] = [c["media_path"]]
        c["v"] = 3

    def _init_screens(self):
        names = list(screens.SCREENS)
        self._migrate()
        saved = [n for n in (self.cfg.get("order") or LEGACY) if n in names]
        self.order = saved + [n for n in names if n not in saved]
        known = set(self.cfg.get("known") or LEGACY)
        enabled = set(self.cfg["screens"])
        enabled |= {n for n in names if n not in known and n != "gallery"}  # new screens start enabled
        self.enabled = {n: n in enabled for n in names}
        self.cfg["known"] = names
        self._save_screens(push=False)

    def enabled_ordered(self):
        return [n for n in self.order if self.enabled[n]] or list(self.order)

    def _save_screens(self, push=True):
        self.cfg["order"] = self.order
        self.cfg["screens"] = [n for n in self.order if self.enabled[n]]
        if push:
            self.runner.screens = self.enabled_ordered()
        settings.save(self.cfg)

    def save(self):
        settings.save(self.cfg)

    # ---------- styling ----------
    def _style(self):
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
        st.configure("Head.TLabel", background=PANEL, foreground=FG, font=("Segoe UI Semibold", 12))
        st.configure("TCheckbutton", background=PANEL, foreground=FG)
        st.map("TCheckbutton", background=[("active", PANEL)])
        st.configure("TRadiobutton", background=PANEL, foreground=FG)
        st.map("TRadiobutton", background=[("active", PANEL)])
        st.configure("TScale", background=PANEL, troughcolor="#2a2f4a")
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", borderwidth=0, padding=(14, 9))
        st.map("Accent.TButton", background=[("active", "#e88a6b")])
        st.configure("TButton", background=RAISED, foreground=FG, borderwidth=0, padding=(14, 9))
        st.map("TButton", background=[("active", "#2b3158")])
        for w in ("TCombobox", "TSpinbox"):
            st.configure(w, fieldbackground=RAISED, background=RAISED, foreground=FG, arrowcolor=FG,
                         bordercolor=RAISED, lightcolor=RAISED, darkcolor=RAISED, insertcolor=FG, padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", RAISED)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", RAISED)], selectforeground=[("readonly", FG)])
        r.option_add("*TCombobox*Listbox.background", RAISED)
        r.option_add("*TCombobox*Listbox.foreground", FG)
        r.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        r.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        st.configure("Vertical.TScrollbar", background=RAISED, troughcolor=PANEL, borderwidth=0, arrowcolor=DIM)

    # ---------- menu ----------
    def _menu(self):
        m = tk.Menu(self.root, bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground="#fff", bd=0)
        self.root.config(menu=m)

        def sub():
            return tk.Menu(m, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground="#fff")

        f = sub()
        f.add_command(label="Add to gallery...", command=self.add_files)
        f.add_command(label="Open settings folder", command=lambda: os.startfile(settings.PATH.parent))
        f.add_separator()
        f.add_command(label="Quit", command=self.quit)
        m.add_cascade(label="File", menu=f)

        v = sub()
        self.m_pause = tk.BooleanVar(value=False)
        v.add_checkbutton(label="Pause display", variable=self.m_pause, command=self.toggle_pause)
        v.add_separator()
        self.m_show = tk.StringVar(value=self.cfg["pinned"] or "")
        v.add_radiobutton(label="Rotate all screens", variable=self.m_show, value="", command=self._menu_show)
        for n in screens.SCREENS:
            v.add_radiobutton(label=n.title(), variable=self.m_show, value=n, command=self._menu_show)
        m.add_cascade(label="View", menu=v)

        li = sub()
        self.m_lights = tk.BooleanVar(value=self.lights.cfg["enabled"])
        li.add_checkbutton(label="Control fan lights", variable=self.m_lights, command=self._menu_lights)
        li.add_separator()
        self.m_effect = tk.StringVar(value=self.lights.cfg["effect"])
        for e in lights.EFFECTS:
            li.add_radiobutton(label=e, variable=self.m_effect, value=e, command=self._menu_effect)
        m.add_cascade(label="Lights", menu=li)

        h = sub()
        h.add_command(label="About", command=self.about)
        m.add_cascade(label="Help", menu=h)

    def _menu_show(self):
        self.set_pin(self.m_show.get() or None)

    def _menu_lights(self):
        self.l_on.set(self.m_lights.get())
        self.apply_lights()

    def _menu_effect(self):
        self.l_effect.set(self.m_effect.get())
        self.apply_lights()

    def about(self):
        messagebox.showinfo(
            "About",
            "Jungle Leopard Dashboard\n\nLCD screens and fan lights for the Jungle Leopard AIO cooler.\n"
            "Fan lights run through OpenRGB (GPL-2.0).\n\nSettings: " + str(settings.PATH),
        )

    # ---------- tabs ----------
    def _tabs(self):
        titles = ("Dashboard", "Screens", "Gallery", "Lights", "Device")
        builders = (self._tab_dash, self._tab_screens, self._tab_gallery, self._tab_lights, self._tab_device)
        self.tab = 0
        self.bar = TabBar(self.root, titles, self._show_tab)
        self.bar.pack(anchor="w", padx=10, pady=(8, 0))
        host = tk.Frame(self.root, bg=BG)
        host.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        host.grid_rowconfigure(0, weight=1)
        host.grid_columnconfigure(0, weight=1)
        self.pages = []
        for build in builders:
            page = ttk.Frame(host, style="Card.TFrame", padding=12)
            page.grid(row=0, column=0, sticky="nsew")
            build(page)
            self.pages.append(page)
        self._show_tab(0)

    def _show_tab(self, i):
        self.tab = i
        self.pages[i].tkraise()

    # -- dashboard --
    def _tab_dash(self, f):
        box = tk.Frame(f, bg=PANEL, width=PREVIEW[0], height=PREVIEW[1])
        box.pack_propagate(False)
        box.pack()
        self.preview = tk.Label(box, bg=PANEL, bd=0)
        self.preview.pack()
        bar = ttk.Frame(f, style="Card.TFrame")
        bar.pack(fill="x", pady=(8, 0))
        self.dot = tk.Canvas(bar, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.dot.pack(side="left")
        self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill=DIM, outline="")
        self.status = tk.StringVar(value="starting")
        ttk.Label(bar, textvariable=self.status, style="Card.TLabel").pack(side="left", padx=(6, 18))
        self.pv_name = tk.StringVar()
        ttk.Label(bar, textvariable=self.pv_name, style="Dim.TLabel").pack(side="left")
        self.pause_btn = ttk.Button(bar, text="Pause", style="Accent.TButton", command=self.toggle_pause_btn)
        self.pause_btn.pack(side="right")

        pin = ttk.Frame(f, style="Card.TFrame")
        pin.pack(fill="x", pady=(6, 0))
        ttk.Label(pin, text="Show:", style="Dim.TLabel").pack(side="left", padx=(0, 6))
        self.pin = tk.StringVar(value=self.cfg["pinned"] or "")
        for label, val in [("Rotate", "")] + [(n.title(), n) for n in screens.SCREENS]:
            ttk.Radiobutton(pin, text=label, value=val, variable=self.pin,
                            command=lambda: self.set_pin(self.pin.get() or None)).pack(side="left", padx=2)

    # -- screens --
    def _tab_screens(self, f):
        ttk.Label(f, text="Screens", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="Double-click to turn a screen on or off.", style="Dim.TLabel").grid(row=1, column=0, sticky="w")
        self.lb = tk.Listbox(f, height=len(screens.SCREENS), width=22, bg=RAISED, fg=FG, selectbackground=ACCENT,
                             selectforeground="#fff", highlightthickness=0, bd=0, font=("Segoe UI", 11), activestyle="none")
        self.lb.grid(row=2, column=0, sticky="nw", pady=(6, 0))
        self.lb.bind("<Double-Button-1>", lambda e: self.toggle_selected())

        side = ttk.Frame(f, style="Card.TFrame")
        side.grid(row=0, column=1, rowspan=3, sticky="nw", padx=(18, 0))
        row = ttk.Frame(side, style="Card.TFrame")
        row.pack(anchor="w")
        for text, cmd in (("On/off", self.toggle_selected), ("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1))):
            ttk.Button(row, text=text, command=cmd).pack(side="left", padx=(0, 4))
        self._fill_list()

        self.secs = tk.IntVar(value=self.cfg["rotate_seconds"])
        self.secs_lbl = ttk.Label(side, style="Card.TLabel")
        self.secs_lbl.pack(anchor="w", pady=(16, 0))
        ttk.Scale(side, from_=3, to=60, variable=self.secs, length=220, command=lambda v: self.apply_secs()).pack(anchor="w")
        ttk.Label(side, text="How long each screen stays up before the next one.", style="Dim.TLabel", wraplength=230).pack(anchor="w", pady=(4, 0))
        self.apply_secs()

    def _fill_list(self, keep=None):
        sel = keep if keep is not None else (self.lb.curselection() or (0,))[0]
        self.lb.delete(0, "end")
        for n in self.order:
            self.lb.insert("end", ("✔  " if self.enabled[n] else "☐  ") + n.title())
        self.lb.selection_set(sel)

    def toggle_selected(self):
        i = (self.lb.curselection() or (0,))[0]
        n = self.order[i]
        self.enabled[n] = not self.enabled[n]
        if not any(self.enabled.values()):
            self.enabled[n] = True  # at least one screen must stay on
        self._fill_list(i)
        self._save_screens()

    def move(self, d):
        i = (self.lb.curselection() or (0,))[0]
        j = i + d
        if 0 <= j < len(self.order):
            self.order[i], self.order[j] = self.order[j], self.order[i]
            self._fill_list(j)
            self._save_screens()

    def set_pin(self, name):
        self.cfg["pinned"] = self.runner.pinned = name
        self.pin.set(name or "")
        self.m_show.set(name or "")
        self.save()

    # -- gallery --
    def _tab_gallery(self, f):
        ttk.Label(f, text="Gallery", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="Pictures, GIFs and videos shown full-screen on the LCD.", style="Dim.TLabel").grid(row=1, column=0, sticky="w")
        wrap = tk.Frame(f, bg=RAISED)
        wrap.grid(row=2, column=0, sticky="nw", pady=(6, 0))
        self.gl = tk.Listbox(wrap, height=9, width=34, bg=RAISED, fg=FG, selectbackground=ACCENT, selectforeground="#fff",
                             highlightthickness=0, bd=0, font=("Segoe UI", 10), activestyle="none", exportselection=False)
        sb = ttk.Scrollbar(wrap, command=self.gl.yview)
        self.gl.config(yscrollcommand=sb.set)
        self.gl.pack(side="left")
        sb.pack(side="left", fill="y")

        side = ttk.Frame(f, style="Card.TFrame")
        side.grid(row=0, column=1, rowspan=3, sticky="nw", padx=(18, 0))
        ttk.Button(side, text="Add files...", style="Accent.TButton", command=self.add_files).pack(fill="x")
        for text, cmd in (("Add folder...", self.add_folder), ("Remove", self.remove_item),
                          ("Move up", lambda: self.move_item(-1)), ("Move down", lambda: self.move_item(1)),
                          ("Clear all", self.clear_items)):
            ttk.Button(side, text=text, command=cmd).pack(fill="x", pady=(4, 0))
        self.g_secs = tk.IntVar(value=self.cfg["gallery"]["image_seconds"])
        self.g_lbl = ttk.Label(side, style="Card.TLabel")
        self.g_lbl.pack(anchor="w", pady=(14, 0))
        ttk.Scale(side, from_=2, to=60, variable=self.g_secs, length=150, command=lambda v: self.apply_gallery_secs()).pack(anchor="w")
        self.g_hint = ttk.Label(f, style="Dim.TLabel", wraplength=480)
        self.g_hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._fill_gallery()
        self.apply_gallery_secs()

    def _fill_gallery(self, keep=None):
        items = self.cfg["gallery"]["items"]
        sel = keep if keep is not None else (self.gl.curselection() or (0,))[0]
        self.gl.delete(0, "end")
        for p in items:
            self.gl.insert("end", ("▣  " if gal.kind(p) == "image" else "▶  ") + os.path.basename(p))
        if items:
            self.gl.selection_set(min(sel, len(items) - 1))
        n = len(items)
        self.g_hint.config(text=(f"{n} item{'s' if n != 1 else ''}. ▣ pictures show for the time on the right; "
                                 "▶ GIFs and videos play to the end (up to 90 s)."
                                 if n else "Nothing here yet. Add files or a folder, then pick Gallery on the Dashboard to see it."))
        self._gallery_changed()

    def _gallery_changed(self):
        self.gallery.set_items(self.cfg["gallery"]["items"])
        self.save()
        if self.cfg["gallery"]["items"] and not self.enabled["gallery"]:
            self.enabled["gallery"] = True
            self._fill_list()
            self._save_screens()

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Add to gallery", parent=self.root, filetypes=gal.FILETYPES)
        self._add(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="Add all pictures and videos in a folder", parent=self.root)
        if d:
            self._add(sorted(os.path.join(d, n) for n in os.listdir(d)))

    def _add(self, paths):
        items = self.cfg["gallery"]["items"]
        new = [p for p in paths if gal.kind(p) and p not in items]
        if new:
            items.extend(new)
            self._fill_gallery(keep=len(items) - 1)
            self.set_pin("gallery")

    def remove_item(self):
        items = self.cfg["gallery"]["items"]
        if items and self.gl.curselection():
            i = self.gl.curselection()[0]
            del items[i]
            self._fill_gallery(keep=i)

    def move_item(self, d):
        items = self.cfg["gallery"]["items"]
        if not self.gl.curselection():
            return
        i = self.gl.curselection()[0]
        j = i + d
        if 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]
            self._fill_gallery(keep=j)

    def clear_items(self):
        if self.cfg["gallery"]["items"] and messagebox.askyesno("Clear gallery", "Remove all items from the gallery?\n(Your files are not deleted.)", parent=self.root):
            self.cfg["gallery"]["items"].clear()
            self._fill_gallery()

    def apply_gallery_secs(self):
        n = int(round(self.g_secs.get()))
        self.g_lbl.config(text=f"Picture time: {n} s")
        self.cfg["gallery"]["image_seconds"] = self.gallery.image_seconds = n
        self.save()

    # -- lights --
    def _tab_lights(self, f):
        lc = self.lights.cfg
        ttk.Label(f, text="Fan lights", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        self.lstatus = tk.StringVar()
        ttk.Label(f, textvariable=self.lstatus, style="Dim.TLabel").grid(row=0, column=1, columnspan=3, sticky="e")
        ttk.Label(f, text="Controls the addressable header (D_LED2) through OpenRGB.", style="Dim.TLabel").grid(row=1, column=0, columnspan=4, sticky="w")

        self.l_on = tk.BooleanVar(value=lc["enabled"])
        ttk.Checkbutton(f, text="Control fan lights", variable=self.l_on, command=self.apply_lights).grid(row=2, column=0, sticky="w", pady=(8, 0))

        ttk.Label(f, text="Effect", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.l_effect = tk.StringVar(value=lc["effect"])
        cb = ttk.Combobox(f, textvariable=self.l_effect, state="readonly", width=14, values=lights.EFFECTS)
        cb.grid(row=3, column=1, sticky="w", padx=8, pady=(8, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_lights())

        ttk.Label(f, text="Colour", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.l_swatch = tk.Button(f, width=6, relief="flat", command=self.pick_color, bd=0)
        self.l_swatch.grid(row=4, column=1, sticky="w", padx=8, pady=(8, 0))
        pre = ttk.Frame(f, style="Card.TFrame")
        pre.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))
        for name, rgb in PRESETS:
            cmd = self.use_claude_palette if name == "Claude" else (lambda c=rgb: self.set_color(c))
            tk.Button(pre, text=name, relief="flat", bd=0, padx=10, pady=6, bg="#%02x%02x%02x" % rgb,
                      fg="#000" if sum(rgb) > 450 else "#fff", command=cmd).pack(side="left", padx=3)
        self._paint_swatch()

        ttk.Label(f, text="Speed", style="Card.TLabel").grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.l_speed = tk.IntVar(value=lc["speed"])
        ttk.Scale(f, from_=1, to=100, variable=self.l_speed, length=180, command=lambda v: self.apply_lights()).grid(row=6, column=1, columnspan=2, sticky="w", padx=8, pady=(8, 0))

        ttk.Label(f, text="LEDs on header", style="Card.TLabel").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.l_leds = tk.IntVar(value=lc["leds"])
        ttk.Spinbox(f, from_=1, to=64, width=5, textvariable=self.l_leds, command=self.apply_lights).grid(row=7, column=1, sticky="w", padx=8, pady=(8, 0))
        self.l_leds.trace_add("write", lambda *a: self.apply_lights())
        ttk.Label(f, text="Set to the real count so rainbow runs evenly across the fans.", style="Dim.TLabel").grid(row=8, column=0, columnspan=4, sticky="w", pady=(2, 0))

        self.l_install = ttk.Button(f, text="Install OpenRGB", style="Accent.TButton", command=self.install_orgb)
        if not lights.openrgb_installed():
            self.l_install.grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _paint_swatch(self):
        r, g, b = self.lights.cfg["color"]
        hexc = "#%02x%02x%02x" % (r, g, b)
        self.l_swatch.config(bg=hexc, activebackground=hexc)

    def use_claude_palette(self):
        """The Claude preset: the full brand palette flowing across every LED."""
        self.l_on.set(True)
        self.l_effect.set("Claude")
        self.apply_lights()

    def set_color(self, rgb):
        self.lights.cfg["color"] = [int(x) for x in rgb]
        self._paint_swatch()
        self.apply_lights()

    def pick_color(self):
        rgb, _ = colorchooser.askcolor(color="#%02x%02x%02x" % tuple(self.lights.cfg["color"]), parent=self.root)
        if rgb:
            self.set_color(rgb)

    def apply_lights(self):
        c = self.lights.cfg
        c["enabled"] = bool(self.l_on.get())
        c["effect"] = self.l_effect.get()
        c["speed"] = int(round(self.l_speed.get()))
        try:
            c["leds"] = max(1, min(64, int(self.l_leds.get())))
        except (tk.TclError, ValueError):
            pass  # mid-typing in the spinbox
        self.m_lights.set(c["enabled"])
        self.m_effect.set(c["effect"])
        self.save()

    def install_orgb(self):
        self.l_install.config(state="disabled", text="Downloading...")

        def work():
            try:
                lights.install_openrgb()
                err = None
            except Exception as e:
                err = str(e)[:70]
            self.root.after(0, lambda: self._installed(err))

        threading.Thread(target=work, daemon=True).start()

    def _installed(self, err):
        if err:
            self.l_install.config(state="normal", text="Retry install")
            messagebox.showerror("OpenRGB install failed", err, parent=self.root)
        else:
            self.l_install.grid_remove()

    # -- device --
    def _tab_device(self, f):
        ttk.Label(f, text="Cooler display", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        self.bright = tk.IntVar(value=self.cfg["brightness"])
        self.bright_lbl = ttk.Label(f, style="Card.TLabel")
        self.bright_lbl.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(f, from_=0, to=100, variable=self.bright, length=280, command=lambda v: self.apply_bright()).grid(row=2, column=0, sticky="w")
        self.auto = tk.BooleanVar(value=os.path.exists(STARTUP))
        ttk.Checkbutton(f, text="Start with Windows (minimized)", variable=self.auto, command=self.toggle_auto).grid(row=3, column=0, sticky="w", pady=(10, 0))

        ttk.Label(f, text="Data sources", style="Head.TLabel").grid(row=4, column=0, sticky="w", pady=(18, 4))
        self.src = {}
        for i, key in enumerate(("Cooler LCD", "GPU (nvidia-smi)", "Hardware sensors", "Media controls", "OpenRGB")):
            ttk.Label(f, text=key, style="Card.TLabel").grid(row=5 + i, column=0, sticky="w", pady=2)
            v = tk.StringVar()
            lab = tk.Label(f, textvariable=v, bg=PANEL, fg=DIM, anchor="w")
            lab.grid(row=5 + i, column=1, sticky="w", padx=14)
            self.src[key] = (v, lab)
        self.hw_btn = ttk.Button(f, text="", style="Accent.TButton", command=self.hw_action)
        self.hw_btn.grid(row=10, column=0, sticky="w", pady=(12, 0))
        ttk.Label(f, text="Optional: CPU temperature and fan RPM via LibreHardwareMonitor (runs as administrator).",
                  style="Dim.TLabel", wraplength=470).grid(row=11, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.apply_bright()

    def hw_action(self):
        if not hwapp.installed():
            self.hw_btn.config(state="disabled", text="Downloading...")

            def work():
                try:
                    hwapp.install()
                    err = None
                except Exception as e:
                    err = str(e)[:80]
                self.root.after(0, lambda: self._hw_installed(err))

            threading.Thread(target=work, daemon=True).start()
        elif not sensors.hw.available:
            if messagebox.askokcancel(
                    "Start sensor app",
                    "LibreHardwareMonitor needs administrator rights to read CPU and fan sensors."
                    " Windows will ask you to approve it. It starts hidden in the tray.", parent=self.root):
                hwapp.launch_elevated()

    def _hw_installed(self, err):
        if err:
            messagebox.showerror("Install failed", err, parent=self.root)

    def apply_bright(self):
        n = int(round(self.bright.get()))
        self.bright_lbl.config(text=f"Backlight {n}%")
        self.cfg["brightness"] = self.runner.brightness = n
        self.save()

    def toggle_auto(self):
        if self.auto.get():
            pyw = sys.executable.replace("python.exe", "pythonw.exe")
            with open(STARTUP, "w") as f:
                f.write('CreateObject("WScript.Shell").Run """%s"" ""%s"" --minimized", 0, False\n' % (pyw, os.path.join(HERE, "gui.pyw")))
        elif os.path.exists(STARTUP):
            os.remove(STARTUP)

    def apply_secs(self):
        n = int(round(self.secs.get()))
        self.secs_lbl.config(text=f"Switch screens every {n} s")
        self.cfg["rotate_seconds"] = self.runner.rotate_seconds = n
        self.save()

    # ---------- shared actions ----------
    def toggle_pause_btn(self):
        self.m_pause.set(not self.runner.paused)
        self.toggle_pause()

    def toggle_pause(self):
        self.runner.paused = self.m_pause.get()
        self.pause_btn.config(text="Resume" if self.runner.paused else "Pause")

    # ---------- refresh ----------
    def _src_status(self):
        r = self.runner.status
        orgb = lights.openrgb_installed()
        rows = {
            "Cooler LCD": (r, GOOD if r == "running" else WARN if r == "paused" else BAD),
            "GPU (nvidia-smi)": ("ok" if sensors.gpu.data else "not found", GOOD if sensors.gpu.data else DIM),
            "Hardware sensors": ("LibreHardwareMonitor connected" if sensors.hw.available else "not running (optional: CPU temp, fan RPM)", GOOD if sensors.hw.available else DIM),
            "Media controls": ("ok" if sensors.media.available else "unavailable", GOOD if sensors.media.available else DIM),
            "OpenRGB": (("installed - " + self.lights.status) if orgb else "not installed", GOOD if orgb and not self.lights.status.startswith("error") else WARN),
        }
        for key, (text, col) in rows.items():
            v, lab = self.src[key]
            v.set(text)
            lab.config(fg=col)
        if not hwapp.installed():
            self.hw_btn.config(state="normal", text="Install sensor app")
        elif sensors.hw.available:
            self.hw_btn.config(state="disabled", text="Sensor app running")
        else:
            self.hw_btn.config(state="normal", text="Start sensor app (admin)")

    def tick(self):
        s = self.runner.status
        self.status.set(s)
        self.lstatus.set(self.lights.status)
        self.dot.itemconfig(self.dot_id, fill=GOOD if s == "running" else WARN if s == "paused" else BAD)
        if self.tab == 4:
            self._src_status()
        img = self.runner.last_image
        if self.tab == 0 and img is not None and self.root.state() != "iconic":
            try:
                self._photo = ImageTk.PhotoImage(img.resize(PREVIEW))
                self.preview.config(image=self._photo)
                self.pv_name.set("Now showing: " + str(self.runner.current).title())
            except Exception:
                pass
        self.root.after(1000, self.tick)

    def quit(self):
        self.lights.shutdown()
        self.runner.shutdown()
        self.gallery.stop_stream()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Gui(root, minimized="--minimized" in sys.argv)
    root.mainloop()
