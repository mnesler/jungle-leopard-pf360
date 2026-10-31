"""LCD runner. Command line usage: python app.py [seconds] [--screen NAME]"""
import io
import sys
import threading
import time

from jl import Display
from screens import FAST, SCREENS

SCREEN_SECONDS = 10


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
        self.screens = list(screens or SCREENS)  # enabled screens, in order
        self.status = "starting"
        self.current = None  # name of the screen being shown
        self.last_image = None  # last frame sent to the LCD (for the GUI preview)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        self.thread.join(timeout=5)

    def _session(self):
        self.status = "connecting..."  # opening the port can take a while after a crash
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
                try:
                    frame = SCREENS[name]()
                except Exception as e:  # a broken screen must not stop the display
                    print("screen %s failed: %s" % (name, e), file=sys.stderr)
                    time.sleep(0.5)
                    continue
                self.last_image = frame
                d.send_jpeg(to_jpeg(frame))
                time.sleep(0.12 if name in FAST else 0.25)
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
    runner = Runner(pinned=args[args.index("--screen") + 1] if "--screen" in args else None)
    nums = [a for a in args if a.replace(".", "").isdigit()]
    runner.start()
    try:
        runner.stop.wait(float(nums[0]) if nums else None)
    except KeyboardInterrupt:
        pass
    runner.shutdown()


if __name__ == "__main__":
    main()
