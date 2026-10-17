"""YouTube search through yt-dlp: no API key, no account.

The parsing helpers have no GTK dependency so they can be unit tested on
canned yt-dlp output. The dialog lives in search_dialog.py.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

SEARCH_COUNT = 25
# "ytsearch:lofi", "ytsearch10:lofi" (yt-dlp's own search syntax).
SEARCH_PREFIX = re.compile(r"^\s*ytsearch(?:\d+|all)?:\s*(.*)$", re.I | re.S)


class Result:
    __slots__ = ("id", "url", "title", "channel", "duration", "views", "thumbnail", "live")

    def __init__(self, id, url, title, channel="", duration=None, views=None,
                 thumbnail=None, live=False):
        self.id = id
        self.url = url
        self.title = title
        self.channel = channel
        self.duration = duration
        self.views = views
        self.thumbnail = thumbnail
        self.live = live

    def __repr__(self):
        return f"Result({self.id!r}, {self.title!r})"


def have_ytdlp():
    return shutil.which("yt-dlp") is not None


# ---------------------------------------------------------------- sign-in
#
# When YouTube rate-limits a connection it answers "Sign in to confirm you're
# not a bot" (often after HTTP 429). yt-dlp can then reuse the YouTube login
# of a local browser (--cookies-from-browser) or a cookies.txt export. This is
# opt-in, set in Preferences, and the cookies never leave this computer.

# Set from settings["youtube_cookies"]: "" (off), a yt-dlp browser spec such as
# "brave" or "chrome:/home/u/.config/google-chrome-beta", or "file:/path/cookies.txt".
cookie_source = ""

_HOME = Path.home()
_BROWSERS = [
    ("Brave", "brave", [".config/BraveSoftware/Brave-Browser"]),
    ("Google Chrome", "chrome", [".config/google-chrome"]),
    ("Google Chrome Beta", "chrome", [".config/google-chrome-beta"]),
    ("Google Chrome Dev", "chrome", [".config/google-chrome-unstable"]),
    ("Chromium", "chromium", [".config/chromium", "snap/chromium/common/chromium"]),
    ("Microsoft Edge", "edge", [".config/microsoft-edge"]),
    ("Microsoft Edge Beta", "edge", [".config/microsoft-edge-beta"]),
    ("Microsoft Edge Dev", "edge", [".config/microsoft-edge-dev"]),
    ("Vivaldi", "vivaldi", [".config/vivaldi"]),
    ("Opera", "opera", [".config/opera"]),
    ("Firefox", "firefox", [".mozilla/firefox", "snap/firefox/common/.mozilla/firefox",
                            ".var/app/org.mozilla.firefox/.mozilla/firefox"]),
]
# Folders yt-dlp finds on its own; anything else is passed as an explicit profile path.
_DEFAULT_DIRS = {".config/BraveSoftware/Brave-Browser", ".config/google-chrome", ".config/chromium",
                 ".config/microsoft-edge", ".config/vivaldi", ".config/opera", ".mozilla/firefox"}


def detect_browsers(home=None):
    """Return [(label, spec)] for browsers with a profile on this computer."""
    home = Path(home) if home else _HOME
    found = []
    for label, name, dirs in _BROWSERS:
        for rel in dirs:
            if (home / rel).is_dir():
                spec = name if rel in _DEFAULT_DIRS else f"{name}:{home / rel}"
                found.append((label, spec))
                break
    return found


def auth_args(source=None):
    """yt-dlp arguments for the chosen sign-in source (empty when off)."""
    source = cookie_source if source is None else source
    if not source:
        return []
    if source.startswith("file:"):
        return ["--cookies", source[5:]]
    return ["--cookies-from-browser", source]


def is_bot_block(message):
    text = (message or "").lower()
    return "not a bot" in text or "429" in text or "sign in to confirm" in text


def search_query(text):
    """Return the query of a typed "ytsearch:…" string, or None for anything else."""
    m = SEARCH_PREFIX.match(text or "")
    return m.group(1).strip() if m else None


def smallest_thumbnail(thumbs):
    """Pick the smallest thumbnail URL; entries without a size count as large."""
    best, best_area = None, None
    for t in thumbs or []:
        url = t.get("url") if isinstance(t, dict) else None
        if not url:
            continue
        w, h = t.get("width"), t.get("height")
        area = w * h if isinstance(w, int) and isinstance(h, int) else 10 ** 9
        if best_area is None or area < best_area:
            best, best_area = url, area
    return best


def parse_entry(data):
    """Turn one yt-dlp --flat-playlist JSON object into a Result, or None."""
    if not isinstance(data, dict):
        return None
    vid = data.get("id")
    ie = data.get("ie_key") or data.get("extractor_key") or "Youtube"
    if not vid or ie != "Youtube":  # channels and playlists use YoutubeTab
        return None
    url = data.get("url") or data.get("webpage_url") or ""
    if not url.startswith(("http://", "https://")):
        url = f"https://www.youtube.com/watch?v={vid}"
    thumb = smallest_thumbnail(data.get("thumbnails")) or data.get("thumbnail")
    duration = data.get("duration")
    views = data.get("view_count")
    live_status = data.get("live_status") or ""
    return Result(
        id=vid, url=url, title=data.get("title") or url,
        channel=data.get("channel") or data.get("uploader") or "",
        duration=duration if isinstance(duration, (int, float)) and duration > 0 else None,
        views=views if isinstance(views, int) and views >= 0 else None,
        thumbnail=thumb,
        live=live_status in ("is_live", "is_upcoming"))


def parse_search_output(text):
    """Parse the JSON lines printed by ``yt-dlp --flat-playlist --dump-json``."""
    results, seen = [], set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            res = parse_entry(json.loads(line))
        except ValueError:
            continue
        if res is not None and res.id not in seen:
            seen.add(res.id)
            results.append(res)
    return results


def search_command(query, count=SEARCH_COUNT):
    return ["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", *auth_args(),
            f"ytsearch{count}:{query}"]


def search(query, count=SEARCH_COUNT, on_process=None):
    """Run a YouTube search and return a list of Results.

    ``on_process`` receives the Popen object so the caller can kill it.
    Raises RuntimeError when yt-dlp is missing or fails.
    """
    if not have_ytdlp():
        raise RuntimeError("yt-dlp is not installed")
    proc = subprocess.Popen(search_command(query, count), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if on_process:
        on_process(proc)
    try:
        out, err = proc.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError("YouTube search timed out")
    results = parse_search_output(out)
    if proc.returncode != 0 and not results:
        if proc.returncode < 0:  # killed by the caller
            return []
        raise RuntimeError((err.strip().splitlines() or ["yt-dlp failed"])[-1])
    return results


def fmt_duration(seconds):
    if not seconds:
        return ""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_views(n):
    if n is None:
        return ""
    if n == 1:
        return "1 view"
    for div, unit in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            v = n / div
            num = f"{v:.1f}".rstrip("0").rstrip(".") if v < 10 else f"{v:.0f}"
            return f"{num}{unit} views"
    return f"{n} views"


def describe(result):
    """One-line subtitle for a result row: channel · duration · views."""
    parts = [result.channel, "LIVE" if result.live else fmt_duration(result.duration),
             fmt_views(result.views)]
    return "  ·  ".join(p for p in parts if p)
