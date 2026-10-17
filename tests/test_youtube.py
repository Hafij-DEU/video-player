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

# Keep the managed yt-dlp of every test out of the real ~/.local/share.
youtube.MANAGED_DIR = Path(tempfile.mkdtemp(prefix="astra-managed-")) / "bin"
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
        self.assertEqual(youtube.search_command("lofi")[1:],
                         ["--flat-playlist", "--dump-json", "--no-warnings",
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



class SignInTest(unittest.TestCase):
    def tearDown(self):
        youtube.cookie_source = ""

    def test_detect_browsers(self):
        home = Path(tempfile.mkdtemp(prefix="astra-home-"))
        (home / ".config/BraveSoftware/Brave-Browser").mkdir(parents=True)
        (home / ".config/google-chrome-beta").mkdir(parents=True)
        (home / "snap/firefox/common/.mozilla/firefox").mkdir(parents=True)
        found = dict(youtube.detect_browsers(home))
        self.assertEqual(found["Brave"], "brave")
        self.assertEqual(found["Google Chrome Beta"], f"chrome:{home}/.config/google-chrome-beta")
        self.assertEqual(found["Firefox"], f"firefox:{home}/snap/firefox/common/.mozilla/firefox")
        self.assertNotIn("Google Chrome", found)

    def test_auth_args(self):
        self.assertEqual(youtube.auth_args(""), [])
        self.assertEqual(youtube.auth_args("brave"), ["--cookies-from-browser", "brave"])
        self.assertEqual(youtube.auth_args("file:/tmp/c.txt"), ["--cookies", "/tmp/c.txt"])
        youtube.cookie_source = "chrome"
        self.assertIn("--cookies-from-browser", youtube.search_command("lofi"))
        youtube.cookie_source = ""
        self.assertNotIn("--cookies-from-browser", youtube.search_command("lofi"))

    def test_bot_block_detection(self):
        self.assertTrue(youtube.is_bot_block(
            "ERROR: [youtube] z5y8Clp_TdE: Sign in to confirm you’re not a bot. Use --cookies"))
        self.assertTrue(youtube.is_bot_block("HTTP Error 429: Too Many Requests"))
        self.assertFalse(youtube.is_bot_block("ERROR: Video unavailable"))
        self.assertFalse(youtube.is_bot_block("ERROR: [youtube] ab429cdEFgh: Video unavailable"))

    def test_cookie_error_detection(self):
        for msg in ('ERROR: could not find brave cookies database in "/home/u/.config/Brave"',
                    "ERROR: secretstorage not available No module named 'secretstorage'",
                    "WARNING: failed to decrypt cookie (AES-CBC) because the MAC check failed",
                    "ERROR: failed to load cookies",
                    'ERROR: unsupported browser: "netscape"'):
            self.assertTrue(youtube.is_cookie_error(msg), msg)
        self.assertFalse(youtube.is_cookie_error("ERROR: Video unavailable"))

    def test_needs_keyring(self):
        self.assertTrue(youtube.needs_keyring("brave"))
        self.assertTrue(youtube.needs_keyring("chrome:/home/u/.config/google-chrome-beta"))
        self.assertTrue(youtube.needs_keyring("chromium+gnomekeyring"))
        self.assertFalse(youtube.needs_keyring("chrome+kwallet"))
        self.assertFalse(youtube.needs_keyring("firefox"))
        self.assertFalse(youtube.needs_keyring("file:/tmp/chrome.txt"))
        self.assertFalse(youtube.needs_keyring(""))


class FallbackOrderTest(unittest.TestCase):
    BROWSERS = [("Brave", "brave"), ("Google Chrome", "chrome"),
                ("Firefox", "firefox:/home/u/snap/firefox/common/.mozilla/firefox"),
                ("Vivaldi", "vivaldi")]

    def test_chosen_first_then_detection_order(self):
        self.assertEqual(youtube.fallback_order("chrome", self.BROWSERS),
                         ["chrome", "brave", self.BROWSERS[2][1], "vivaldi"])

    def test_no_duplicates_and_unknown_choice(self):
        order = youtube.fallback_order("edge", self.BROWSERS + [("Brave", "brave")])
        self.assertEqual(order, ["edge", "brave", "chrome", self.BROWSERS[2][1], "vivaldi"])
        self.assertEqual(youtube.fallback_order("", self.BROWSERS)[0], "brave")

    def test_without_keyring_chromium_browsers_go_last(self):
        self.assertEqual(youtube.fallback_order("brave", self.BROWSERS, keyring_ok=False),
                         ["brave", self.BROWSERS[2][1], "chrome", "vivaldi"])

    def test_label(self):
        self.assertEqual(youtube.browser_label("chrome", self.BROWSERS), "Google Chrome")
        self.assertEqual(youtube.browser_label("edge:/x", self.BROWSERS), "Edge")
        self.assertEqual(youtube.browser_label("file:/a/b/cookies.txt", []), "cookies.txt")


def _script(path, text):
    path.write_text(text)
    path.chmod(0o755)
    return path


class YtdlpPathTest(unittest.TestCase):
    """Which yt-dlp runs; never the user's real ~/.local/share or browsers."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="astra-ytdlp-"))
        self.saved = (youtube.MANAGED_DIR, youtube.managed_enabled, os.environ["PATH"],
                      dict(youtube._secretstorage))
        youtube.MANAGED_DIR = self.tmp / "managed"
        youtube._secretstorage.clear()
        self.sys_bin = self.tmp / "sys"
        self.sys_bin.mkdir()
        os.environ["PATH"] = f"{self.sys_bin}{os.pathsep}/usr/bin{os.pathsep}/bin"
        # Stand-in interpreters: "import secretstorage" succeeds with one, fails with the other.
        self.py_ok = _script(self.tmp / "python-ok", "#!/bin/sh\nexit 0\n")
        self.py_no = _script(self.tmp / "python-no", "#!/bin/sh\nexit 1\n")

    def tearDown(self):
        youtube.MANAGED_DIR, youtube.managed_enabled, os.environ["PATH"], cache = self.saved
        youtube._secretstorage.clear()
        youtube._secretstorage.update(cache)
        youtube.cookie_source = ""

    def managed(self, py):
        youtube.MANAGED_DIR.mkdir(exist_ok=True)
        return _script(youtube.managed_path(), f"#!{py}\n")

    def system(self, py):
        return _script(self.sys_bin / "yt-dlp", f"#!{py}\n")

    def only_fake_path(self):
        os.environ["PATH"] = str(self.sys_bin)

    def test_none(self):
        self.only_fake_path()
        self.assertIsNone(youtube.ytdlp_path(""))
        self.assertFalse(youtube.have_ytdlp())

    def test_system_when_no_managed_copy(self):
        sys_prog = self.system(self.py_ok)
        youtube.managed_enabled = True
        self.assertEqual(youtube.ytdlp_path(""), str(sys_prog))

    def test_managed_preferred_when_present_and_enabled(self):
        self.system(self.py_ok)
        managed = self.managed(self.py_ok)
        youtube.managed_enabled = True
        self.assertEqual(youtube.ytdlp_path(""), str(managed))
        self.assertEqual(youtube.ytdlp_path("brave"), str(managed))
        youtube.cookie_source = "firefox"
        self.assertEqual(youtube.search_command("x")[0], str(managed))
        youtube.managed_enabled = False
        self.assertEqual(youtube.ytdlp_path(""), str(self.sys_bin / "yt-dlp"))

    def test_keyring_browser_falls_back_to_system_with_secretstorage(self):
        sys_prog = self.system(self.py_ok)
        managed = self.managed(self.py_no)
        youtube.managed_enabled = True
        self.assertEqual(youtube.ytdlp_path("firefox"), str(managed))
        self.assertEqual(youtube.ytdlp_path("brave"), str(sys_prog))
        self.assertFalse(youtube.keyring_missing("brave"))

    def test_keyring_missing_everywhere(self):
        self.only_fake_path()
        self.system(self.py_no)
        managed = self.managed(self.py_no)
        youtube.managed_enabled = True
        self.assertEqual(youtube.ytdlp_path("chrome"), str(managed))
        self.assertTrue(youtube.keyring_missing("chrome"))
        self.assertFalse(youtube.keyring_missing("firefox"))

    def test_managed_skipped_without_its_python(self):
        self.system(self.py_ok)
        self.managed(self.tmp / "no-such-python3")
        youtube.managed_enabled = True
        self.assertEqual(youtube.ytdlp_path(""), str(self.sys_bin / "yt-dlp"))

    def test_env_shebang(self):
        os.environ["PATH"] = f"{self.tmp}{os.pathsep}{os.environ['PATH']}"
        (self.tmp / "python3").symlink_to(self.py_no)
        prog = _script(self.sys_bin / "yt-dlp", "#!/usr/bin/env python3\n")
        self.assertEqual(youtube.interpreter(prog), str(self.tmp / "python3"))
        self.assertFalse(youtube.has_secretstorage(prog))
        self.assertTrue(youtube.has_secretstorage(_script(self.tmp / "bin", "\x7fELF")))


class UpdateScheduleTest(unittest.TestCase):
    WEEK = 7 * 86400
    NOW = 1_800_000_000

    def test_never_checked(self):
        self.assertTrue(youtube.update_due(0, self.NOW))

    def test_weekly(self):
        self.assertFalse(youtube.update_due(self.NOW - 3600, self.NOW))
        self.assertFalse(youtube.update_due(self.NOW - self.WEEK + 60, self.NOW))
        self.assertTrue(youtube.update_due(self.NOW - self.WEEK, self.NOW))
        self.assertTrue(youtube.update_due(self.NOW - 30 * 86400, self.NOW))

    def test_clock_moved_back(self):
        self.assertFalse(youtube.update_due(self.NOW + 3600, self.NOW))
        self.assertTrue(youtube.update_due(self.NOW + 2 * 86400, self.NOW))


class DownloadTest(unittest.TestCase):
    """Download and update against a local stand-in for GitHub releases."""

    PAYLOAD = b"#!/usr/bin/env python3\nprint('2026.10.01')\n"

    @classmethod
    def setUpClass(cls):
        import hashlib
        import http.server
        import threading

        cls.state = {"tag": "2026.10.01", "payload": cls.PAYLOAD, "sum": None, "hits": []}

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_HEAD(self):
                self.do_GET(body=False)

            def do_GET(self, body=True):
                st = cls.state
                st["hits"].append(self.path)
                if self.path == "/latest":
                    self.send_response(302)
                    self.send_header("Location", f"/tag/{st['tag']}")
                    self.end_headers()
                    return
                data = None
                if self.path.startswith("/tag/"):
                    data = b"release page"
                elif self.path == f"/download/{st['tag']}/yt-dlp":
                    data = st["payload"]
                elif self.path == f"/download/{st['tag']}/SHA2-256SUMS":
                    digest = st["sum"] or hashlib.sha256(st["payload"]).hexdigest()
                    data = f"{'0' * 64}  yt-dlp.exe\n{digest}  yt-dlp\n".encode()
                if data is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if body:
                    self.wfile.write(data)

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.saved = youtube.MANAGED_DIR, youtube.RELEASES
        youtube.MANAGED_DIR = Path(tempfile.mkdtemp(prefix="astra-managed-")) / "bin"
        youtube.RELEASES = f"http://127.0.0.1:{self.server.server_port}"
        self.state.update(tag="2026.10.01", payload=self.PAYLOAD, sum=None, hits=[])

    def tearDown(self):
        youtube.MANAGED_DIR, youtube.RELEASES = self.saved

    def test_download_verifies_and_installs(self):
        self.assertEqual(youtube.latest_version(), "2026.10.01")
        self.assertEqual(youtube.remote_size(), len(self.PAYLOAD))
        seen = []
        self.assertEqual(youtube.download_managed(progress=seen.append), "2026.10.01")
        dest = youtube.managed_path()
        self.assertEqual(dest.read_bytes(), self.PAYLOAD)
        self.assertTrue(os.access(dest, os.X_OK))
        self.assertEqual(youtube.managed_version(), "2026.10.01")
        self.assertEqual(seen[-1], 1.0)
        self.assertFalse((youtube.MANAGED_DIR / "yt-dlp.part").exists())

    def test_checksum_mismatch_keeps_nothing(self):
        self.state["sum"] = "f" * 64
        with self.assertRaises(RuntimeError):
            youtube.download_managed()
        self.assertFalse(youtube.managed_path().exists())
        self.assertFalse((youtube.MANAGED_DIR / "yt-dlp.part").exists())
        self.assertIsNone(youtube.managed_version())

    def test_update_only_when_a_new_release_exists(self):
        self.assertEqual(youtube.update_managed(), ("2026.10.01", True))
        self.state["hits"].clear()
        self.assertEqual(youtube.update_managed(), ("2026.10.01", False))
        self.assertNotIn("/download/2026.10.01/yt-dlp", self.state["hits"])
        self.state.update(tag="2026.10.09", payload=self.PAYLOAD + b"# new\n")
        self.assertEqual(youtube.update_managed(), ("2026.10.09", True))
        self.assertTrue(youtube.managed_path().read_bytes().endswith(b"# new\n"))

    def test_failed_update_keeps_old_copy(self):
        youtube.update_managed()
        self.state.update(tag="2026.10.09", payload=b"tampered", sum="0" * 64)
        with self.assertRaises(RuntimeError):
            youtube.update_managed()
        self.assertEqual(youtube.managed_path().read_bytes(), self.PAYLOAD)
        self.assertEqual(youtube.managed_version(), "2026.10.01")


if __name__ == "__main__":
    unittest.main()
