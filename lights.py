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
EFFECTS = ["Static", "Breathing", "Rainbow", "Color cycle", "Off"]
DEFAULTS = {
    "enabled": False,
    "effect": "Static",
    "color": [217, 119, 87],
    "speed": 50,  # 1-100
    "leds": 32,
    "zone": "D_LED2",
}


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
