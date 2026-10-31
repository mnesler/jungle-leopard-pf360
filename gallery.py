"""Gallery: a playlist of pictures, GIFs and videos shown full-screen on the LCD.

Pictures are shown for a fixed time. GIFs and videos are streamed through a bundled
ffmpeg (imageio-ffmpeg) at 12 fps, scaled to fill the 1024x600 panel, and play to
the end (up to a cap). The gallery only advances while its screen is actually shown.
"""
import atexit
import os
import subprocess
import threading
import time

from PIL import Image

W, H, FPS = 1024, 600, 12
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
VIDEO_EXT = {".gif", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
FILETYPES = [
    ("Pictures, GIFs and videos", " ".join("*" + e for e in sorted(IMAGE_EXT | VIDEO_EXT))),
    ("All files", "*.*"),
]
CREATE_NO_WINDOW = 0x08000000


def kind(path):
    ext = os.path.splitext(path)[1].lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else None


def _ffmpeg():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def cover(im):
    s = max(W / im.width, H / im.height)
    im = im.resize((max(W, round(im.width * s)), max(H, round(im.height * s))), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((l, t, l + W, t + H)).convert("RGB")


class Gallery:
    def __init__(self):
        self.items = []
        self.image_seconds = 8
        self.max_clip_seconds = 90
        self._lock = threading.Lock()
        self._reset_state()
        atexit.register(self.stop_stream)

    def _reset_state(self):
        self.idx = 0
        self.elapsed = 0.0  # seconds of the current item already shown
        self.last_call = 0.0
        self._loaded = None  # (idx, path) currently prepared
        self._image = None
        self._frame = None
        self._proc = None
        self._eof = False
        self._got_frames = False
        self.current = None  # path of the item being shown

    # -- playlist --
    def set_items(self, items):
        with self._lock:
            self.stop_stream()
            self.items = [p for p in items if kind(p)]
            self._reset_state()

    # -- streaming --
    def stop_stream(self):
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def _start_stream(self, path, start):
        self.stop_stream()
        self._eof = self._got_frames = False
        cmd = [_ffmpeg(), "-loglevel", "error", "-re"]
        if start > 0.5:
            cmd += ["-ss", f"{start:.2f}"]
        cmd += ["-i", path, "-an", "-vf",
                f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        self._proc = proc
        size = W * H * 3

        def reader():
            try:
                while proc is self._proc:
                    buf = proc.stdout.read(size)
                    if len(buf) < size:
                        break
                    self._frame = Image.frombytes("RGB", (W, H), buf)
                    self._got_frames = True
            except Exception:
                pass
            if proc is self._proc:
                self._eof = True

        threading.Thread(target=reader, daemon=True).start()

    # -- main entry: returns a 1024x600 image, or None when the playlist is empty --
    def frame(self):
        with self._lock:
            if not self.items:
                return None
            now = time.time()
            gap = now - self.last_call if self.last_call else 0.0
            self.last_call = now
            if gap > 2.0:  # screen was away: stop decoding, resume this item where it left off
                self.stop_stream()
                self._loaded = None
                gap = 0.0
            self.elapsed += gap

            self.idx %= len(self.items)
            path = self.items[self.idx]
            if self._loaded != (self.idx, path):
                self._prepare(path)
            k = kind(path)
            done = False
            if k == "image":
                done = self.elapsed >= self.image_seconds
            else:
                done = self._eof or self.elapsed >= self.max_clip_seconds
                if self._eof and not self._got_frames:
                    done = True  # unreadable file: skip it
            img = self._image if k == "image" else self._frame
            if done:
                self._advance()
            return img if img is not None else Image.new("RGB", (W, H), (12, 14, 26))

    def _prepare(self, path):
        self.current = path
        self._loaded = (self.idx, path)
        self._frame = self._image = None
        if kind(path) == "image":
            try:
                with Image.open(path) as im:
                    self._image = cover(im.convert("RGB"))
            except Exception:
                self.elapsed = self.image_seconds  # unreadable: skip quickly
        else:
            try:
                self._start_stream(path, self.elapsed)
            except Exception:
                self._eof, self._got_frames = True, False

    def _advance(self):
        self.stop_stream()
        self.elapsed = 0.0
        self._loaded = None
        self.idx = (self.idx + 1) % len(self.items)


gallery = Gallery()
