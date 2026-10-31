"""LCD screens. Each screen is a function returning a 1024x600 PIL image."""
from datetime import datetime

import psutil
from PIL import Image, ImageDraw

from gallery import gallery
from sensors import gpu, hw, media, net
from usage import UsageStats, fmt

W, H = 1024, 600
BG, FG, DIM, PANEL = (12, 14, 26), (240, 244, 255), (120, 130, 160), (22, 26, 44)
OK, WARN, BAD, ACCENT = (70, 210, 130), (250, 190, 60), (250, 90, 90), (217, 119, 87)
BLUE, GREEN, PURPLE = (80, 200, 255), (120, 220, 140), (160, 120, 255)

usage = UsageStats()


# ---------- helpers ----------
def new_canvas():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def bar(d, x, y, w, h, frac, color):
    d.rounded_rectangle([x, y, x + w, y + h], 10, fill=(30, 34, 54))
    if frac > 0:
        d.rounded_rectangle([x, y, x + max(h, w * min(frac, 1)), y + h], 10, fill=color)


def rate(bps):
    for unit, div in (("GB/s", 1e9), ("MB/s", 1e6), ("KB/s", 1e3)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}"
    return f"{bps:.0f} B/s"


def size(n):
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n:.0f} B"


def sparkline(d, x, y, w, h, values, color):
    top = max(max(values), 1.0)
    pts = [(x + i * w / (len(values) - 1), y + h - h * v / top) for i, v in enumerate(values)]
    d.polygon([(x, y + h)] + pts + [(x + w, y + h)], fill=tuple(int(c * 0.28 + 12) for c in color))
    d.line(pts, fill=color, width=3)


def tile(d, x, y, w, h, label, value, sub="", color=FG):
    d.rounded_rectangle([x, y, x + w, y + h], 14, fill=PANEL)
    d.text((x + 20, y + 16), label, fill=DIM, font_size=24)
    d.text((x + 20, y + 52), value, fill=color, font_size=54)
    if sub:
        d.text((x + 20, y + h - 18), sub, fill=DIM, font_size=22, anchor="ls")


def heat(t):
    return OK if t < 70 else WARN if t < 85 else BAD


# ---------- screens ----------
def screen_system():
    img, d = new_canvas()
    now = datetime.now()
    d.text((60, 40), now.strftime("%H:%M"), fill=FG, font_size=120)
    d.text((64, 175), now.strftime("%A, %B %d"), fill=DIM, font_size=36)
    g = gpu.data
    rows = [("CPU", psutil.cpu_percent(), "", BLUE)]
    if g:
        rows.append(("GPU", g["util"], f"{g['temp']:.0f}°C", GREEN))
    rows.append(("RAM", psutil.virtual_memory().percent, "", PURPLE))
    for i, (name, val, extra, col) in enumerate(rows):
        y = 250 + i * 115
        d.text((60, y), name, fill=DIM, font_size=36)
        if extra:
            d.text((W - 230, y + 4), extra, fill=DIM, font_size=36, anchor="ra")
        d.text((W - 60, y), f"{val:.0f}%", fill=FG, font_size=48, anchor="ra")
        bar(d, 60, y + 55, W - 120, 24, val / 100, col)
    t, label = (hw.cpu_temp, "CPU temp") if hw.cpu_temp is not None else (g["temp"] if g else None, "GPU temp")
    if t is not None:
        d.text((W - 60, 60), f"{t:.0f}°C", fill=FG, font_size=64, anchor="ra")
        d.text((W - 60, 130), label, fill=DIM, font_size=26, anchor="ra")
    return img


def screen_claude():
    img, d = new_canvas()
    d.text((60, 40), "Claude", fill=FG, font_size=64)
    days = usage.last_days(7)
    today = days[-1][1]
    d.text((W - 60, 40), fmt(today["tokens"]), fill=ACCENT, font_size=64, anchor="ra")
    d.text((W - 60, 112), f"tokens today · {today['msgs']} messages", fill=DIM, font_size=26, anchor="ra")
    top = max([v["tokens"] for _, v in days] + [1])
    x0, base, ch, bw, gap = 60, 440, 220, 100, 36
    for i, (date, v) in enumerate(days):
        x = x0 + i * (bw + gap)
        h = max(4, int(ch * v["tokens"] / top)) if v["tokens"] else 4
        d.rounded_rectangle([x, base - h, x + bw, base], 8, fill=ACCENT if i == 6 else (70, 78, 110))
        if v["tokens"]:
            d.text((x + bw / 2, base - h - 8), fmt(v["tokens"]), fill=FG, font_size=22, anchor="ms")
        d.text((x + bw / 2, base + 12), date.strftime("%a"), fill=DIM, font_size=24, anchor="mt")
    models = sorted(((m, t) for m, t in usage.models.items() if t), key=lambda x: -x[1])[:3]
    total = sum(t for _, t in models) or 1
    palette = [ACCENT, BLUE, PURPLE]
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


