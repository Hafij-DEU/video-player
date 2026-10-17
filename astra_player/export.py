"""Save a time range of the current media to a new file (the "record" feature).

Local files and direct stream URLs go through ffmpeg. Web pages such as YouTube
go through yt-dlp's --download-sections, which calls ffmpeg itself.

Two modes:
  fast    stream copy: instant and lossless, but cuts land on keyframes
  precise re-encode to H.264/AAC MP4: frame-accurate, slower
"""

import re
import shutil
import subprocess
import threading
from pathlib import Path

from gi.repository import GLib

from .playlist import ext_of, uri_to_path

COPY_EXT = {"mkv", "mp4", "mov", "webm", "ts", "m2ts", "mts", "avi", "flv", "m4v", "mka",
            "mp3", "m4a", "flac", "ogg", "opus", "wav", "aac"}
AUDIO_EXT = {"mp3", "m4a", "flac", "ogg", "opus", "wav", "aac", "mka", "wma", "ape", "wv"}

_FF_PROGRESS = re.compile(r"out_time_us=(\d+)")
_YT_PROGRESS = re.compile(r"(\d+(?:\.\d+)?)%")


def available():
    return shutil.which("ffmpeg") is not None


def stamp(seconds):
    seconds = max(seconds, 0.0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}.{int(m):02}.{s:04.1f}" if h else f"{int(m):02}.{s:04.1f}"


def default_name(title, start, end, precise, source_uri, has_video=True):
    stem = Path(title).stem if "." in title[-6:] else title
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip() or "clip"
    src_ext = ext_of(uri_to_path(source_uri) or "") if source_uri.startswith("file:") else ""
    if precise:
        ext = "mp4" if has_video else "m4a"
    elif src_ext in COPY_EXT:
        ext = src_ext
    else:
        ext = "mkv"
    return f"{stem} [{stamp(start)}-{stamp(end)}].{ext}"


def build_command(source, start, end, out_path, precise, web_page=False):
    """Return the argv that writes [start, end] of source to out_path."""
    dur = max(end - start, 0.05)
    out = str(out_path)
    if web_page:
        from .youtube import auth_args, js_args, ytdlp_command
        cmd = [*ytdlp_command(), "--no-playlist", "--newline", "--no-warnings", "--force-overwrites", *auth_args(), *js_args(),
               "--download-sections", f"*{start:.3f}-{end:.3f}",
               "-f", "bv*+ba/b", "-o", out]
        if precise:
            cmd.append("--force-keyframes-at-cuts")
        if out.endswith((".mp4", ".mkv", ".webm")):
            cmd += ["--merge-output-format", out.rsplit(".", 1)[1]]
        cmd.append(source)
        return cmd

    path = uri_to_path(source)
    src = str(path) if path is not None else source
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"]
    if precise:
        cmd += ["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}",
                "-map", "0:v:0?", "-map", "0:a?", "-sn", "-dn",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    else:
        cmd += ["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}",
                "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero"]
        if out.endswith((".mp4", ".m4v", ".mov", ".m4a")):
            cmd += ["-map", "-0:s", "-map", "-0:d", "-movflags", "+faststart"]
        cmd.append(out)
    return cmd


def build_download(source, out_path, web_page=False):
    """argv that saves a whole video (web page via yt-dlp) or stream (ffmpeg copy)."""
    out = str(out_path)
    if web_page:
        from .youtube import auth_args, js_args, ytdlp_command
        cmd = [*ytdlp_command(), "--no-playlist", "--newline", "--no-warnings", "--force-overwrites",
               *auth_args(), *js_args(), "-f", "bv*+ba/b", "-o", out]
        if out.endswith((".mp4", ".mkv", ".webm")):
            cmd += ["--merge-output-format", out.rsplit(".", 1)[1]]
        return cmd + [source]
    path = uri_to_path(source)
    src = str(path) if path is not None else source
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats",
            "-i", src, "-map", "0", "-c", "copy", out]


class Export:
    """Run one export in a thread; callbacks fire on the GTK main loop."""

    def __init__(self, cmd, duration, on_progress, on_done):
        self.cmd = cmd
        self.duration = max(duration, 0.05)
        self.on_progress = on_progress
        self.on_done = on_done
        self.proc = None
        self.cancelled = False
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def _run(self):
        tail = []
        try:
            self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1)
            for line in self.proc.stdout:
                line = line.strip()
                if line:
                    tail = (tail + [line])[-12:]
                m = _FF_PROGRESS.match(line)
                if m:
                    frac = int(m.group(1)) / 1e6 / self.duration
                    GLib.idle_add(self.on_progress, min(max(frac, 0.0), 1.0))
                elif line.startswith("[download]"):
                    m = _YT_PROGRESS.search(line)
                    if m:
                        GLib.idle_add(self.on_progress, min(float(m.group(1)) / 100, 1.0))
            code = self.proc.wait()
        except OSError as exc:
            GLib.idle_add(self.on_done, str(exc))
            return
        if self.cancelled:
            GLib.idle_add(self.on_done, "cancelled")
        elif code != 0:
            errors = [ln for ln in tail if not ln.startswith(("frame=", "out_time", "progress=", "speed=",
                                                                "bitrate=", "total_size", "fps=", "stream_",
                                                                "dup_frames", "drop_frames", "[download]"))]
            GLib.idle_add(self.on_done, (errors or tail or [f"exit code {code}"])[-1])
        else:
            GLib.idle_add(self.on_done, None)
