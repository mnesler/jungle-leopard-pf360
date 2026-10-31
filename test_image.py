import io
import time

from PIL import Image, ImageDraw

from jl import Display

W, H = 1024, 600


def make(t):
    img = Image.new("RGB", (W, H), (10, 12, 30))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 8):
        c = int(255 * x / W)
        d.rectangle([x, 0, x + 8, 60], fill=(c, 80, 255 - c))
    d.text((60, 200), "HELLO FROM PYTHON", fill=(255, 255, 255), font_size=72)
    d.text((60, 300), f"t = {t:.1f}s", fill=(0, 255, 160), font_size=48)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80, subsampling=2)
    return buf.getvalue()


d = Display()
d.prime()
print("info:", d.info()[0] is not None)
d.command(0x11, read=False)
start = time.time()
last_ka = 0
while time.time() - start < 6:
    now = time.time()
    if now - last_ka > 1.0:
        d.keepalive()
        last_ka = now
    jpeg = make(now - start)
    d.send_jpeg(jpeg)
    time.sleep(0.25)
print("frame size:", len(jpeg))
d.close()
