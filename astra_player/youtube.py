"""YouTube search through yt-dlp: no API key, no account.

The parsing helpers have no GTK dependency so they can be unit tested on
canned yt-dlp output. The dialog lives in search_dialog.py.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
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
    return ytdlp_path("") is not None


# ---------------------------------------------------------------- yt-dlp
#
# YouTube changes often and an old yt-dlp is a common reason for failures, so
# Astra Player can keep its own copy: the official zipapp from yt-dlp's GitHub
# releases, checked against the release's SHA2-256SUMS. It is only downloaded
# after the user agrees (Preferences › YouTube, or the sign-in dialog), and
# then updated weekly in the background while "Keep yt-dlp up to date" is on.

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "astra-player"
MANAGED_DIR = DATA_DIR / "bin"
RELEASES = "https://github.com/yt-dlp/yt-dlp/releases"
MANAGED_SIZE = 3_100_000  # shown until the real size is known
UPDATE_INTERVAL = 7 * 86400
_UA = {"User-Agent": "astra-player"}
_TAG = re.compile(r"^\d{4}\.\d{2}\.\d{2}(?:\.\d+)?$")

# Set from settings["ytdlp_managed"]: use (and update) the managed copy.
managed_enabled = False

# Chromium-based browsers encrypt cookies with a key kept in the desktop
# keyring; yt-dlp reads it through the Python "secretstorage" module.
KEYRING_BROWSERS = {"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"}
SECRETSTORAGE_HINT = ("Reading the sign-in of Chrome-based browsers needs the Python "
                      "secretstorage module: sudo apt install python3-secretstorage")
_secretstorage = {}


def managed_path():
    return MANAGED_DIR / "yt-dlp"


def managed_version():
    try:
        tag = (MANAGED_DIR / "yt-dlp.version").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return tag if managed_path().is_file() else None


def interpreter(program):
    """The Python a yt-dlp script runs with, or None for anything that isn't a Python script."""
    try:
        with open(program, "rb") as fh:
            first = fh.readline(256)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    words = first[2:].decode("utf-8", "replace").split()
    if words and os.path.basename(words[0]) == "env":
        words = [w for w in words[1:] if not w.startswith("-")]
        prog = shutil.which(words[0]) if words else None
    else:
        prog = words[0] if words and os.path.isfile(words[0]) else None
    return prog if prog and "python" in os.path.basename(prog) else None


def has_secretstorage(program):
    """True when this yt-dlp can import secretstorage (always true for non-Python builds)."""
    py = interpreter(program)
    if py is None:
        return True
    if py not in _secretstorage:
        try:
            ok = subprocess.run([py, "-c", "import secretstorage"], capture_output=True,
                                timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        _secretstorage[py] = ok
    return _secretstorage[py]


def needs_keyring(source):
    """True when this sign-in source is a Chromium browser using the desktop keyring."""
    if not source or source.startswith("file:"):
        return False
    head = source.split(":", 1)[0].lower()
    name, _, keyring = head.partition("+")
    return name in KEYRING_BROWSERS and keyring in ("", "gnomekeyring")


def _runnable(program):
    if not (os.path.isfile(program) and os.access(program, os.X_OK)):
        return False
    try:
        with open(program, "rb") as fh:
            first = fh.readline(256)
    except OSError:
        return False
    if first.startswith(b"#!") and b"python" in first:
        return interpreter(program) is not None  # the zipapp needs python3 on PATH
    return True


def _on_path(name):
    found, seen = [], set()
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        prog = os.path.join(folder or ".", name)
        if os.path.isfile(prog) and os.access(prog, os.X_OK):
            real = os.path.realpath(prog)
            if real not in seen:
                seen.add(real)
                found.append(prog)
    return found


def ytdlp_candidates():
    """Every usable yt-dlp, best first: the managed copy (when enabled), then PATH order."""
    found = []
    managed = str(managed_path())
    if managed_enabled and _runnable(managed):
        found.append(managed)
    return found + _on_path("yt-dlp")


def ytdlp_path(source=None):
    """The yt-dlp to run for this sign-in source, or None when there is none.

    The managed copy wins, unless the source needs secretstorage and only a
    system copy has it.
    """
    source = cookie_source if source is None else source
    found = ytdlp_candidates()
    if not found:
        return None
    if needs_keyring(source):
        for prog in found:
            if has_secretstorage(prog):
                return prog
    return found[0]


def keyring_missing(source=None):
    """True when the source needs secretstorage and no yt-dlp here can load it."""
    source = cookie_source if source is None else source
    return needs_keyring(source) and not any(has_secretstorage(p) for p in ytdlp_candidates())


def update_due(last_check, now=None, interval=UPDATE_INTERVAL):
    """Weekly check; a last check in the future (clock changed) also counts as due."""
    now = time.time() if now is None else now
    return not last_check or now - last_check >= interval or last_check - now > 86400


def _open(url, method="GET", timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, method=method, headers=_UA),
                                  timeout=timeout)


