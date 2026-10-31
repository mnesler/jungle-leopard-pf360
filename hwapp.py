"""Optional LibreHardwareMonitor integration (CPU temperature, fan RPM).

The portable app is downloaded from the project's GitHub release, checked against its
published SHA-256, and extracted to %APPDATA%\\JLDash\\lhm. It must run as administrator
(it loads a kernel driver for the sensors), so launching goes through a UAC prompt that the
user approves. Once running it serves sensors as JSON on http://localhost:8085/data.json (its built-in
web server, enabled through the config written here), which sensors.HwSensors reads.
"""
import hashlib
import io
import os
import subprocess
import zipfile
from pathlib import Path

import requests

DIR = Path(os.environ.get("APPDATA", Path.home())) / "JLDash" / "lhm"
EXE = DIR / "LibreHardwareMonitor.exe"
URL = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip"
SHA256 = "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"
# start hidden in the tray instead of opening its big window
CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
    <add key="runWebServerMenuItem" value="true" />
    <add key="listenerPort" value="8085" />
  </appSettings>
</configuration>
"""


def installed():
    return EXE.exists()


def running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LibreHardwareMonitor.exe", "/NH"],
                         capture_output=True, text=True, creationflags=0x08000000).stdout
    return "LibreHardwareMonitor.exe" in out


def install():
    """Download, verify and extract. Raises RuntimeError on any problem; installs nothing on failure."""
    data = requests.get(URL, timeout=120).content
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError("LibreHardwareMonitor download failed its hash check; nothing was installed")
    DIR.mkdir(parents=True, exist_ok=True)
    root = DIR.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = (DIR / info.filename).resolve()
            if root not in target.parents:
                raise RuntimeError("unsafe path in archive: %s" % info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
    if not EXE.exists():
        raise RuntimeError("LibreHardwareMonitor.exe not found in the download")
    write_config()


def write_config():
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "LibreHardwareMonitor.config").write_text(CONFIG, encoding="utf8")


def restart_elevated():
    """Stop a running instance and start it again with the current config (one UAC prompt)."""
    if not installed():
        raise RuntimeError("not installed")
    write_config()
    cmd = (f"Stop-Process -Name LibreHardwareMonitor -Force -ErrorAction SilentlyContinue; Start-Sleep 2; "
           f"Start-Process -FilePath '{EXE}' -WorkingDirectory '{DIR}'")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
         "Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList '-NoProfile','-Command','%s'" % cmd.replace("'", "''")],
        creationflags=0x08000000,
    )


def launch_elevated():
    """Start the app as administrator. Windows shows a UAC prompt; declining is harmless."""
    if not installed():
        raise RuntimeError("not installed")
    write_config()  # keep the web-server setting in place
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
         f"Start-Process -FilePath '{EXE}' -WorkingDirectory '{DIR}' -Verb RunAs"],
        creationflags=0x08000000,
    )
