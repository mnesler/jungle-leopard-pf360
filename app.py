"""Multi-screen dashboard for the Jungle Leopard LCD.

Usage: python app.py [seconds] [--screen NAME]   (screens: system, claude, usage)
"""
import io
import sys
import threading
import time
from datetime import datetime

import psutil
import requests
from PIL import Image, ImageDraw

from jl import Display
from usage import UsageStats, fmt

W, H = 1024, 600
BG, FG, DIM, PANEL = (12, 14, 26), (240, 244, 255), (120, 130, 160), (22, 26, 44)
OK, WARN, BAD, ACCENT = (70, 210, 130), (250, 190, 60), (250, 90, 90), (217, 119, 87)
SCREEN_SECONDS = 10


# ---------- helpers ----------
def cpu_temp():
    try:
        for entries in psutil.sensors_temperatures().values():
            if entries:
                return entries[0].current
    except Exception:
        pass
    return None


def bar(d, x, y, w, h, frac, color):
    d.rounded_rectangle([x, y, x + w, y + h], 10, fill=(30, 34, 54))
    if frac > 0:
        d.rounded_rectangle([x, y, x + max(h, w * min(frac, 1)), y + h], 10, fill=color)


def new_canvas():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


# ---------- Claude status poller ----------
class ClaudeStatus:
    URL = "https://status.claude.com/api/v2/summary.json"

    def __init__(self, every=60):
        self.every = every
        self.data = None
        self.error = None
        self.updated = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                r = requests.get(self.URL, timeout=10)
                r.raise_for_status()
                self.data, self.error, self.updated = r.json(), None, datetime.now()
            except Exception as e:
                self.error = str(e)[:60]
            time.sleep(self.every)


claude = ClaudeStatus()


def status_color(s):
    return {"operational": OK, "under_maintenance": ACCENT}.get(
        s, WARN if s in ("degraded_performance", "partial_outage") else BAD
    )


# ---------- screens ----------
def screen_system():
    img, d = new_canvas()
    now = datetime.now()
    d.text((60, 40), now.strftime("%H:%M"), fill=FG, font_size=120)
    d.text((64, 175), now.strftime("%A, %B %d"), fill=DIM, font_size=36)
    for i, (name, val, col) in enumerate(
        [("CPU", psutil.cpu_percent(), (80, 200, 255)), ("RAM", psutil.virtual_memory().percent, (160, 120, 255))]
    ):
        y = 280 + i * 120
        d.text((60, y), name, fill=DIM, font_size=36)
        d.text((W - 60, y), f"{val:.0f}%", fill=FG, font_size=48, anchor="ra")
        bar(d, 60, y + 60, W - 120, 24, val / 100, col)
    t = cpu_temp()
    if t is not None:
        d.text((W - 60, 60), f"{t:.0f}°C", fill=FG, font_size=64, anchor="ra")
    return img


