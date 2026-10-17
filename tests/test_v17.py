"""Unit tests for 1.7: folder subtitles, second-subtitle parser, updater, stream saving."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astra_player import export, subparse, updater  # noqa: E402
from astra_player.playlist import episode_code, find_subtitle, find_subtitles, path_to_uri  # noqa: E402


def touch(root, *names):
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")


class FolderSubtitleTest(unittest.TestCase):
    def test_episode_codes(self):
        self.assertEqual(episode_code("Show.S01E02.1080p"), (1, 2))
        self.assertEqual(episode_code("show 2x05 web"), (2, 5))
        self.assertEqual(episode_code("Drama Ep 07"), (None, 7))
        self.assertIsNone(episode_code("movie 1080p"))

    def test_matches_by_name_episode_and_subs_folder(self):
        d = Path(tempfile.mkdtemp())
        touch(d, "Show.S01E02.mkv", "Show.S01E03.mkv", "Subs/Show.S01E02.English.srt",
              "Subs/Show.S01E03.English.srt", "Show.S01E03.mkv.extra/none.txt")
        best = find_subtitle(path_to_uri(d / "Show.S01E02.mkv"))
        self.assertTrue(best.endswith("Subs/Show.S01E02.English.srt"))
        ranked = find_subtitles(path_to_uri(d / "Show.S01E03.mkv"))
        self.assertLessEqual(ranked[0][0], 2)
        self.assertTrue(ranked[0][1].endswith("Show.S01E03.English.srt"))

    def test_exact_and_language_and_single(self):
        d = Path(tempfile.mkdtemp())
        touch(d, "movie.mkv", "movie.en.srt", "movie.srt")
        g = Path(tempfile.mkdtemp())
        touch(g, "Drama.Ep03.mp4", "Drama.Ep04.mp4", "subs/Drama - E03 - English.srt", "subs/Drama - E04.srt")
        self.assertTrue(find_subtitle(path_to_uri(g / "Drama.Ep04.mp4")).endswith("Drama%20-%20E04.srt"))
        self.assertTrue(find_subtitle(path_to_uri(d / "movie.mkv")).endswith("/movie.srt"))
        e = Path(tempfile.mkdtemp())
        touch(e, "film.mp4", "whatever.ass")
        self.assertTrue(find_subtitle(path_to_uri(e / "film.mp4")).endswith("whatever.ass"))
        f = Path(tempfile.mkdtemp())
        touch(f, "a.mp4", "b.mp4", "random.srt")
        self.assertIsNone(find_subtitle(path_to_uri(f / "a.mp4")))
        self.assertEqual(find_subtitles(path_to_uri(f / "a.mp4"))[0][0], 9)


class SubparseTest(unittest.TestCase):
    def test_srt_and_overlap(self):
        cues = subparse.Cues(subparse.parse_srt_vtt(
            "1\n00:00:01,000 --> 00:00:04,000\n<i>Hello</i>\nworld\n\n"
            "2\n00:00:03,500 --> 00:00:05,000\nSecond\n"))
        self.assertEqual(cues.at(2), "Hello\nworld")
        self.assertEqual(cues.at(3.7), "Hello\nworld\nSecond")
        self.assertEqual(cues.at(6), "")

    def test_vtt_and_ass(self):
        vtt = subparse.parse_srt_vtt("WEBVTT\n\n00:01.000 --> 00:02.500 align:center\nHi &amp; bye\n")
        self.assertEqual(vtt, [(1.0, 2.5, "Hi & bye")])
        ass = subparse.parse_ass("[Script Info]\n[Events]\nFormat: Layer, Start, End, Style, Name, "
                                 "MarginL, MarginR, MarginV, Effect, Text\n"
                                 "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}Line one\\NLine, two\n")
        self.assertEqual(ass, [(1.0, 3.0, "Line one\nLine, two")])


class UpdaterTest(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updater.newer("v1.7.0", "1.6.0"))
        self.assertTrue(updater.newer("v1.10.0", "1.9.3"))
        self.assertFalse(updater.newer("v1.6.0", "1.6.0"))
        self.assertFalse(updater.newer("", "1.6.0"))

    def test_due(self):
        self.assertTrue(updater.due(0, 1000))
        self.assertFalse(updater.due(1000, 1000 + 3600))
        self.assertTrue(updater.due(1000, 1000 + 25 * 3600))
        self.assertTrue(updater.due(5000, 1000))


class DownloadTest(unittest.TestCase):
    def test_stream_copy(self):
        cmd = export.build_download("https://example.com/live/index.m3u8", "/tmp/out.mkv")
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("copy", cmd)
        self.assertEqual(cmd[-1], "/tmp/out.mkv")

    def test_web_page_uses_ytdlp(self):
        cmd = export.build_download("https://www.youtube.com/watch?v=x", "/tmp/v.mkv", web_page=True)
        self.assertIn("--merge-output-format", cmd)
        self.assertEqual(cmd[-1], "https://www.youtube.com/watch?v=x")


if __name__ == "__main__":
    unittest.main()
