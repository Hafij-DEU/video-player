"""Playlist model plus helpers for media discovery and playlist files."""

import random
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from gi.repository import Gio

VIDEO_EXT = {
    "3g2", "3gp", "amv", "asf", "avi", "divx", "dv", "f4v", "flv", "m2t", "m2ts", "m2v", "m4v",
    "mkv", "mov", "mp4", "mpe", "mpeg", "mpg", "mts", "mxf", "nut", "ogm", "ogv", "qt", "rm",
    "rmvb", "tp", "trp", "ts", "vob", "webm", "wmv", "y4m", "av1", "h264", "h265", "hevc", "264", "265",
}
AUDIO_EXT = {
    "aac", "ac3", "aif", "aiff", "alac", "amr", "ape", "au", "caf", "dsf", "dts", "eac3", "flac",
    "m4a", "m4b", "mka", "mp1", "mp2", "mp3", "mpc", "oga", "ogg", "opus", "ra", "spx", "tak",
    "tta", "voc", "wav", "weba", "wma", "wv",
}
PLAYLIST_EXT = {"m3u", "m3u8", "pls"}
SUBTITLE_EXT = ["srt", "ass", "ssa", "vtt", "sub", "smi", "sami", "txt"]
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT


def ext_of(path):
    return Path(path).suffix.lower().lstrip(".")


def uri_to_path(uri):
    if uri.startswith("file://"):
        return Path(unquote(urlparse(uri).path))
    return None


def path_to_uri(path):
    return Gio.File.new_for_path(str(path)).get_uri()


def to_uri(text):
    """Accept a path or URI typed or pasted by the user."""
    text = text.strip().strip('"').strip("'")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return text
    return Gio.File.new_for_commandline_arg(text).get_uri()


def display_name(uri):
    path = uri_to_path(uri)
    if path is not None:
        return path.name
    parsed = urlparse(uri)
    tail = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    return tail or parsed.netloc or uri


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def folder_media(folder, recursive=False):
    folder = Path(folder)
    pattern = folder.rglob("*") if recursive else folder.iterdir()
    try:
        files = [p for p in pattern if p.is_file() and ext_of(p) in MEDIA_EXT]
    except OSError:
        return []
    return [path_to_uri(p) for p in sorted(files, key=lambda p: _natural_key(str(p)))]


SUB_DIRS = {"subs", "sub", "subtitles", "subtitle", "srt"}
_SXXEYY = re.compile(r"s(\d{1,2})[ ._-]?e(\d{1,3})", re.I)
_NXNN = re.compile(r"(?<!\d)(\d{1,2})x(\d{2,3})(?!\d)", re.I)
_EP = re.compile(r"(?:^|[^a-z0-9])(?:e|ep|episode)[ ._-]?(\d{1,3})(?!\d)", re.I)


def episode_code(name):
    """(season, episode) from a file name, season None when only an episode is given."""
    for rx in (_SXXEYY, _NXNN):
        m = rx.search(name)
        if m:
            return int(m.group(1)), int(m.group(2))
    m = _EP.search(name)
    if m:
        return None, int(m.group(1))
    return None


def _subtitle_files(folder, depth=0):
    out = []
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return out
    for p in entries:
        if p.is_file() and ext_of(p) in SUBTITLE_EXT and ext_of(p) != "txt":
            out.append(p)
        elif p.is_dir() and depth < 2 and (depth > 0 or p.name.lower() in SUB_DIRS):
            out += _subtitle_files(p, depth + 1)
    return out


def find_subtitles(uri):
    """Every subtitle near a local media file, best match first, as [(score, uri)].

    Looks beside the file and in Subs/Subtitles folders (also Subs/<name>/).
    score 0: same name; 1: same name plus a language tag (movie.en.srt);
    2: same episode code (S01E02, 1x02, Ep02); 3: the only subtitle beside the
    only video; 9: other subtitles in the folder (listed, never auto-loaded).
    """
    path = uri_to_path(uri)
    if path is None:
        return []
    stem = path.stem.lower()
    ep = episode_code(path.stem)
    subs = _subtitle_files(path.parent)
    try:
        videos = [p for p in path.parent.iterdir() if p.is_file() and ext_of(p) in VIDEO_EXT]
    except OSError:
        videos = [path]
    ranked = []
    for p in subs:
        name = p.name.lower()
        in_named_dir = p.parent.name.lower() == stem
        if p.stem.lower() == stem:
            score = 0
        elif name.startswith(stem + ".") or name.startswith(stem + "_") or in_named_dir:
            score = 1
        elif ep is not None and episode_code(p.stem) == ep:
            score = 2
        elif len(subs) == 1 and len(videos) <= 1:
            score = 3
        else:
            score = 9
        ranked.append((score, SUBTITLE_EXT.index(ext_of(p)), name, p))
    ranked.sort()
    return [(r[0], path_to_uri(r[3])) for r in ranked]


def find_subtitle(uri):
    """URI of the subtitle to load automatically for a local media file, or None."""
    for score, sub in find_subtitles(uri):
        if score <= 3:
            return sub
        break
    return None


