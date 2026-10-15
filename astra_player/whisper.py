"""Offline speech-to-text subtitles with whisper.cpp.

Two engines are supported, both running on the CPU by default:
  * ``whisper-cli`` from the Debian/Ubuntu ``whisper.cpp`` package
    (GPU through Vulkan when ``libggml0-backend-vulkan`` is installed);
  * the ``pywhispercpp`` Python module (``pip install --user pywhispercpp``).

Both read the same ggml model files. Nothing is ever downloaded without the
user confirming it first: ``download_model`` is only called from the UI after
a dialog that shows the model size.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from importlib.util import find_spec
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from .playlist import uri_to_path  # noqa: E402

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "astra-player"
MODELS_DIR = DATA_DIR / "models"
SUBS_DIR = DATA_DIR / "subtitles"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"

# name -> (size in bytes, sha256), from the whisper.cpp model repository.
MODELS = {
    "tiny": (77691713, "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21"),
    "base": (147951465, "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"),
    "small": (487601967, "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),
}

LANGUAGES = [
    ("auto", "Detect automatically"), ("en", "English"), ("tr", "Turkish"), ("de", "German"),
    ("fr", "French"), ("es", "Spanish"), ("it", "Italian"), ("pt", "Portuguese"),
    ("nl", "Dutch"), ("pl", "Polish"), ("ru", "Russian"), ("uk", "Ukrainian"),
    ("ar", "Arabic"), ("fa", "Persian"), ("ur", "Urdu"), ("hi", "Hindi"), ("bn", "Bengali"),
    ("zh", "Chinese"), ("ja", "Japanese"), ("ko", "Korean"), ("id", "Indonesian"),
]

WORKER = Path(__file__).with_name("whisper_worker.py")


class Cancelled(Exception):
    pass


def fmt_size(n):
    return f"{n / 1e6:.0f} MB"


def model_path(name):
    return MODELS_DIR / f"ggml-{name}.bin"


def model_installed(name):
    p = model_path(name)
    return p.is_file() and p.stat().st_size == MODELS[name][0]


def find_backend():
    """Return ("cli", path), ("python", interpreter) or None."""
    cli = shutil.which("whisper-cli")
    if cli:
        return "cli", cli
    if find_spec("pywhispercpp") is not None:
        return "python", sys.executable
    return None


def backend_label(backend=None):
    backend = backend or find_backend()
    if backend is None:
        return "Not installed"
    return "whisper.cpp (whisper-cli)" if backend[0] == "cli" else "whisper.cpp (pywhispercpp)"


def install_hint():
    return ("Install one of these speech engines, then try again:\n\n"
            "  sudo apt install whisper.cpp\n"
            "  (add libggml0-backend-vulkan for GPU)\n\n"
            "or, without root:\n\n"
            "  pip install --user --break-system-packages pywhispercpp")


def download_model(name, progress=None, cancel=None):
    """Fetch a model into MODELS_DIR and verify its checksum. Only call after the user agreed."""
    size, sha = MODELS[name]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = model_path(name)
    part = dest.with_suffix(".part")
    digest = hashlib.sha256()
    done = 0
    req = urllib.request.Request(MODEL_URL.format(name), headers={"User-Agent": "astra-player"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as out:
            while chunk := resp.read(1 << 16):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done / size)
        if done != size or digest.hexdigest() != sha:
            raise RuntimeError("Downloaded model is damaged (checksum mismatch)")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


# ------------------------------------------------------------------- audio

def _ffmpeg_extract(src, wav, track, duration, progress, cancel):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", f"0:a:{track}?",
           "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav",
           "-progress", "pipe:1", str(wav)]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        try:
            for line in proc.stdout:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if line.startswith("out_time_us=") and duration and progress:
                    try:
                        progress(min(int(line.split("=", 1)[1]) / 1e6 / duration, 1.0))
                    except ValueError:
                        pass
            err = proc.stderr.read()
        finally:
            if proc.poll() is None:
                proc.kill()
    if proc.returncode != 0:
        raise RuntimeError((err.strip().splitlines() or ["ffmpeg failed"])[-1])


def _gst_extract(uri, wav, track, progress, cancel):
    pipe = Gst.Pipeline()
    dec = Gst.ElementFactory.make("uridecodebin")
    dec.set_property("uri", uri)
    conv = Gst.ElementFactory.make("audioconvert")
    res = Gst.ElementFactory.make("audioresample")
    caps = Gst.ElementFactory.make("capsfilter")
    caps.set_property("caps", Gst.Caps.from_string("audio/x-raw,format=S16LE,rate=16000,channels=1"))
    enc = Gst.ElementFactory.make("wavenc")
    sink = Gst.ElementFactory.make("filesink")
    sink.set_property("location", str(wav))
    for el in (dec, conv, res, caps, enc, sink):
        pipe.add(el)
    conv.link(res)
    res.link(caps)
    caps.link(enc)
    enc.link(sink)
    seen = [0]

    def skip_video(_bin, _pad, _caps, factory):
        # Do not waste time decoding pictures: only the sound is needed.
        klass = factory.get_metadata("klass") or ""
        return 2 if "Decoder" in klass and ("Video" in klass or "Image" in klass) else 0

    def pad_added(_dec, pad):
        name = (pad.get_current_caps() or pad.query_caps(None)).get_structure(0).get_name()
        target = None
        if name.startswith("audio/x-raw"):
            if seen[0] == track:
                target = conv.get_static_pad("sink")
            seen[0] += 1
        if target is None or target.is_linked():
            fake = Gst.ElementFactory.make("fakesink")
            fake.set_property("sync", False)
            fake.set_property("async", False)
            pipe.add(fake)
            fake.sync_state_with_parent()
            target = fake.get_static_pad("sink")
        pad.link(target)

    def no_more_pads(_dec):
        if not conv.get_static_pad("sink").is_linked():
            conv.get_static_pad("sink").send_event(Gst.Event.new_eos())

    dec.connect("autoplug-select", skip_video)
    dec.connect("pad-added", pad_added)
    dec.connect("no-more-pads", no_more_pads)
    bus = pipe.get_bus()
    pipe.set_state(Gst.State.PLAYING)
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            msg = bus.timed_pop_filtered(200 * Gst.MSECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if msg is None:
                ok_p, pos = pipe.query_position(Gst.Format.TIME)
                ok_d, dur = pipe.query_duration(Gst.Format.TIME)
                if progress and ok_p and ok_d and dur > 0:
                    progress(min(pos / dur, 1.0))
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                raise RuntimeError(err.message)
            break
    finally:
        pipe.set_state(Gst.State.NULL)


def extract_audio(uri, wav, track=0, duration=None, progress=None, cancel=None):
    """Write the chosen audio track of ``uri`` as 16 kHz mono 16-bit WAV."""
    src = uri_to_path(uri)
    if src is not None and shutil.which("ffmpeg"):
        _ffmpeg_extract(src, wav, track, duration, progress, cancel)
    else:
        _gst_extract(uri, wav, track, progress, cancel)
    if not Path(wav).is_file() or Path(wav).stat().st_size <= 44:
        raise RuntimeError("This file has no audio track")


def wav_duration(wav):
    return max(Path(wav).stat().st_size - 44, 0) / 32000.0


# ------------------------------------------------------------- transcribe

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_CLI_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")


def parse_srt(text):
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                body = "\n".join(lines[i + 1:]).strip()
                if body:
                    segments.append((t0, t1, body))
                break
    return segments


def _srt_time(t):
    ms = int(round(max(t, 0) * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_srt(segments, path):
    out = []
    for n, (t0, t1, text) in enumerate(segments, 1):
        out.append(f"{n}\n{_srt_time(t0)} --> {_srt_time(max(t1, t0 + 0.2))}\n{text.strip()}\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")


_LOOP = re.compile(r"(\b.{3,80}?)(?:[\s,.]*\1){2,}")


def _clean(segments):
    keep = []
    for t0, t1, text in segments:
        text = " ".join(text.split())
        # Small models sometimes get stuck repeating a phrase; keep one copy.
        text = _LOOP.sub(r"\1", text)
        # whisper marks silence and music like this; they make poor subtitles.
        if not text or re.fullmatch(r"[\[(][^\])]*[\])]", text):
            continue
        keep.append((t0, t1, text))
    return keep


def _run(cmd, on_line, cancel):
    tail = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          errors="replace") as proc:
        def watch():
            while proc.poll() is None:
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    return
                time.sleep(0.1)

        threading.Thread(target=watch, daemon=True).start()
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-8:]
            on_line(line)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        msg = next((ln for ln in reversed(tail) if "error" in ln.lower()), tail[-1] if tail else "")
        raise RuntimeError(msg or f"speech engine exited with code {proc.returncode}")


def transcribe(wav, model, language="auto", translate=False, gpu=False, threads=None,
               backend=None, progress=None, cancel=None):
    """Return a list of (start, end, text) segments for a 16 kHz mono WAV file."""
    backend = backend or find_backend()
    if backend is None:
        raise RuntimeError("No speech engine installed")
    threads = threads or max(1, min(os.cpu_count() or 4, 8))
    total = wav_duration(wav) or 1.0

    if backend[0] == "cli":
        with tempfile.TemporaryDirectory(prefix="astra-whisper-") as tmp:
            base = Path(tmp) / "out"
            cmd = [backend[1], "-m", str(model), "-f", str(wav), "-l", language, "-t", str(threads),
                   "-mc", "0", "-pp", "-osrt", "-of", str(base)]
            if translate:
                cmd.append("-tr")
            if not gpu:
                cmd.append("-ng")

            def on_line(line):
                m = _CLI_PROGRESS.search(line)
                if m and progress:
                    progress(int(m.group(1)) / 100)

            _run(cmd, on_line, cancel)
            srt = base.with_suffix(".srt")
            return _clean(parse_srt(srt.read_text(encoding="utf-8", errors="replace")))

    segments = []
    cmd = [backend[1], str(WORKER), "--model", str(model), "--wav", str(wav), "--language", language,
           "--threads", str(threads)] + (["--translate"] if translate else [])

    def on_line(line):
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if "seg" in msg:
            t0, t1, text = msg["seg"]
            segments.append((t0, t1, text))
            if progress:
                progress(min(t1 / total, 1.0))

    _run(cmd, on_line, cancel)
    return _clean(segments)


# ------------------------------------------------------------------- job

def output_path(media_path):
    """``movie.mkv`` -> ``movie.whisper.srt`` beside it, or in SUBS_DIR if that folder is read-only."""
    media_path = Path(media_path)
    beside = media_path.with_name(media_path.stem + ".whisper.srt")
    if os.access(media_path.parent, os.W_OK):
        return beside
    SUBS_DIR.mkdir(parents=True, exist_ok=True)
    return SUBS_DIR / beside.name


def generate(uri, out_path, model, language="auto", translate=False, gpu=False, track=0,
             duration=None, backend=None, progress=None, cancel=None):
    """Extract audio, transcribe it and write ``out_path``. ``progress(stage, fraction)``."""
    report = progress or (lambda _s, _f: None)
    with tempfile.TemporaryDirectory(prefix="astra-whisper-") as tmp:
        wav = Path(tmp) / "audio.wav"
        report("extract", 0.0)
        extract_audio(uri, wav, track, duration, lambda f: report("extract", f), cancel)
        report("transcribe", 0.0)
        segments = transcribe(wav, model, language, translate, gpu, backend=backend,
                              progress=lambda f: report("transcribe", f), cancel=cancel)
    if not segments:
        raise RuntimeError("No speech was recognized")
    write_srt(segments, out_path)
    return out_path, len(segments)
