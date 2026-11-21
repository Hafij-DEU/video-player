"""Regression tests: subtitle/playlist encodings, long overlapping cues, playlist titles, settings types."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astra_player import settings, subparse  # noqa: E402
from astra_player.playlist import Entry, path_to_uri, read_playlist_file, write_playlist_file  # noqa: E402

SRT = "1\n00:00:01,000 --> 00:00:04,000\nŞişli'de ığdır İzmir Ğ\n"


def tmpfile(name, data):
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(data)
    return p


class SubtitleEncodingTest(unittest.TestCase):
    def test_turkish_cp1254(self):
        cues = subparse.load(tmpfile("tr.srt", SRT.encode("cp1254")))
        self.assertEqual(cues.at(2), "Şişli'de ığdır İzmir Ğ")

    def test_western_cp1252_still_works(self):
        cues = subparse.load(tmpfile("fr.srt", "1\n00:00:01,000 --> 00:00:04,000\nCafé à côté\n"
                                     .encode("cp1252")))
        self.assertEqual(cues.at(2), "Café à côté")

    def test_utf8_and_bom_utf16_unchanged(self):
        self.assertEqual(subparse.load(tmpfile("a.srt", SRT.encode("utf-8"))).at(2), SRT.split("\n")[2])
        self.assertEqual(subparse.load(tmpfile("b.srt", SRT.encode("utf-16"))).at(2), SRT.split("\n")[2])

    def test_utf16_without_bom(self):
        for enc in ("utf-16-le", "utf-16-be"):
            cues = subparse.load(tmpfile("c.srt", SRT.encode(enc)))
            self.assertEqual(len(cues), 1, enc)
            self.assertEqual(cues.at(2), "Şişli'de ığdır İzmir Ğ")

    def test_arabic_cp1256(self):
        line = "مرحبا بالعالم كيف حالك"
        cues = subparse.load(tmpfile("ar.srt", f"1\n00:00:01,000 --> 00:00:04,000\n{line}\n".encode("cp1256")))
        self.assertEqual(cues.at(2), line)


class LongCueTest(unittest.TestCase):
    def test_long_cue_behind_many_short_cues(self):
        cues = [(0.0, 100.0, "SIGN")] + [(1 + i * 0.5, 1.4 + i * 0.5, f"s{i}") for i in range(50)]
        c = subparse.Cues(cues)
        self.assertEqual(c.at(20.1), "SIGN\ns38")
        self.assertEqual(c.at(50), "SIGN")
        self.assertEqual(c.at(100), "")
        self.assertEqual(c.at(-1), "")

    def test_big_file_is_fast(self):
        cues = [(i * 2.0, i * 2.0 + 1.5, f"line {i}") for i in range(20000)] + [(0, 40000, "all")]
        c = subparse.Cues(cues)
        t0 = time.perf_counter()
        for k in range(20000):
            c.at(k * 1.999)
        self.assertLess(time.perf_counter() - t0, 1.0)
        self.assertEqual(c.at(3.0), "all\nline 1")


class PlaylistTest(unittest.TestCase):
    def test_cp1254_m3u_and_indented_comment(self):
        d = Path(tempfile.mkdtemp())
        body = "#EXTM3U\n   #EXTINF:-1,Şarkı\nŞarkı.mp3\n"
        p = d / "list.m3u"
        p.write_bytes(body.encode("cp1254"))
        self.assertEqual(read_playlist_file(p), [path_to_uri(d / "Şarkı.mp3")])

    def test_m3u8_stays_utf8(self):
        d = Path(tempfile.mkdtemp())
        p = d / "list.m3u8"
        p.write_bytes("#EXTM3U\nŞarkı.mp3\n".encode("utf-8"))
        self.assertEqual(read_playlist_file(p), [path_to_uri(d / "Şarkı.mp3")])

    def test_newline_in_title_does_not_add_entries(self):
        d = Path(tempfile.mkdtemp())
        e1 = Entry(path_to_uri(d / "a.mp4"), "Bad\nhttp://evil/x\r\n#x")
        e2 = Entry(path_to_uri(d / "b.mp4"), "Fine")
        p = d / "out.m3u"
        write_playlist_file(p, [e1, e2])
        self.assertEqual(read_playlist_file(p), [e1.uri, e2.uri])

    def test_newline_in_file_name_round_trips(self):
        d = Path(tempfile.mkdtemp())
        e = Entry(path_to_uri(d / "we\nird.mp4"), "t")
        p = d / "out.m3u"
        write_playlist_file(p, [e])
        self.assertEqual(read_playlist_file(p), [e.uri])


class SettingsTypeTest(unittest.TestCase):
    def load(self, data):
        f = tmpfile("settings.json", json.dumps(data).encode())
        with mock.patch.object(settings, "SETTINGS_FILE", f), \
                mock.patch.object(settings, "RESUME_FILE", f.with_name("resume.json")), \
                mock.patch.object(settings, "migrate_legacy", lambda: None):
            return settings.Settings()

    def test_wrong_types_fall_back_per_key(self):
        s = self.load({"recent": None, "volume": "loud", "muted": 1, "eq_bands": [1, 2],
                       "seek_short": 10, "sub_style": "classic"})
        self.assertEqual(s["recent"], [])
        self.assertEqual(s["volume"], 1.0)
        self.assertIs(s["muted"], False)
        self.assertEqual(s["eq_bands"], [0.0] * 10)
        self.assertEqual(s["seek_short"], 10)
        self.assertEqual(s["sub_style"], "classic")
        s.add_recent("file:///x")  # used to raise TypeError with recent=None
        self.assertEqual(s["recent"], ["file:///x"])

    def test_good_values_and_damaged_recent_entries(self):
        s = self.load({"volume": 0.5, "update_last_check": 1700000000.5, "recent": ["a", 3, None, "b"]})
        self.assertEqual(s["volume"], 0.5)
        self.assertEqual(s["update_last_check"], 1700000000.5)
        self.assertEqual(s["recent"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
