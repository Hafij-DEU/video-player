"""Persistent settings and per-file resume state, stored as JSON in XDG config."""

import json
import os
import shutil
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
CONFIG_DIR = CONFIG_HOME / "astra-player"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
RESUME_FILE = CONFIG_DIR / "resume.json"

DEFAULTS = {
    "volume": 1.0,
    "muted": False,
    "last_dir": str(Path.home()),
    "recent": [],
    "resume_playback": True,
    "auto_load_subtitles": True,
    "auto_add_folder": True,
    "subtitle_font": "Sans Bold 24",
    "screenshot_dir": str(Path.home() / "Pictures" / "Astra Player"),
    "seek_short": 5,
    "seek_long": 30,
    "hardware_decoding": True,
    "loop_mode": "playlist",  # none | one | playlist
    "shuffle": False,
    "eq_enabled": False,
    "eq_bands": [0.0] * 10,
    "show_playlist": False,
    "pip_hint_shown": False,
    "whisper_model": "base",  # tiny | base | small
    "whisper_language": "auto",
    "whisper_translate": False,
    "whisper_gpu": False,
    "youtube_cookies": "",  # "" | browser spec | "file:/path/cookies.txt"
}

# The app was called Kiln Player before 1.2.0.
LEGACY_NAME = "kiln-player"


def migrate_legacy():
    """Carry settings, resume points and Whisper models over from Kiln Player, once."""
    old_cfg = CONFIG_HOME / LEGACY_NAME
    if old_cfg.is_dir() and not CONFIG_DIR.exists():
        try:
            shutil.copytree(old_cfg, CONFIG_DIR)
        except OSError:
            pass
    old_data, new_data = DATA_HOME / LEGACY_NAME, DATA_HOME / "astra-player"
    if old_data.is_dir() and not new_data.exists():
        try:
            old_data.rename(new_data)  # models are large; move instead of copying
        except OSError:
            pass


MAX_RECENT = 20
MAX_RESUME = 300


def _load(path, fallback):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return fallback


def _save(path, data):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        tmp.replace(path)
    except OSError:
        pass


class Settings:
    def __init__(self):
        migrate_legacy()
        self.data = dict(DEFAULTS)
        stored = _load(SETTINGS_FILE, {})
        if isinstance(stored, dict):
            self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        resume = _load(RESUME_FILE, {})
        self.resume = resume if isinstance(resume, dict) else {}

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self):
        _save(SETTINGS_FILE, self.data)
        _save(RESUME_FILE, self.resume)

    def add_recent(self, uri):
        recent = [u for u in self.data["recent"] if u != uri]
        recent.insert(0, uri)
        self.data["recent"] = recent[:MAX_RECENT]

    def get_resume(self, uri):
        return self.resume.get(uri)

    def set_resume(self, uri, seconds):
        self.resume.pop(uri, None)
        if seconds is not None:
            self.resume[uri] = round(seconds, 1)
        while len(self.resume) > MAX_RESUME:
            self.resume.pop(next(iter(self.resume)))
