"""Background data pollers. Each runs in a daemon thread and exposes plain attributes."""
import asyncio
import io
import re
import subprocess
import threading
import time
from collections import deque

import psutil
import requests

CREATE_NO_WINDOW = 0x08000000


def _thread(fn):
    threading.Thread(target=fn, daemon=True).start()


# ---------- GPU (nvidia-smi: no driver or admin needed) ----------
class GpuStats:
    FIELDS = "temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed,clocks.gr"

    def __init__(self, every=1.0):
        self.every, self.data = every, None
        _thread(self._loop)

    def _loop(self):
        cmd = ["nvidia-smi", f"--query-gpu={self.FIELDS}", "--format=csv,noheader,nounits"]
        while True:
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                                     creationflags=CREATE_NO_WINDOW).stdout
                v = [float(x) for x in out.strip().splitlines()[0].split(",")]
                self.data = dict(zip(["temp", "util", "mem_used", "mem_total", "power", "fan", "clock"], v))
            except Exception:
                self.data = None  # no NVIDIA GPU / nvidia-smi missing
                time.sleep(10)
            time.sleep(self.every)


# ---------- network ----------
class NetStats:
    def __init__(self, history=60):
        self.down = self.up = 0.0  # bytes/s
        self.down_hist = deque([0.0] * history, maxlen=history)
        self.up_hist = deque([0.0] * history, maxlen=history)
        self.total_down = self.total_up = 0  # bytes since the app started
        _thread(self._loop)

    def _loop(self):
        last, t = psutil.net_io_counters(), time.time()
        start = last
        while True:
            time.sleep(1)
            cur, now = psutil.net_io_counters(), time.time()
            dt = max(now - t, 1e-6)
            self.down = max(0.0, (cur.bytes_recv - last.bytes_recv) / dt)
            self.up = max(0.0, (cur.bytes_sent - last.bytes_sent) / dt)
            self.down_hist.append(self.down)
            self.up_hist.append(self.up)
            self.total_down = cur.bytes_recv - start.bytes_recv
            self.total_up = cur.bytes_sent - start.bytes_sent
            last, t = cur, now


# ---------- now playing (Windows media controls: Spotify, browsers, etc.) ----------
class MediaInfo:
    def __init__(self):
        self.title = self.artist = self.album = ""
        self.playing = False
        self.position = self.duration = 0.0
        self.art = None  # PIL image or None
        self.available = False
        self._art_key = None
        _thread(lambda: asyncio.run(self._loop()))

    async def _read_art(self, ref):
        from PIL import Image
        from winrt.windows.storage.streams import Buffer, InputStreamOptions

        stream = await ref.open_read_async()
        size = int(stream.size)
        buf = Buffer(size)
        await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
        return Image.open(io.BytesIO(bytes(memoryview(buf)))).convert("RGB")

    async def _loop(self):
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
            )
            mgr = await Manager.request_async()
            self.available = True
        except Exception:
            return  # winrt not installed / unsupported OS
        while True:
            try:
                s = mgr.get_current_session()
                if s is None:
                    self.title = self.artist = self.album = ""
                    self.playing, self.art, self._art_key = False, None, None
                else:
                    p = await s.try_get_media_properties_async()
                    tl = s.get_timeline_properties()
                    self.title, self.artist, self.album = p.title, p.artist, p.album_title
                    self.playing = s.get_playback_info().playback_status == Status.PLAYING
                    self.duration = tl.end_time.total_seconds() - tl.start_time.total_seconds()
                    pos = tl.position.total_seconds()
                    if self.playing:  # timeline is a snapshot; extrapolate from its update time
                        pos += (datetime.now(tl.last_updated_time.tzinfo) - tl.last_updated_time).total_seconds()
                    self.position = max(0.0, min(pos, self.duration or pos))
                    key = (self.title, self.artist)
                    if key != self._art_key:
                        self._art_key = key
                        try:
                            self.art = await self._read_art(p.thumbnail) if p.thumbnail else None
                        except Exception:
                            self.art = None
            except Exception:
                pass
            await asyncio.sleep(1)


# ---------- LibreHardwareMonitor (optional: CPU temp, fan RPM) ----------
def _num(text):
    """'45,0 °C' / '1203 RPM' -> float (None if not a number)."""
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(text))
    return float(m.group(0).replace(",", ".")) if m else None


class HwSensors:
    """Reads LibreHardwareMonitor's built-in web server (http://localhost:8085/data.json).

    The app must be running as administrator; hwapp.py installs and starts it.
    """
    URL = "http://127.0.0.1:8085/data.json"
    CPU_TEMP_NAMES = ("CPU Package", "Core (Tctl/Tdie)", "Core (Tdie)", "CPU Total", "Package")

    def __init__(self, every=2.0):
        self.every = every
        self.available = False
        self.cpu_temp = None
        self.cpu_power = None
        self.fans = []  # [(name, rpm)] excluding GPU fans (those come from nvidia-smi)
        _thread(self._loop)

    def _walk(self, node, path, out):
        text = node.get("Text", "")
        kids = node.get("Children") or []
        if not kids and node.get("Value") not in (None, ""):
            out.append((path, text, node["Value"]))
        for k in kids:
            self._walk(k, path + [text], out)

    def _parse(self, tree):
        leaves = []
        self._walk(tree, [], leaves)
        temps, powers, fans = {}, {}, []
        for path, name, value in leaves:
            group = path[-1] if path else ""
            v = _num(value)
            if v is None:
                continue
            hw = " ".join(path).lower()
            gpu = any(k in hw for k in ("nvidia", "geforce", "radeon", "intel arc"))
            if group.startswith("Temperature") and not gpu and "gpu" not in name.lower():
                temps.setdefault(name, v)
            elif group.startswith("Power") and "package" in name.lower() and not gpu:
                powers.setdefault(name, v)
            elif group.startswith("Fan") and not gpu and "RPM" in str(value) and v > 0:
                fans.append((name, v))
        self.cpu_temp = next((temps[k] for k in self.CPU_TEMP_NAMES if k in temps), None)
        if self.cpu_temp is None:
            self.cpu_temp = next((v for k, v in temps.items() if "CPU" in k or "Core" in k), None)
        self.cpu_power = next(iter(powers.values()), None)
        self.fans = fans

    def _loop(self):
        while True:
            try:
                r = requests.get(self.URL, timeout=2)
                r.raise_for_status()
                self._parse(r.json())
                self.available = True
            except Exception:
                self.available = False
                self.cpu_temp = self.cpu_power = None
                self.fans = []
                time.sleep(8)
            time.sleep(self.every)


gpu = GpuStats()
net = NetStats()
media = MediaInfo()
hw = HwSensors()
