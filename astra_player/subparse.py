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


# Bytes where cp1254 (Turkish) and cp1252 (Western) differ: Ğ İ Ş ğ ı ş vs Ð Ý Þ ð ý þ.
_TR_BYTES = frozenset(b"\xd0\xdd\xde\xf0\xfd\xfe")


def _utf16_no_bom(raw):
    """'utf-16-le' / 'utf-16-be' when raw looks like BOM-less UTF-16 text, else None."""
    sample = raw[:4096]
    half = len(sample) // 2
    if half < 2:
        return None
    even = sample[0::2].count(0)
    odd = sample[1::2].count(0)
    if odd > half * 0.3 and even < half * 0.05:
        return "utf-16-le"
    if even > half * 0.3 and odd < half * 0.05:
        return "utf-16-be"
    return None


def decode_legacy(raw):
    """Decode non-UTF-8 text, choosing between Turkish, Western and Arabic code pages."""
    high = sum(1 for b in raw if b >= 0x80)
    letters = sum(1 for b in raw if 0x41 <= b <= 0x5A or 0x61 <= b <= 0x7A)
    order = ["cp1252", "cp1254", "latin-1"]
    if high and high > letters:
        order.insert(0, "cp1256")  # mostly non-Latin letters: Arabic script
    elif any(b in _TR_BYTES for b in raw):
        order.insert(0, "cp1254")  # Turkish letters (cp1252 would give Þ ý Ð ...)
    for enc in order:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def decode_text(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    enc = _utf16_no_bom(raw)  # before UTF-8: NUL bytes are valid UTF-8 too
    if enc:
        try:
            return raw[:len(raw) - len(raw) % 2].decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    return decode_legacy(raw)


def _read(path):
    return decode_text(Path(path).read_bytes())


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
        # Precompute the text of every interval between cue boundaries, so a long cue
        # stays visible however many short cues overlap it, and lookups stay O(log n).
        events = {}
        for i, (start, end, _body) in enumerate(self.cues):
            if end > start:
                events.setdefault(start, [[], []])[0].append(i)
                events.setdefault(end, [[], []])[1].append(i)
        self._times = sorted(events)
        self._texts = []
        active = set()
        for t in self._times:
            add, drop = events[t]
            active.difference_update(drop)
            active.update(add)
            self._texts.append("\n".join(self.cues[i][2] for i in sorted(active)))

    def __len__(self):
        return len(self.cues)

    def at(self, t):
        """Text of every cue showing at time t (overlapping cues are joined)."""
        k = bisect.bisect_right(self._times, t) - 1
        if k < 0:
            return ""
        return self._texts[k]


def load(path):
    text = _read(path)
    ext = Path(path).suffix.lower()
    if ext in (".ass", ".ssa") or "[Script Info]" in text[:400]:
        return Cues(parse_ass(text))
    return Cues(parse_srt_vtt(text))
