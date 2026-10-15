"""Unit tests for the Whisper subtitle pipeline (no display needed).

    python3 -m unittest tests/test_whisper.py

Audio extraction is always tested on clips generated with ffmpeg. The full
speech-to-text run needs a speech engine (whisper-cli or pywhispercpp) and a
downloaded model; it uses the spoken sample that ships with Ubuntu's
whisper.cpp package, or the WAV named by KILN_SPEECH_WAV, and is skipped
when either is missing. The tests never download anything.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from kiln_player import whisper  # noqa: E402
from kiln_player.playlist import path_to_uri  # noqa: E402

Gst.init(None)
FF = ["ffmpeg", "-v", "error", "-y"]
SPEECH_SAMPLES = [os.environ.get("KILN_SPEECH_WAV", ""),
                  "/usr/share/sounds/debian/samples/en-Wikipedia-Ignore_All_Rules.wav"]


def dominant_hz(wav):
    import numpy as np
    with wave.open(str(wav), "rb") as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(float)
    spec = np.abs(np.fft.rfft(data[: rate * 2]))
    return np.fft.rfftfreq(len(data[: rate * 2]), 1 / rate)[spec.argmax()]


class SrtTests(unittest.TestCase):
    def test_round_trip(self):
        segs = [(0.0, 1.5, "Hello"), (61.25, 3725.004, "two\nlines")]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.srt"
            whisper.write_srt(segs, p)
            text = p.read_text(encoding="utf-8")
            self.assertIn("00:01:01,250 --> 01:02:05,004", text)
            self.assertEqual(whisper.parse_srt(text), segs)

    def test_clean_drops_noise_markers(self):
        segs = [(0, 1, " [Music] "), (1, 2, "(silence)"), (2, 3, "  real   words ")]
        self.assertEqual(whisper._clean(segs), [(2, 3, "real words")])

    def test_clean_collapses_loops(self):
        loop = "It was in the book of the book of the book of the book of the book."
        self.assertEqual(whisper._clean([(0, 1, loop)])[0][2], "It was in the book of the book.")
        normal = "No, no. I said no to the plan."
        self.assertEqual(whisper._clean([(0, 1, normal)])[0][2], normal)

    def test_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(whisper.output_path(Path(tmp) / "My film.mkv"),
                             Path(tmp) / "My film.whisper.srt")

    def test_models_known(self):
        self.assertEqual(list(whisper.MODELS), ["tiny", "base", "small"])
        for size, sha in whisper.MODELS.values():
            self.assertGreater(size, 50_000_000)
            self.assertEqual(len(sha), 64)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = whisper.MODELS_DIR, whisper.MODEL_URL, dict(whisper.MODELS)
        src = self.tmp / "src"
        src.mkdir()
        (src / "ggml-fake.bin").write_bytes(b"x" * 1000)
        whisper.MODELS_DIR = self.tmp / "models"
        whisper.MODEL_URL = path_to_uri(src) + "/ggml-{}.bin"

    def tearDown(self):
        whisper.MODELS_DIR, whisper.MODEL_URL, models = self.saved
        whisper.MODELS.clear()
        whisper.MODELS.update(models)
        shutil.rmtree(self.tmp)

    def test_checksum_verified(self):
        import hashlib
        whisper.MODELS["fake"] = (1000, hashlib.sha256(b"x" * 1000).hexdigest())
        seen = []
        whisper.download_model("fake", seen.append)
        self.assertTrue(whisper.model_installed("fake"))
        self.assertEqual(seen[-1], 1.0)

    def test_bad_checksum_leaves_nothing(self):
        whisper.MODELS["fake"] = (1000, "0" * 64)
        with self.assertRaises(RuntimeError):
            whisper.download_model("fake")
        self.assertEqual(list(whisper.MODELS_DIR.iterdir()), [])

    def test_cancel(self):
        whisper.MODELS["fake"] = (1000, "0" * 64)
        ev = threading.Event()
        ev.set()
        with self.assertRaises(whisper.Cancelled):
            whisper.download_model("fake", cancel=ev)
        self.assertFalse(whisper.model_installed("fake"))


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="kiln-whisper-test-"))
        cls.clip = cls.tmp / "two tracks.mkv"
        subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
                             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                             "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100",
                             "-t", "4", "-map", "0:v", "-map", "1:a", "-map", "2:a",
                             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ac", "2",
                             str(cls.clip)], check=True)
        cls.silent = cls.tmp / "no audio.mkv"
        subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25", "-t", "2",
                             "-c:v", "libx264", "-preset", "ultrafast", str(cls.silent)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def _check(self, fn):
        for track, hz in ((0, 440), (1, 1000)):
            wav = self.tmp / f"t{track}.wav"
            fn(path_to_uri(self.clip), wav, track)
            with wave.open(str(wav), "rb") as wf:
                self.assertEqual((wf.getframerate(), wf.getnchannels(), wf.getsampwidth()), (16000, 1, 2))
            self.assertAlmostEqual(whisper.wav_duration(wav), 4.0, delta=0.15)
            self.assertAlmostEqual(dominant_hz(wav), hz, delta=5)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_ffmpeg(self):
        self._check(lambda uri, wav, t: whisper._ffmpeg_extract(self.clip, wav, t, 4, None, None))

    def test_gstreamer(self):
        self._check(lambda uri, wav, t: whisper._gst_extract(uri, wav, t, None, None))

    def test_no_audio(self):
        with self.assertRaises(RuntimeError):
            whisper.extract_audio(path_to_uri(self.silent), self.tmp / "none.wav")
        wav = self.tmp / "none2.wav"
        try:
            whisper._gst_extract(path_to_uri(self.silent), wav, 0, None, None)
        except RuntimeError:
            return
        self.assertFalse(wav.exists() and whisper.wav_duration(wav) > 0)


def _speech_sample():
    return next((p for p in SPEECH_SAMPLES if p and Path(p).is_file()), None)


def _installed_model():
    return next((n for n in whisper.MODELS if whisper.model_installed(n)), None)


@unittest.skipUnless(whisper.find_backend() and _installed_model() and _speech_sample(),
                     "needs a speech engine, a downloaded model and a speech sample")
class TranscribeTests(unittest.TestCase):
    def test_generate_srt_from_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "speech.mkv"
            subprocess.run(FF + ["-f", "lavfi", "-i", "color=black:size=320x240:rate=10",
                                 "-i", _speech_sample(), "-t", "16", "-shortest",
                                 "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                                 str(clip)], check=True)
            out = whisper.output_path(clip)
            stages = []
            path, count = whisper.generate(path_to_uri(clip), out, whisper.model_path(_installed_model()),
                                           language="en", progress=lambda s, f: stages.append(s))
            self.assertEqual(path, out)
            self.assertGreaterEqual(count, 1)
            text = out.read_text(encoding="utf-8").lower()
            self.assertIn("-->", text)
            self.assertIn("rule", text)
            self.assertEqual(stages[0], "extract")
            self.assertIn("transcribe", stages)

    def test_cancel_transcription(self):
        ev = threading.Event()
        ev.set()
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            whisper.extract_audio(path_to_uri(Path(_speech_sample())), wav)
            with self.assertRaises(whisper.Cancelled):
                whisper.transcribe(wav, whisper.model_path(_installed_model()), cancel=ev)


if __name__ == "__main__":
    unittest.main(verbosity=2)