def screen_claude():
    img, d = new_canvas()
    d.text((60, 40), "Claude Status", fill=FG, font_size=64)
    data = claude.data
    if not data:
        d.text((60, 200), claude.error or "Loading...", fill=DIM, font_size=40)
        return img
    overall = data["status"]
    col = {"none": OK, "minor": WARN, "major": BAD, "critical": BAD}.get(overall["indicator"], WARN)
    d.ellipse([W - 110, 52, W - 60, 102], fill=col)
    d.text((60, 120), overall["description"], fill=col, font_size=40)

    comps = [c for c in data["components"] if not c.get("group")]
    for i, c in enumerate(comps[:6]):
        col_i, row = i % 2, i // 2
        x, y = 60 + col_i * 470, 200 + row * 80
        d.rounded_rectangle([x, y, x + 450, y + 66], 12, fill=PANEL)
        d.ellipse([x + 16, y + 21, x + 40, y + 45], fill=status_color(c["status"]))
        name = c["name"].split(" (")[0]
        d.text((x + 56, y + 33), name, fill=FG, font_size=28, anchor="lm")

    incs = data.get("incidents", [])
    y = 200 + ((min(len(comps), 6) + 1) // 2) * 80 + 10
    if incs:
        d.text((60, y), "Active incident", fill=WARN, font_size=28)
        d.text((60, y + 38), incs[0]["name"][:60], fill=FG, font_size=32)
    else:
        d.text((60, y), "No active incidents", fill=DIM, font_size=28)
    if claude.updated:
        d.text((W - 60, H - 40), f"updated {claude.updated:%H:%M:%S}", fill=DIM, font_size=22, anchor="rs")
    return img


usage = UsageStats()


def screen_usage():
    img, d = new_canvas()
    d.text((60, 40), "Claude Usage", fill=FG, font_size=64)
    days = usage.last_days(7)
    today = days[-1][1]
    d.text((W - 60, 40), fmt(today["tokens"]), fill=ACCENT, font_size=64, anchor="ra")
    d.text((W - 60, 112), f"tokens today · {today['msgs']} messages", fill=DIM, font_size=26, anchor="ra")

    # 7-day bar chart
    top = max([v["tokens"] for _, v in days] + [1])
    x0, base, ch, bw, gap = 60, 440, 220, 100, 36
    for i, (date, v) in enumerate(days):
        x = x0 + i * (bw + gap)
        h = max(4, int(ch * v["tokens"] / top)) if v["tokens"] else 4
        d.rounded_rectangle([x, base - h, x + bw, base], 8, fill=ACCENT if i == 6 else (70, 78, 110))
        if v["tokens"]:
            d.text((x + bw / 2, base - h - 8), fmt(v["tokens"]), fill=FG, font_size=22, anchor="ms")
        d.text((x + bw / 2, base + 12), date.strftime("%a"), fill=DIM, font_size=24, anchor="mt")

    # model breakdown (last 7 days)
    models = sorted(((m, t) for m, t in usage.models.items() if t), key=lambda x: -x[1])[:3]
    total = sum(t for _, t in models) or 1
    palette = [ACCENT, (80, 200, 255), (160, 120, 255)]
    x = 60
    for (m, t), col in zip(models, palette):
        w = int((W - 120) * t / total)
        d.rectangle([x, 520, x + w, 530], fill=col)
        x += w
    x = 60
    for (m, t), col in zip(models, palette):
        d.ellipse([x, 548, x + 14, 562], fill=col)
        label = f"{m.replace('claude-', '')} {fmt(t)}"
        d.text((x + 22, 555), label, fill=DIM, font_size=22, anchor="lm")
        x += 22 + int(d.textlength(label, font_size=22)) + 36
    if usage.error:
        d.text((W - 60, H - 20), usage.error, fill=BAD, font_size=18, anchor="rs")
    return img


SCREENS = {"system": screen_system, "claude": screen_claude, "usage": screen_usage}


# ---------- main loop ----------
def to_jpeg(img):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80, subsampling=2)
    return buf.getvalue()


class Runner:
    """Drives the LCD. Reconnects automatically if the port drops or is busy."""

    def __init__(self, brightness=95, rotate_seconds=SCREEN_SECONDS, screens=None, pinned=None):
        self.stop = threading.Event()
        self.paused = False
        self.pinned = pinned  # screen name, or None to rotate
        self.brightness = brightness
        self.rotate_seconds = rotate_seconds
        self.screens = list(screens or SCREENS)
        self.status = "starting"
        self.current = None  # name of the screen being shown
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        self.thread.join(timeout=5)

    def _session(self):
        d = Display()
        try:
            d.prime()
            d.command(0x11, read=False)
            applied = None
            idx, switched, last_ka = 0, time.time(), 0.0
            while not self.stop.is_set():
                now = time.time()
                if now - last_ka > 1.0:
                    d.keepalive()
                    last_ka = now
                if applied != self.brightness:
                    d.command(0x03, [max(0, min(100, int(self.brightness)))], read=False)
                    applied = self.brightness
                if self.paused:
                    self.status = "paused"
                    time.sleep(0.25)
                    continue
                self.status = "running"
                names = [n for n in self.screens if n in SCREENS] or list(SCREENS)
                if now - switched >= self.rotate_seconds:
                    idx, switched = idx + 1, now
                name = self.pinned if self.pinned in SCREENS else names[idx % len(names)]
                self.current = name
                d.send_jpeg(to_jpeg(SCREENS[name]()))
                time.sleep(0.25)
        finally:
            try:
                d.close()
            except Exception:
                pass

    def _run(self):
        while not self.stop.is_set():
            try:
                self._session()
            except Exception as e:
                # device missing, or port held by the vendor app
                self.status = "waiting for device (%s)" % str(e)[:40]
                self.stop.wait(3)


def main():
    args = sys.argv[1:]
    runner = Runner()
    runner.pinned = args[args.index("--screen") + 1] if "--screen" in args else None
    nums = [a for a in args if a.replace(".", "").isdigit()]
    runner.start()
    try:
        runner.stop.wait(float(nums[0]) if nums else None)
    except KeyboardInterrupt:
        pass
    runner.shutdown()


if __name__ == "__main__":
    main()