def screen_network():
    img, d = new_canvas()
    d.text((60, 40), "Network", fill=FG, font_size=64)
    for i, (label, now, hist, total, col) in enumerate([
        ("Download", net.down, net.down_hist, net.total_down, BLUE),
        ("Upload", net.up, net.up_hist, net.total_up, PURPLE),
    ]):
        y = 150 + i * 215
        d.rounded_rectangle([60, y, W - 60, y + 195], 16, fill=PANEL)
        d.text((90, y + 18), label, fill=DIM, font_size=28)
        d.text((90, y + 56), rate(now), fill=col, font_size=64)
        d.text((90, y + 150), f"{size(total)} since start", fill=DIM, font_size=24)
        sparkline(d, 470, y + 20, W - 60 - 470 - 30, 155, list(hist), col)
    return img


def screen_music():
    img, d = new_canvas()
    if not media.title:
        d.text((W / 2, H / 2 - 20), "Nothing playing", fill=DIM, font_size=56, anchor="mm")
        if not media.available:
            d.text((W / 2, H / 2 + 50), "Windows media controls unavailable", fill=DIM, font_size=26, anchor="mm")
        return img
    art = 380
    if media.art:
        a = media.art.copy()
        s = max(art / a.width, art / a.height)
        a = a.resize((int(a.width * s) + 1, int(a.height * s) + 1))
        l, t = (a.width - art) // 2, (a.height - art) // 2
        img.paste(a.crop((l, t, l + art, t + art)), (60, 110))
    else:
        d.rounded_rectangle([60, 110, 60 + art, 110 + art], 20, fill=PANEL)
        d.text((60 + art / 2, 110 + art / 2), "♪", fill=DIM, font_size=140, anchor="mm")
    x = 60 + art + 50
    mw = W - x - 50
    d.text((x, 150), "NOW PLAYING" if media.playing else "PAUSED", fill=ACCENT if media.playing else DIM, font_size=24)

    def clip(text, px, fs):  # truncate with an ellipsis to fit px
        while text and d.textlength(text, font_size=fs) > px:
            text = text[:-2].rstrip() + "…" if len(text) > 2 else ""
        return text
    d.text((x, 195), clip(media.title, mw, 54), fill=FG, font_size=54)
    d.text((x, 270), clip(media.artist, mw, 36), fill=DIM, font_size=36)
    d.text((x, 322), clip(media.album, mw, 28), fill=DIM, font_size=28)
    if media.duration > 0:
        bar(d, x, 440, mw, 14, media.position / media.duration, ACCENT)
        mm = lambda s: f"{int(s) // 60}:{int(s) % 60:02d}"
        d.text((x, 470), mm(media.position), fill=DIM, font_size=24)
        d.text((x + mw, 470), mm(media.duration), fill=DIM, font_size=24, anchor="ra")
    return img


def screen_hardware():
    img, d = new_canvas()
    d.text((60, 40), "Hardware", fill=FG, font_size=64)
    g = gpu.data
    tiles = []
    if hw.cpu_temp is not None:
        tiles.append(("CPU temp", f"{hw.cpu_temp:.0f}°C", f"{hw.cpu_power:.0f} W package" if hw.cpu_power else "", heat(hw.cpu_temp)))
    else:
        tiles.append(("CPU temp", "n/a", "needs sensor app", DIM))
    if g:
        tiles += [
            ("GPU temp", f"{g['temp']:.0f}°C", f"{g['clock']:.0f} MHz", heat(g["temp"])),
            ("GPU power", f"{g['power']:.0f} W", f"{g['mem_used'] / 1024:.1f} / {g['mem_total'] / 1024:.0f} GB VRAM", FG),
            ("GPU fan", f"{g['fan']:.0f}%", "", FG),
        ]
    for name, rpm in hw.fans[:6 - len(tiles)]:
        tiles.append((name[:22], f"{rpm:.0f}", "RPM", FG))
    for i, (label, value, sub, col) in enumerate(tiles[:6]):
        tile(d, 60 + (i % 3) * 313, 150 + (i // 3) * 190, 295, 170, label, value, sub, col)
    if not hw.available:
        d.text((60, H - 70), "Run LibreHardwareMonitor as administrator for CPU temperature and motherboard fan RPM.",
               fill=DIM, font_size=22)
        d.text((60, H - 40), "The AIO pump speed is not reported by the cooler's USB protocol.", fill=DIM, font_size=22)
    return img


def screen_gallery():
    img = gallery.frame()
    if img is None:
        img, d = new_canvas()
        d.text((W / 2, H / 2 - 20), "Gallery is empty", fill=DIM, font_size=52, anchor="mm")
        d.text((W / 2, H / 2 + 45), "Add pictures, GIFs or videos in the Gallery tab", fill=DIM, font_size=26, anchor="mm")
    return img


SCREENS = {
    "system": screen_system,
    "network": screen_network,
    "hardware": screen_hardware,
    "music": screen_music,
    "claude": screen_claude,
    "gallery": screen_gallery,
}
FAST = {"gallery"}  # screens worth refreshing quicker than 4 fps (GIFs, video)