def read_playlist_file(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    if ext_of(path) == "pls":
        for line in text.splitlines():
            m = re.match(r"\s*File\d+\s*=\s*(.+)", line, re.I)
            if m:
                out.append(m.group(1).strip())
    else:
        out = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    uris = []
    for entry in out:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", entry):
            uris.append(entry)
        else:
            p = Path(entry)
            if not p.is_absolute():
                p = path.parent / p
            uris.append(path_to_uri(p))
    return uris


def write_playlist_file(path, entries):
    lines = ["#EXTM3U"]
    for entry in entries:
        lines.append(f"#EXTINF:-1,{entry.title}")
        local = uri_to_path(entry.uri)
        lines.append(str(local) if local else entry.uri)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def expand(uris):
    """Expand folders and playlist files into media URIs."""
    out = []
    for uri in uris:
        path = uri_to_path(uri)
        if path is not None and path.is_dir():
            out += folder_media(path, recursive=True)
        elif path is not None and ext_of(path) in PLAYLIST_EXT:
            out += read_playlist_file(path)
        else:
            out.append(uri)
    return out


class Entry:
    __slots__ = ("uri", "title", "suburi")

    def __init__(self, uri, title=None):
        self.uri = uri
        self.title = title or display_name(uri)
        self.suburi = None


class Playlist:
    def __init__(self):
        self.entries = []
        self.index = -1
        self._shuffle_order = []

    def __len__(self):
        return len(self.entries)

    @property
    def current(self):
        if 0 <= self.index < len(self.entries):
            return self.entries[self.index]
        return None

    def clear(self):
        self.entries.clear()
        self.index = -1
        self._shuffle_order = []

    def add(self, uris, titles=None):
        """Append URIs, skipping ones already queued. Returns index of the first given URI.

        ``titles`` optionally maps a URI to its display title (e.g. a search result).
        """
        first = None
        known = {e.uri: i for i, e in enumerate(self.entries)}
        for uri in uris:
            if uri in known:
                idx = known[uri]
            else:
                self.entries.append(Entry(uri, (titles or {}).get(uri)))
                idx = len(self.entries) - 1
                known[uri] = idx
            if first is None:
                first = idx
        self._shuffle_order = []
        return first

    def remove(self, idx):
        if not 0 <= idx < len(self.entries):
            return
        del self.entries[idx]
        if idx < self.index:
            self.index -= 1
        elif idx == self.index:
            self.index = min(self.index, len(self.entries) - 1) if self.entries else -1
        self._shuffle_order = []

    def move(self, src, dst):
        if not (0 <= src < len(self.entries) and 0 <= dst < len(self.entries)):
            return
        cur = self.current
        self.entries.insert(dst, self.entries.pop(src))
        if cur is not None:
            self.index = self.entries.index(cur)

    def sort(self):
        cur = self.current
        self.entries.sort(key=lambda e: _natural_key(e.title))
        if cur is not None:
            self.index = self.entries.index(cur)

    def _shuffled_neighbor(self, step):
        n = len(self.entries)
        if len(self._shuffle_order) != n:
            self._shuffle_order = list(range(n))
            random.shuffle(self._shuffle_order)
        pos = self._shuffle_order.index(self.index) if self.index in self._shuffle_order else -1
        return self._shuffle_order[(pos + step) % n], (pos + step) in range(n)

    def neighbor(self, step, loop_mode="playlist", shuffle=False):
        """Index of the next (+1) or previous (-1) entry, or None at the end without looping."""
        n = len(self.entries)
        if n == 0:
            return None
        if shuffle and n > 1:
            idx, inside = self._shuffled_neighbor(step)
            return idx if inside or loop_mode == "playlist" else None
        idx = self.index + step
        if 0 <= idx < n:
            return idx
        if loop_mode == "playlist":
            return idx % n
        return None


def media_filter():
    from gi.repository import Gtk

    filters = Gio.ListStore.new(Gtk.FileFilter)
    media = Gtk.FileFilter(name="Media files")
    for e in sorted(MEDIA_EXT | PLAYLIST_EXT):
        media.add_suffix(e)
    video = Gtk.FileFilter(name="Video")
    for e in sorted(VIDEO_EXT):
        video.add_suffix(e)
    audio = Gtk.FileFilter(name="Audio")
    for e in sorted(AUDIO_EXT):
        audio.add_suffix(e)
    everything = Gtk.FileFilter(name="All files")
    everything.add_pattern("*")
    for f in (media, video, audio, everything):
        filters.append(f)
    return filters, media


def subtitle_filter():
    from gi.repository import Gtk

    filters = Gio.ListStore.new(Gtk.FileFilter)
    subs = Gtk.FileFilter(name="Subtitles")
    for e in SUBTITLE_EXT:
        subs.add_suffix(e)
    everything = Gtk.FileFilter(name="All files")
    everything.add_pattern("*")
    filters.append(subs)
    filters.append(everything)
    return filters, subs


def fmt_time(seconds):
    if seconds is None or seconds != seconds:
        return "--:--"
    seconds = int(max(seconds, 0))
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"

