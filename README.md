# Jungle Leopard Dashboard

A small Windows app that drives the LCD and fan lights of a Jungle Leopard
(TZMRIT-style) AIO cooler without the vendor's Electron app.

- **LCD:** rotating screens - system stats, Claude service status, Claude Code usage
- **Fan lights:** static / breathing / rainbow / colour cycle, via OpenRGB
- **GUI:** live preview, pause, screen picker, backlight, start with Windows

Tested on: `33C3:7792` panel (1024x600, firmware 3.6), Windows 10, Gigabyte X570
AORUS Elite WiFi with the fans on the `D_LED2` header.

## Run

```
pip install -r requirements.txt
pythonw gui.pyw          # or: python gui.pyw
```

Quit the vendor's *Jungle Leopard Display* app first - only one program can hold
the cooler's serial port. For the fan lights, tick **Control fan lights**; if
OpenRGB is missing the panel offers **Install OpenRGB** (pinned release, SHA-256
checked, extracted to `%APPDATA%\JLDash\openrgb`).

Command line without the GUI: `python app.py [seconds] [--screen system|claude|usage]`.

## Files

| File | Purpose |
|---|---|
| `jl.py` | Device protocol (serial framing, info, backlight, JPEG frames) |
| `app.py` | Screens, data pollers (GPU, Claude status) and the `Runner` loop |
| `usage.py` | Local Claude Code token totals from `~/.claude/projects/**/*.jsonl` |
| `lights.py` | Effects engine + headless OpenRGB server management |
| `gui.pyw` | Tk control window |
| `settings.py` | JSON settings in `%APPDATA%\JLDash\settings.json` |
| `probe.py`, `test_image.py` | Device probing helpers |

## Protocol notes

USB CDC serial, found by VID `0x33C3`. Baud rate is irrelevant; DTR/RTS asserted.

- **Command frame:** `55 AA | len u16 LE | cmd | payload | checksum u16 LE`
  (`len` = payload + 7, checksum = sum of all prior bytes & 0xFFFF).
  Replies use the same framing with a JSON payload.
- **Image frame:** `len u32 LE | JPEG | checksum u16 LE` (checksum covers the length
  bytes). No `55 AA` header, no command byte.
- **Keys used:** `0x06` device info, `0x03` backlight (0-100), `0x11` live mode /
  keep-alive (send about every 1.5 s).
- **Session start:** send `FF D9 FF D9`, pause, then `00 00 00 00`. Resend frames
  about every 250 ms so a still image never shows half drawn.
- **Not implemented on purpose:** OTA flash (`0x0C`) and serial-number write
  (`0x23`) - a bad write could leave the panel unusable.

The fan lights are *not* on the cooler: this unit has no lighting controller of its
own, so the fans plug into a motherboard addressable-RGB header.

## Privacy

The usage screen reads local Claude Code logs only. Nothing is sent anywhere and no
credentials are used. The Claude status screen polls the public
`status.claude.com` feed.

## Credits

Protocol details cross-checked against
[senesees/Jungle-Leopard-Display-TZMRIT-PF360-LCD](https://github.com/senesees/Jungle-Leopard-Display-TZMRIT-PF360-LCD)
and the vendor app's own (unminified) source. OpenRGB is GPL-2.0 and is downloaded,
not bundled.
