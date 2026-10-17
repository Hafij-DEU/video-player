"""Plain-text subtitle parsing for the second subtitle line (SRT, WebVTT, ASS/SSA, SAMI-free).

The first subtitle is rendered by GStreamer; a second one is drawn by GTK from
these cues, so two languages can show at once.
"""

import bisect
import html
import re
from pathlib import Path

_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_ARROW = re.compile(r"(\S+)\s*-->\s*(\S+)")
_TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")


def _secs(stamp):
    m = _TIME.fullmatch(stamp.strip())
    if not m:
        raise ValueError(stamp)
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac.ljust(3, "0")[:3]) / 1000


def _clean(text):
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    return html.unescape(_TAGS.sub("", text)).strip()


def _read(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_srt_vtt(text):
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [ln for ln in block.strip().splitlines()]
        for i, line in enumerate(lines):
            m = _ARROW.search(line)
            if m:
                try:
                    start, end = _secs(m.group(1)), _secs(m.group(2))
                except ValueError:
                    break
                body = _clean("\n".join(lines[i + 1:]))
                if body:
                    cues.append((start, end, body))
                break
    return cues


def parse_ass(text):
    cues, fmt = [], None
    for line in text.splitlines():
        if line.lower().startswith("format:") and fmt is None and "text" in line.lower():
            fmt = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
        elif line.lower().startswith("dialogue:"):
            fields = line.split(":", 1)[1].split(",", (len(fmt) - 1) if fmt else 9)
            names = fmt or ["layer", "start", "end", "style", "name", "marginl", "marginr",
                            "marginv", "effect", "text"]
            row = dict(zip(names, fields))
            try:
                start, end = _secs(row["start"]), _secs(row["end"])
            except (KeyError, ValueError):
                continue
            body = _clean(row.get("text", ""))
            if body:
                cues.append((start, end, body))
    return cues


class Cues:
    def __init__(self, cues):
        self.cues = sorted(cues)
        self.starts = [c[0] for c in self.cues]

    def __len__(self):
        return len(self.cues)

    def at(self, t):
        """Text of every cue showing at time t (overlapping cues are joined)."""
        i = bisect.bisect_right(self.starts, t)
        lines = []
        for start, end, body in self.cues[max(0, i - 8):i]:
            if start <= t < end:
                lines.append(body)
        return "\n".join(lines)


def load(path):
    text = _read(path)
    ext = Path(path).suffix.lower()
    if ext in (".ass", ".ssa") or "[Script Info]" in text[:400]:
        return Cues(parse_ass(text))
    return Cues(parse_srt_vtt(text))
