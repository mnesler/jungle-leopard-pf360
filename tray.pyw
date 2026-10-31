"""Tray launcher for the Jungle Leopard LCD dashboard (no console window)."""
import os
import subprocess
import sys

import pystray
from PIL import Image, ImageDraw

import app

STARTUP_LNK = os.path.join(
    os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "JungleLeopardDash.vbs"
)
HERE = os.path.dirname(os.path.abspath(__file__))


def icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 10, 60, 54], 8, fill=(22, 26, 44), outline=app.ACCENT, width=4)
    d.rectangle([14, 38, 22, 46], fill=app.ACCENT)
    d.rectangle([28, 28, 36, 46], fill=app.ACCENT)
    d.rectangle([42, 20, 50, 46], fill=app.ACCENT)
    return img


def autostart_on():
    return os.path.exists(STARTUP_LNK)


def toggle_autostart(icon, item):
    if autostart_on():
        os.remove(STARTUP_LNK)
    else:
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        with open(STARTUP_LNK, "w") as f:
            f.write('CreateObject("WScript.Shell").Run """%s"" ""%s""", 0, False\n' % (pyw, os.path.join(HERE, "tray.pyw")))


def main():
    runner = app.Runner()
    runner.start()

    def pin(name):
        def _set(icon, item):
            runner.pinned = name
        return _set

    def pinned_is(name):
        return lambda item: runner.pinned == name

    screens = [pystray.MenuItem("Rotate all", pin(None), checked=pinned_is(None), radio=True)]
    screens += [
        pystray.MenuItem(n.title(), pin(n), checked=pinned_is(n), radio=True) for n in app.SCREENS
    ]

    def toggle_pause(icon, item):
        runner.paused = not runner.paused

    def quit_(icon, item):
        runner.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: "Status: " + runner.status, None, enabled=False),
        pystray.MenuItem("Pause", toggle_pause, checked=lambda item: runner.paused),
        pystray.MenuItem("Screen", pystray.Menu(*screens)),
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda item: autostart_on()),
        pystray.MenuItem("Quit", quit_),
    )
    pystray.Icon("jl-dash", icon_image(), "Jungle Leopard Dashboard", menu).run()


if __name__ == "__main__":
    main()