def latest_version():
    """The tag of yt-dlp's latest release, read from the /latest redirect."""
    with _open(f"{RELEASES}/latest", "HEAD", 20) as resp:
        tag = resp.geturl().rstrip("/").rsplit("/", 1)[-1]
    if not _TAG.match(tag):
        raise RuntimeError(f"Unexpected yt-dlp release: {tag}")
    return tag


def remote_size(tag=None):
    """Download size of the zipapp in bytes, or None."""
    try:
        with _open(f"{RELEASES}/download/{tag or latest_version()}/yt-dlp", "HEAD", 15) as resp:
            return int(resp.headers.get("Content-Length") or 0) or None
    except (OSError, ValueError, RuntimeError):
        return None


def parse_sums(text):
    sums = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def download_managed(tag=None, progress=None, cancel=None):
    """Fetch the yt-dlp zipapp into MANAGED_DIR and verify it. Only call after the user agreed."""
    tag = tag or latest_version()
    with _open(f"{RELEASES}/download/{tag}/SHA2-256SUMS") as resp:
        want = parse_sums(resp.read(200_000).decode("utf-8", "replace")).get("yt-dlp")
    if not want:
        raise RuntimeError("The yt-dlp release has no checksum for yt-dlp")
    MANAGED_DIR.mkdir(parents=True, exist_ok=True)
    dest = managed_path()
    part = dest.with_name("yt-dlp.part")
    digest = hashlib.sha256()
    try:
        with _open(f"{RELEASES}/download/{tag}/yt-dlp") as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0) or MANAGED_SIZE
            done = 0
            while chunk := resp.read(1 << 16):
                if cancel is not None and cancel.is_set():
                    raise RuntimeError("cancelled")
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(min(done / total, 1.0))
        if digest.hexdigest() != want:
            raise RuntimeError("Downloaded yt-dlp is damaged (checksum mismatch)")
        part.chmod(0o755)
        part.replace(dest)
        (MANAGED_DIR / "yt-dlp.version").write_text(tag + "\n", encoding="utf-8")
    finally:
        part.unlink(missing_ok=True)
    return tag


def update_managed(progress=None, cancel=None):
    """Download the latest release unless it is already here. Returns (tag, updated)."""
    tag = latest_version()
    if managed_version() == tag:
        return tag, False
    return download_managed(tag, progress, cancel), True


def ytdlp_version(program):
    try:
        out = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


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
    return ("not a bot" in text or "sign in to confirm" in text
            or re.search(r"\b429\b", text) is not None)


_COOKIE_ERROR = re.compile(r"cookies? database|keyring|secretstorage|decrypt|failed to load cookies"
                           r"|unsupported browser|could not copy", re.I)


def is_cookie_error(message):
    """True when yt-dlp could not read the chosen browser's cookies."""
    return bool(_COOKIE_ERROR.search(message or ""))


def browser_label(spec, browsers=None):
    for label, s in (detect_browsers() if browsers is None else browsers):
        if s == spec:
            return label
    if spec.startswith("file:"):
        return spec[5:].rsplit("/", 1)[-1]
    return spec.split(":", 1)[0].split("+", 1)[0].capitalize()


def fallback_order(first, browsers, keyring_ok=True):
    """Browser specs to try: the chosen one, then every other detected browser.

    When no yt-dlp here can read the desktop keyring, Chromium-based browsers
    other than the chosen one go last; they can only work with KWallet.
    """
    order = [first] if first else []
    rest = [spec for _label, spec in browsers if spec not in order]
    if not keyring_ok:
        rest.sort(key=needs_keyring)  # stable: keeps detection order within each group
    for spec in rest:
        if spec not in order:
            order.append(spec)
    return order


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
    return [ytdlp_path() or "yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", *auth_args(),
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
