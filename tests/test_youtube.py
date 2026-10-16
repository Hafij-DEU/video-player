"""Unit tests for YouTube search (no display, no network).

    python3 -m unittest tests/test_youtube.py

The fixture is real ``yt-dlp --flat-playlist --dump-json "ytsearch3:lofi"``
output trimmed to the fields Astra Player reads, plus hand-made edge cases:
a non-JSON line, a channel entry, a duplicate, a short with partial
thumbnail sizes, and an entry with no URL or title.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astra_player import youtube  # noqa: E402
from astra_player.playlist import Playlist  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ytsearch_lofi.jsonl"


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.results = youtube.parse_search_output(FIXTURE.read_text(encoding="utf-8"))

    def test_keeps_videos_only_once(self):
        self.assertEqual([r.id for r in self.results],
                         ["rFZHOHl-L8A", "_jH2oTNRe7g", "sF80I-TQiW0", "abcDEF12345", "noUrl000001"])

    def test_fields(self):
        first = self.results[1]
        self.assertEqual(first.url, "https://www.youtube.com/watch?v=_jH2oTNRe7g")
        self.assertTrue(first.title.startswith("cozy autumn music"))
        self.assertEqual(first.channel, "Lofi Girl")
        self.assertEqual(first.duration, 3882)
        self.assertEqual(first.views, 935086)
        self.assertIn("hq720.jpg", first.thumbnail)
        self.assertFalse(first.live)

    def test_smallest_thumbnail(self):
        short = self.results[3]
        self.assertEqual(short.thumbnail, "https://i.ytimg.com/vi/abcDEF12345/default.jpg")
        # The 360-wide thumbnail comes first in yt-dlp output; it is also the smallest.
        self.assertIn("sqp=-oaymwEcCOgCEMoB", self.results[0].thumbnail)

    def test_fallbacks(self):
        short = self.results[3]
        self.assertEqual(short.channel, "Someone")  # uploader when channel is null
        self.assertTrue(short.live)
        bare = self.results[4]
        self.assertEqual(bare.url, "https://www.youtube.com/watch?v=noUrl000001")
        self.assertEqual(bare.title, bare.url)
        self.assertIsNone(bare.duration)
        self.assertIsNone(bare.views)
        self.assertIsNone(bare.thumbnail)
        self.assertIsNone(self.results[0].duration)  # live radio: duration null

    def test_describe(self):
        self.assertEqual(youtube.describe(self.results[1]), "Lofi Girl  ·  1:04:42  ·  935K views")
        self.assertEqual(youtube.describe(self.results[3]), "Someone  ·  LIVE  ·  1 view")
        self.assertEqual(youtube.describe(self.results[4]), "")

    def test_bad_input(self):
        self.assertEqual(youtube.parse_search_output(""), [])
        self.assertEqual(youtube.parse_search_output("ERROR: nope\n{broken json\n[1, 2]\n"), [])


class FormatTest(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(youtube.fmt_duration(None), "")
        self.assertEqual(youtube.fmt_duration(5), "0:05")
        self.assertEqual(youtube.fmt_duration(42825), "11:53:45")

    def test_views(self):
        self.assertEqual(youtube.fmt_views(0), "0 views")
        self.assertEqual(youtube.fmt_views(999), "999 views")
        self.assertEqual(youtube.fmt_views(1500), "1.5K views")
        self.assertEqual(youtube.fmt_views(15574995), "16M views")
        self.assertEqual(youtube.fmt_views(2_000_000_000), "2B views")

    def test_search_query(self):
        self.assertEqual(youtube.search_query("ytsearch:lofi beats"), "lofi beats")
        self.assertEqual(youtube.search_query("  YTSEARCH10: lofi"), "lofi")
        self.assertEqual(youtube.search_query("ytsearch:"), "")
        self.assertIsNone(youtube.search_query("https://youtu.be/x"))
        self.assertIsNone(youtube.search_query(""))

    def test_command(self):
        self.assertEqual(youtube.search_command("lofi"),
                         ["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings",
                          "ytsearch25:lofi"])


class FakeYtdlpTest(unittest.TestCase):
    """Run search() against a stand-in yt-dlp script that prints the fixture."""

    def setUp(self):
        self.bin = tempfile.mkdtemp(prefix="astra-fake-ytdlp-")
        self.args = Path(self.bin) / "args"
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.bin + os.pathsep + self.old_path

    def tearDown(self):
        os.environ["PATH"] = self.old_path

    def fake(self, body):
        script = Path(self.bin) / "yt-dlp"
        script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{self.args}'\n{body}\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    def test_search_runs_ytdlp(self):
        self.fake(f"cat '{FIXTURE}'")
        results = youtube.search("lofi girl")
        self.assertEqual(len(results), 5)
        self.assertEqual(self.args.read_text().splitlines()[-1], "ytsearch25:lofi girl")

    def test_search_error(self):
        self.fake("echo 'ERROR: Unable to download API page' >&2; exit 1")
        with self.assertRaisesRegex(RuntimeError, "Unable to download API page"):
            youtube.search("lofi")

    def test_missing_ytdlp(self):
        os.environ["PATH"] = self.bin  # empty folder: no yt-dlp anywhere
        self.assertFalse(youtube.have_ytdlp())
        with self.assertRaisesRegex(RuntimeError, "not installed"):
            youtube.search("lofi")


class PlaylistTitleTest(unittest.TestCase):
    def test_titles_for_web_results(self):
        pl = Playlist()
        url = "https://www.youtube.com/watch?v=_jH2oTNRe7g"
        pl.add([url], {url: "cozy autumn music"})
        pl.add(["https://example.com/a.mp4"])
        self.assertEqual([e.title for e in pl.entries], ["cozy autumn music", "a.mp4"])


if __name__ == "__main__":
    unittest.main()
