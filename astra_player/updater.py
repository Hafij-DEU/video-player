"""Check GitHub for a newer Astra Player release and install it on request.

Only the release list is read automatically (once a day, opt-out in
Preferences). The .deb is downloaded and installed only when the user presses
Update; apt then also installs any newly recommended extras.
"""

import json
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from gi.repository import GLib

REPO = "Hafij-DEU/video-player"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL = 24 * 3600


def parse_version(text):
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3]) if nums else ()


def newer(latest, current):
    return parse_version(latest) > parse_version(current)


def fetch_latest(timeout=15):
    """(version, deb_url, page_url) of the latest release, or None."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "astra-player"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    deb = next((a["browser_download_url"] for a in data.get("assets", [])
                if a.get("name", "").endswith("_all.deb")), None)
    return data.get("tag_name", ""), deb, data.get("html_url", "")


def check_async(current, callback):
    """callback(version, deb_url, page_url) on the main loop when a newer release exists."""
    def worker():
        try:
            info = fetch_latest()
        except (OSError, ValueError):
            return
        if info and info[1] and newer(info[0], current):
            GLib.idle_add(lambda: callback(*info) and False)

    threading.Thread(target=worker, daemon=True).start()


def due(last_check, now=None):
    now = time.time() if now is None else now
    return not last_check or now - last_check >= CHECK_INTERVAL or last_check > now


def install_async(deb_url, done):
    """Download the .deb and install it with pkexec apt; done(error_or_None) on the main loop."""
    def worker():
        try:
            tmp = Path(tempfile.mkdtemp(prefix="astra-update-")) / deb_url.rsplit("/", 1)[-1]
            req = urllib.request.Request(deb_url, headers={"User-Agent": "astra-player"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:
                fh.write(resp.read())
            tmp.chmod(0o644)
            tmp.parent.chmod(0o755)
            proc = subprocess.run(["pkexec", "apt-get", "install", "-y", str(tmp)],
                                  capture_output=True, text=True)
            err = None if proc.returncode == 0 else (
                proc.stderr.strip().splitlines() or [f"apt exited with {proc.returncode}"])[-1]
        except OSError as exc:
            err = str(exc)
        GLib.idle_add(lambda: done(err) and False)

    threading.Thread(target=worker, daemon=True).start()
