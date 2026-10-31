"""Persistent user settings (JSON in %APPDATA%\JLDash)."""
import json
import os
from pathlib import Path

PATH = Path(os.environ.get("APPDATA", Path.home())) / "JLDash" / "settings.json"
DEFAULTS = {
    "brightness": 95,
    "rotate_seconds": 10,
    "screens": ["system", "claude", "usage"],  # enabled, in order
    "pinned": None,
    "lights": {},  # overrides for lights.DEFAULTS
}


def load():
    try:
        return {**DEFAULTS, **json.loads(PATH.read_text(encoding="utf8"))}
    except Exception:
        return dict(DEFAULTS)


def save(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf8")
