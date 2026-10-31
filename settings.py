"""Persistent user settings (JSON in %APPDATA%\JLDash)."""
import copy
import json
import os
from pathlib import Path

PATH = Path(os.environ.get("APPDATA", Path.home())) / "JLDash" / "settings.json"
DEFAULTS = {
    "brightness": 95,
    "rotate_seconds": 10,
    "screens": ["system", "claude"],  # enabled screens
    "order": None,  # display order of all screens (None = default)
    "known": None,  # screens the user has already seen (new ones start enabled)
    "media_path": "",  # legacy single picture (migrated into the gallery)
    "gallery": {"items": [], "image_seconds": 8},
    "pinned": None,
    "lights": {},  # overrides for lights.DEFAULTS
}


def load():
    try:
        return {**copy.deepcopy(DEFAULTS), **json.loads(PATH.read_text(encoding="utf8"))}
    except Exception:
        return copy.deepcopy(DEFAULTS)


def save(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf8")
