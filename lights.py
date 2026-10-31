"""Fan-light control via a local OpenRGB SDK server (motherboard D_LED2 header).

OpenRGB is run headless from %APPDATA%\\JLDash\\openrgb (portable build, GPL-2.0,
not bundled in this repo). The server is started on demand and stopped on exit.
"""
import colorsys
import math
import os
import subprocess
import threading
import time
from pathlib import Path

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

ORGB_DIR = Path(os.environ.get("APPDATA", Path.home())) / "JLDash" / "openrgb"
ORGB_EXE = ORGB_DIR / "OpenRGB.exe"
HOST, PORT = "127.0.0.1", 6742
EFFECTS = ["Claude", "Claude light", "Static", "Breathing", "Rainbow", "Color cycle", "Off"]

# The Claude brand palette, ordered so neighbouring colours blend into a pleasing loop:
# clay -> kraft -> manilla -> ivory -> heather -> sky -> olive -> fig -> book cloth -> clay
CLAUDE_LIGHT = [
    (217, 119, 87),   # clay
    (212, 162, 127),  # kraft
    (235, 219, 188),  # manilla
    (240, 240, 235),  # ivory
    (203, 202, 219),  # heather
    (106, 155, 204),  # sky
    (120, 140, 93),   # olive
    (196, 102, 134),  # fig
    (204, 120, 92),   # book cloth
]


# Dark version: the same brand hues, deeper and more saturated, with near-black troughs between
# them so the colours stay distinct instead of blending into pastel.
CLAUDE_DARK = [
    (190, 70, 30),    # clay, deepened
    (70, 22, 8),      # ember (dark trough)
    (150, 98, 40),    # kraft, deepened
    (45, 70, 25),     # olive
    (12, 55, 95),     # sky, deepened
    (40, 30, 120),    # heather -> indigo
    (125, 25, 75),    # fig
    (45, 12, 20),     # wine (dark trough)
]


def palette_color(p, palette=CLAUDE_DARK):
    """Smoothly interpolate around a looping palette; p is 0..1."""
    n = len(palette)
    x = (p % 1.0) * n
    i = int(x)
    f = x - i
    a, b = palette[i % n], palette[(i + 1) % n]
    return tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))
DEFAULTS = {
    "enabled": False,
    "effect": "Claude",
    "color": [217, 119, 87],
    "speed": 50,  # 1-100
    "leds": 32,
    "zone": "D_LED2",
}


OPENRGB_URL = "https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_1.1/OpenRGB_1.1_Windows_64_8e16de2.zip"
OPENRGB_SHA256 = "63291726c6fc84eb479ef2ee752e97e1187f6ce9c49fd27eee40ded588a8172a"


def openrgb_installed():
    return ORGB_EXE.exists()


def install_openrgb():
    """Download the pinned portable OpenRGB release, verify its hash, extract to ORGB_DIR."""
    import hashlib
    import io
    import zipfile

    import requests

    data = requests.get(OPENRGB_URL, timeout=120).content
    if hashlib.sha256(data).hexdigest() != OPENRGB_SHA256:
        raise RuntimeError("OpenRGB download failed its hash check; nothing was installed")
    ORGB_DIR.mkdir(parents=True, exist_ok=True)
    root = ORGB_DIR.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            parts = Path(info.filename).parts[1:]  # drop the top-level folder
            if not parts or info.is_dir():
                continue
            target = (ORGB_DIR.joinpath(*parts)).resolve()
            if root not in target.parents:
                raise RuntimeError("unsafe path in archive: %s" % info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))


def frame(effect, color, speed, n, t):
    """Return a list of n (r, g, b) tuples for time t (seconds)."""
    r, g, b = color
    rate = 0.1 + speed / 100 * 1.9  # cycles per second-ish
    if effect == "Off":
        return [(0, 0, 0)] * n
    if effect == "Breathing":
        k = (math.sin(t * rate * math.pi) + 1) / 2
        k = 0.05 + 0.95 * k
        return [(int(r * k), int(g * k), int(b * k))] * n
    if effect in ("Claude", "Claude light"):
        # the whole palette spread along every LED, drifting slowly along the header
        pal = CLAUDE_DARK if effect == "Claude" else CLAUDE_LIGHT
        return [palette_color(i / max(n, 1) - t * rate * 0.06, pal) for i in range(n)]
    if effect == "Rainbow":
        out = []
        for i in range(n):
            rr, gg, bb = colorsys.hsv_to_rgb((i / max(n, 1) - t * rate * 0.3) % 1.0, 1, 1)
            out.append((int(rr * 255), int(gg * 255), int(bb * 255)))
        return out
    if effect == "Color cycle":
        rr, gg, bb = colorsys.hsv_to_rgb((t * rate * 0.2) % 1.0, 1, 1)
        return [(int(rr * 255), int(gg * 255), int(bb * 255))] * n
    return [(r, g, b)] * n  # Static


class Lights:
    def __init__(self, cfg=None):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.status = "off"
        self.stop = threading.Event()
        self._proc = None  # server we started (so we only kill our own)
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def shutdown(self):
        self.stop.set()
        self._thread.join(timeout=3)
        if self._proc:
            self._proc.terminate()

    # -- server / connection --
    def _connect(self):
        try:
            return OpenRGBClient(HOST, PORT, "jl-dash")
        except Exception:
            pass
        if not ORGB_EXE.exists():
            raise RuntimeError("OpenRGB not found in %s" % ORGB_DIR)
        self.status = "starting OpenRGB..."
        self._proc = subprocess.Popen(
            [str(ORGB_EXE), "--server"], cwd=ORGB_DIR, creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        for _ in range(60):
            if self.stop.wait(1):
                return None
            try:
                return OpenRGBClient(HOST, PORT, "jl-dash")
            except Exception:
                continue
        raise RuntimeError("OpenRGB server did not start")

    def _zone(self, client):
        board = next(d for d in client.devices if d.type.name == "MOTHERBOARD")
        zone = next(z for z in board.zones if z.name == self.cfg["zone"])
        board.set_mode("Direct")
        n = int(self.cfg["leds"])
        if len(zone.leds) != n:
            zone.resize(n)
            board = next(d for d in client.devices if d.type.name == "MOTHERBOARD")
            zone = next(z for z in board.zones if z.name == self.cfg["zone"])
        return zone

    # -- main loop --
    def _loop(self):
        client = zone = None
        leds = None
        last = None
        t0 = time.time()
        while not self.stop.is_set():
            if not self.cfg["enabled"]:
                self.status = "off"
                last = None
                self.stop.wait(0.5)
                continue
            try:
                if client is None:
                    client = self._connect()
                    if client is None:
                        break
                    zone, leds = None, None
                if zone is None or leds != self.cfg["leds"]:
                    zone = self._zone(client)
                    leds, last = self.cfg["leds"], None
                self.status = "on"
                c = self.cfg
                f = frame(c["effect"], c["color"], c["speed"], int(c["leds"]), time.time() - t0)
                if f != last:  # static colors only need one write
                    zone.set_colors([RGBColor(*p) for p in f])
                    last = f
                self.stop.wait(0.05 if c["effect"] not in ("Static", "Off") else 0.25)
            except Exception as e:
                self.status = "error: %s" % str(e)[:40]
                client = zone = None
                self.stop.wait(3)
