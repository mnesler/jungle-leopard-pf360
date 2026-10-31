"""Jungle Leopard Display protocol (USB CDC serial, VID 33C3)."""
import json
import struct
import time

import serial
import serial.tools.list_ports

VID = 0x33C3


def find_port():
    for p in serial.tools.list_ports.comports():
        if p.vid == VID:
            return p.device
    raise RuntimeError("Jungle Leopard device (VID 33C3) not found")


def cmd_frame(cmd, payload=b""):
    payload = bytes(payload)
    body = b"\x55\xaa" + struct.pack("<H", len(payload) + 7) + bytes([cmd]) + payload
    return body + struct.pack("<H", sum(body) & 0xFFFF)


def image_frame(jpeg):
    head = struct.pack("<I", len(jpeg)) + jpeg
    return head + struct.pack("<H", sum(head) & 0xFFFF)


class Display:
    def __init__(self, port=None):
        self.ser = serial.Serial(port or find_port(), 115200, timeout=1.0, write_timeout=3.0)
        self.ser.dtr = True
        self.ser.rts = True

    def close(self):
        self.ser.close()

    def prime(self):
        self.ser.write(b"\xff\xd9\xff\xd9")
        time.sleep(0.5)
        self.ser.write(b"\x00\x00\x00\x00")
        time.sleep(0.1)

    def command(self, cmd, payload=b"", read=True):
        self.ser.reset_input_buffer()
        self.ser.write(cmd_frame(cmd, payload))
        if not read:
            return None
        time.sleep(0.2)
        return self.ser.read(self.ser.in_waiting or 1)

    def info(self):
        raw = self.command(0x06)
        # reply: 55 AA len(2) key | payload | checksum(2)
        try:
            return json.loads(raw[5:-2].decode("utf8")), raw
        except Exception:
            return None, raw

    def set_backlight(self, pct):
        return self.command(0x03, [max(0, min(100, int(pct)))])

    def keepalive(self):
        self.ser.write(cmd_frame(0x11))

    def send_jpeg(self, jpeg):
        self.ser.write(image_frame(jpeg))
