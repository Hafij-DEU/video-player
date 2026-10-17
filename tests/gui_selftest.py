"""End-to-end smoke test: drives a real Astra Player window.

Run under a private X server, for example:
    Xvfb :77 -screen 0 1280x800x24 &  DISPLAY=:77 GDK_BACKEND=x11 python3 tests/gui_selftest.py
Media files are generated with ffmpeg into a temp folder.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="astra-cfg-"))

from gi.repository import GLib  # noqa: E402

from astra_player import whisper, youtube  # noqa: E402
from astra_player.app import AstraApp  # noqa: E402
from astra_player.playlist import path_to_uri  # noqa: E402
from astra_player.shaders import SHADERS  # noqa: E402

MEDIA = Path(tempfile.mkdtemp(prefix="astra-media-"))
youtube.MANAGED_DIR = MEDIA / "managed-bin"  # never the real ~/.local/share
youtube.remote_size = lambda tag=None: None  # no network
FF = ["ffmpeg", "-v", "error", "-y"]
# Spoken English sample from Ubuntu's whisper.cpp package (or ASTRA_SPEECH_WAV).
SPEECH_WAV = next((p for p in (os.environ.get("ASTRA_SPEECH_WAV", ""),
                               "/usr/share/sounds/debian/samples/en-Wikipedia-Ignore_All_Rules.wav")
                   if p and Path(p).is_file()), None)


def make_media():
    subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                         "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
                         "-t", "90", "-map", "0:v", "-map", "1:a", "-map", "2:a",
                         "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-c:a", "aac",
                         "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=tur",
                         str(MEDIA / "a_clip.mkv")], check=True)
    (MEDIA / "a_clip.srt").write_text(
        "1\n00:00:00,500 --> 00:00:20,000\nHello subtitle\n\n", encoding="utf-8")
    subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                         "-f", "lavfi", "-i", "sine=frequency=300", "-t", "6",
                         "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1",
                         "-c:a", "ac3", "-x265-params", "log-level=error",
                         str(MEDIA / "b_hevc.mp4")], check=True)
    subprocess.run(FF + ["-f", "lavfi", "-i", "sine=frequency=500:sample_rate=44100", "-t", "5",
                         "-metadata", "title=Test Tone", "-metadata", "artist=Astra",
                         str(MEDIA / "c_song.flac")], check=True)


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def wait_for(win, pred, timeout=10.0):
    end = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if pred():
            return True
        time.sleep(0.02)
    return False


def pump(seconds):
    wait_for(None, lambda: False, seconds)


def scenario(app):
    win = app.window
    e = win.engine
    win.settings["screenshot_dir"] = str(MEDIA / "shots")
    print(f"GL path: {e.gl}", flush=True)

    win.open_uris([path_to_uri(MEDIA / "a_clip.mkv")])
    check("playlist auto-adds folder", len(win.playlist) == 3, f"({len(win.playlist)} items)")
    check("mkv starts playing", wait_for(win, lambda: e.playing and (e.position() or 0) > 0.3))
    check("video page shown", win.stack.get_visible_child_name() == "video")
    check("two audio tracks", len(e.audio_tracks()) == 2, str(e.audio_tracks()))
    check("external subtitle auto-loaded", len(e.subtitle_tracks()) >= 1, str(e.subtitle_tracks()))
    check("video size 640x360", e.video_size() == (640, 360), str(e.video_size()))

    win.seek_by(10)
    check("seek +10 s", wait_for(win, lambda: (e.position() or 0) >= 9.5), f"pos={e.position()}")
    win.set_speed(2.0)
    p0 = e.position()
    pump(1.0)
    check("2x speed", (e.position() - p0) > 1.5, f"advanced {e.position() - p0:.2f}s")
    win.set_speed(1.0)

    win.activate_action("win.audio-track", GLib.Variant.new_int32(1))
    pump(0.3)
    check("switch audio track", e.current_audio == 1)

    win.shift_subs(0.5)
    check("subtitle delay", abs(e.subtitle_delay - 0.5) < 1e-6)
    win.shift_subs(None)

    win.change_volume(0.5)
    check("volume amplify >100%", e.volume > 1.0, f"{e.volume}")
    win.toggle_mute()
    check("mute", e.mute)
    win.toggle_mute()

    win.nudge_color("brightness", 1)
    check("brightness nudge", abs(e.balance.get_property("brightness") - 0.05) < 1e-6)
    win.reset_color()

    if e.gl:
        win.activate_action("win.shader", GLib.Variant.new_string("Grayscale"))
        pump(0.5)
        check("shader applied", e.shader.get_property("fragment") == SHADERS["Grayscale"])
        check("still playing after shader", e.playing and e.uri is not None)
        win.activate_action("win.shader", GLib.Variant.new_string("none"))

    for mode in ("16:9", "crop", "default"):
        win.activate_action("win.aspect", GLib.Variant.new_string(mode))
    check("aspect modes", win.picture.get_parent() is win.video_holder)

    win.activate_action("win.flip", GLib.Variant.new_string("clockwise"))
    pump(0.5)
    check("rotate keeps playing", e.playing)
    win.activate_action("win.flip", GLib.Variant.new_string("automatic"))

    pos = e.position()
    win.set_ab(0)
    pump(1.2)
    win.set_ab(1)
    pump(2.0)
    check("A-B loop", e.position() <= win.ab[1] + 0.4, f"A={win.ab[0]:.1f} B={win.ab[1]:.1f} now={e.position():.1f}")
    win.clear_ab()

    e.pause()
    wait_for(win, lambda: not e.playing)
    before = e.position()
    e.frame_step(True)
    pump(0.4)
    check("frame step", e.position() is not None and e.position() > before - 0.001,
          f"{before:.3f} -> {e.position():.3f}")
    e.play()

    pump(0.5)
    shot = win.screenshot()
    check("screenshot saved", shot is not None and shot.exists() and shot.stat().st_size > 1000, str(shot))

    win.step_playlist(1)
    check("HEVC + AC3 plays", wait_for(win, lambda: e.playing and (e.position() or 0) > 0.3 and e.uri.endswith("b_hevc.mp4")))
    check("HEVC video size", e.video_size() == (320, 240), str(e.video_size()))

    check("EOS advances to FLAC", wait_for(win, lambda: e.uri and e.uri.endswith("c_song.flac") and e.playing, 15))
    check("audio page for music", wait_for(win, lambda: win.stack.get_visible_child_name() == "audio"))
    check("tags read", wait_for(win, lambda: e.tags.get("title") == "Test Tone"), str(e.tags.get("title")))

    win.settings["loop_mode"] = "none"
    check("stops at end of playlist", wait_for(win, lambda: e.uri is None, 12))

    win.open_uris([path_to_uri(MEDIA / "a_clip.mkv")])
    wait_for(win, lambda: e.playing and (e.position() or 0) > 0.2)
    win.seek_by(20)
    wait_for(win, lambda: (e.position() or 0) > 19)
    win.stop()
    check("resume saved", (win.settings.get_resume(path_to_uri(MEDIA / "a_clip.mkv")) or 0) > 15)
    win.open_uris([path_to_uri(MEDIA / "a_clip.mkv")])
    check("resume restores position", wait_for(win, lambda: e.playing and (e.position() or 0) > 15),
          f"pos={e.position()}")

    win.fullscreen()
    pump(0.5)
    win.unfullscreen()
    pump(0.3)

    feature_checks(win)
    library_checks(win)
    youtube_checks(win)
    whisper_checks(win)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed", flush=True)
    app.exit_code = 1 if failed else 0
    app.quit()


def _probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def feature_checks(win):
    """Repeat button, folder play, picture in picture, recording a portion."""
    e = win.engine

    win.settings["loop_mode"] = "none"
    win._update_repeat_ui()
    seen = []
    for _ in range(3):
        win.activate_action("win.repeat-cycle", None)
        seen.append(win.settings["loop_mode"])
    check("repeat button cycles modes", seen == ["one", "playlist", "none"], str(seen))
    win.activate_action("win.repeat-cycle", None)
    check("repeat icon follows mode", win.repeat_btn.get_icon_name() == "media-playlist-repeat-song-symbolic")

    win.open_uris([path_to_uri(MEDIA)], expand_folder=False)
    check("folder play queues all media", wait_for(win, lambda: len(win.playlist) == 3 and e.playing),
          f"({len(win.playlist)} items)")
    win.settings["loop_mode"] = "playlist"

    win.open_uris([path_to_uri(MEDIA / "a_clip.mkv")])
    wait_for(win, lambda: e.playing and e.uri.endswith("a_clip.mkv") and (e.position() or 0) > 0.3)
    win.activate_action("win.pip", None)
    pump(0.6)
    check("PiP window opens", win.pip is not None and win.pip.get_visible())
    check("main window hidden in PiP", not win.get_visible())
    check("video keeps playing in PiP", e.playing)
    win.activate_action("win.pip", None)
    pump(0.4)
    check("PiP returns to main window", win.pip is None and win.get_visible())

    e.seek(5)
    wait_for(win, lambda: 4.9 < (e.position() or 0) < 6)
    win.toggle_record()
    check("record start marks position", win._rec_start is not None and "REC" in win.info_label.get_label())
    win._rec_start = 5.0
    entry = win.playlist.current
    for precise, name in ((False, "fast.mkv"), (True, "precise.mp4")):
        out = MEDIA / name
        win._run_export(entry, 5.0, 9.0, precise, False, out)
        ok = wait_for(win, lambda: win._export is None, 60)
        dur = _probe_duration(out) if out.exists() else None
        check(f"save portion ({'precise' if precise else 'fast'})",
              ok and dur is not None and 3.0 < dur < 5.5, f"duration={dur}")
    win._rec_start = None
    win.record_btn.remove_css_class("recording")
    win._update_info()


def library_checks(win):
    """Saved playlists: create via the picker, play from an item, rename, delete, persist."""
    from astra_player.library import Library, make_item
    from astra_player.library_dialog import LibraryDialog, choose_playlist
    e = win.engine
    lib_path = MEDIA / "library" / "playlists.json"
    win.library = Library(lib_path)

    made = []
    choose_playlist(win, win.library, "Road trip", lambda pl, created: made.append((pl, created)))
    pump(0.3)
    picker = win.get_visible_dialog()
    picker.emit("response", "save")
    picker.close()
    pump(0.2)
    check("picker creates a named playlist", made and made[0][1] and made[0][0].name == "Road trip")
    pl = made[0][0]
    win.library.add_items(pl.id, [make_item(path_to_uri(MEDIA / "a_clip.mkv"), "Clip A"),
                                  make_item(path_to_uri(MEDIA / "b_hevc.mp4"), "Clip B")])

    ui = LibraryDialog(win).present()
    pump(0.4)
    check("library lists saved playlists", ui.index_list.get_row_at_index(0) is not None
          and ui.index_list.get_row_at_index(1) is None)
    ui.open_playlist(pl.id)
    pump(0.4)
    check("playlist page lists items", ui.detail_list.get_row_at_index(1) is not None)
    ui.play(pl.id, 1)
    check("play saved playlist from item 2", wait_for(
        win, lambda: e.playing and e.uri and e.uri.endswith("b_hevc.mp4"), 10)
        and len(win.playlist) == 2 and win.playlist.current.title == "Clip B")

    win.library.rename(pl.id, "Trip")
    check("saved playlist survives restart", [p.name for p in Library(lib_path).playlists] == ["Trip"]
          and len(Library(lib_path).playlists[0].items) == 2)

    ui = LibraryDialog(win).present()
    pump(0.3)
    ui.delete(pl.id)
    pump(0.3)
    confirm = win.get_visible_dialog()
    confirm.emit("response", "ok")
    confirm.close()
    pump(0.2)
    check("delete saved playlist", Library(lib_path).playlists == [])
    ui.dialog.close()
    pump(0.3)


def youtube_checks(win):
    """Search YouTube with a stand-in yt-dlp that prints canned results (no network)."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "ytsearch_lofi.jsonl"
    fake_bin = MEDIA / "fake-bin"
    fake_bin.mkdir()
    fake = fake_bin / "yt-dlp"
    fake.write_text(f"#!/bin/sh\nsleep 0.3\ncat '{fixture}'\n")
    fake.chmod(0o755)
    old_path = os.environ["PATH"]
    os.environ["PATH"] = f"{fake_bin}{os.pathsep}{old_path}"
    try:
        check("Ctrl+Y opens YouTube search",
              "<Control>y" in win.app.get_accels_for_action("win.youtube-search"))
        win.open_typed("ytsearch:lofi")
        pump(0.1)
        dlg = win._search_dialog
        check("search dialog shows spinner", dlg.stack.get_visible_child_name() == "searching"
              and dlg.entry.get_text() == "lofi")
        check("search results listed", wait_for(
            win, lambda: dlg.stack.get_visible_child_name() == "results", 10)
            and dlg.listbox.get_row_at_index(4) is not None, f"{len(dlg.results)} results")
        before = len(win.playlist)
        dlg.add(1)
        last = win.playlist.entries[-1]
        check("add to playlist keeps title", len(win.playlist) == before + 1
              and last.uri.endswith("_jH2oTNRe7g") and last.title.startswith("cozy autumn"),
              last.title)
        import astra_player.search_dialog as sd
        real_choose = sd.choose_playlist
        sd.choose_playlist = lambda _p, lib, name, cb, **_k: cb(lib.create(name), True)
        try:
            dlg.save_all()
            dlg.save(0)
        finally:
            sd.choose_playlist = real_choose
        saved = [p for p in win.library.playlists if p.name == "lofi"]
        check("save search results as playlist", len(saved) == 1 and len(saved[0].items) == len(dlg.results)
              and saved[0].items[1]["title"].startswith("cozy autumn"),
              f"{len(saved[0].items) if saved else 0} items")
        check("save one video to a playlist", saved and win.library.get(saved[0].id)
              and sum(1 for p in win.library.playlists if p.name.startswith("lofi")) == 2
              and len(win.library.playlists[-1].items) == 1)
        dlg.dialog.close()
        pump(0.3)
        win.playlist.remove(len(win.playlist) - 1)

        signin_checks(win, fake)
        managed_ytdlp_checks(win, fake)
        from astra_player import youtube as yt
        yt.cookie_source = ""
        win.open_uris([path_to_uri(MEDIA / "a_clip.mkv")])
        wait_for(win, lambda: win.engine.playing and (win.engine.position() or 0) > 0.2)
        win._refresh_playlist()
    finally:
        os.environ["PATH"] = old_path


def signin_checks(win, fake):
    """YouTube's bot check: one-time consent, automatic replay, then the next browser.

    The stand-in yt-dlp fails with the bot error unless it gets
    --cookies-from-browser with the browser named in ok_browser.txt. No real
    browser cookies are read: yt-dlp itself is never run here.
    """
    from astra_player import youtube as yt
    args_log, ok_file = MEDIA / "ytdlp-args.txt", MEDIA / "ok_browser.txt"
    video, audio = path_to_uri(MEDIA / "a_clip.mkv"), path_to_uri(MEDIA / "c_song.flac")
    fake.write_text("#!/bin/sh\n"
                    f"echo \"$*\" >> '{args_log}'\n"
                    f"ok=$(cat '{ok_file}')\n"
                    "case \" $* \" in *\" --cookies-from-browser $ok \"*)\n"
                    f"  printf 'Stand-in video\\n%s\\n%s\\n' '{video}' '{audio}'; exit 0;;\n"
                    "esac\n"
                    "echo \"ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. "
                    "Use --cookies-from-browser or --cookies for the authentication.\" >&2\nexit 1\n")
    ok_file.write_text("firefox")
    saved_detect = yt.detect_browsers
    yt.detect_browsers = lambda home=None: [("Brave", "brave"), ("Firefox", "firefox")]
    osd_log = []
    real_osd = win.show_osd

    def logging_osd(text, ms=1800):
        osd_log.append(text)
        real_osd(text, ms)

    win.show_osd = logging_osd
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    try:
        win.engine.stop()
        win.settings["youtube_cookies"] = ""
        yt.cookie_source = ""
        win.open_uris([url])
        ok = wait_for(win, lambda: win.get_visible_dialog() is not None, 10)
        dlg = win.get_visible_dialog()
        check("bot check asks for sign-in consent", ok and dlg.get_heading() == "Sign in to YouTube?"
              and "Use your YouTube login from Brave?" in dlg.get_body()
              and "sign-in needed" in (win.osd.get_label() or ""), dlg.get_heading() if dlg else "none")
        log = args_log.read_text() if args_log.exists() else ""
        check("no browser cookies before consent", "--cookies" not in log and win.engine.uri is None
              and win.settings["youtube_cookies"] == "")
        check("consent lists detected browsers", dlg is not None
              and dlg.browser_dropdown.get_model().get_n_items() == 2 and dlg.ytdlp_check is not None)
        if dlg is None:
            return
        args_log.write_text("")
        dlg.browser_dropdown.set_selected(0)
        dlg.emit("response", "allow")
        dlg.close()
        played = wait_for(win, lambda: win.engine.uri == video, 15)
        lines = args_log.read_text().splitlines()
        brave = [i for i, ln in enumerate(lines) if "--cookies-from-browser brave" in ln]
        firefox = [i for i, ln in enumerate(lines) if "--cookies-from-browser firefox" in ln]
        check("Allow replays the entry with Brave", bool(brave) and brave[0] == 0, str(lines[:1]))
        check("falls back to the next browser", bool(firefox) and firefox[0] > brave[-1]
              and "Trying Firefox\u2026" in osd_log, str(osd_log[-4:]))
        check("plays once a browser works", played and win.playlist.current.title == "Stand-in video",
              str(win.engine.uri))
        check("working browser is remembered", win.settings["youtube_cookies"] == "firefox"
              and yt.cookie_source == "firefox" and win._yt_attempt is None)

        # Every browser fails: stop with a clear message and keep the user's choice.
        win.engine.stop()
        ok_file.write_text("none")
        win.settings["youtube_cookies"] = yt.cookie_source = "brave"
        osd_log.clear()
        args_log.write_text("")
        win.open_uris([url])
        ok = wait_for(win, lambda: win.get_visible_dialog() is not None, 15)
        dlg = win.get_visible_dialog()
        lines = args_log.read_text().splitlines()
        check("all browsers fail: clear message", ok and dlg.get_heading() == "YouTube still wants a sign-in"
              and "sign in" in dlg.get_body() and "Trying Firefox\u2026" in osd_log
              and sum("--cookies-from-browser" in ln for ln in lines) >= 2
              and win.engine.uri is None, dlg.get_body()[:70] if dlg else str(osd_log))
        check("choice restored after failing", yt.cookie_source == "brave"
              and win.settings["youtube_cookies"] == "brave" and win._yt_attempt is None)
        if dlg:
            dlg.close()
            pump(0.3)
    finally:
        del win.show_osd
        yt.detect_browsers = saved_detect
        win.settings["youtube_cookies"] = yt.cookie_source = ""


def managed_ytdlp_checks(win, fake):
    """Astra Player's own yt-dlp: asked first with the size, then preferred over PATH."""
    from astra_player import youtube as yt
    saved = yt.update_managed, yt.remote_size
    yt.remote_size = lambda tag=None: 3_072_469
    calls = []

    def fake_update(progress=None, cancel=None):
        calls.append(1)
        yt.MANAGED_DIR.mkdir(parents=True, exist_ok=True)
        yt.managed_path().write_text(fake.read_text())
        yt.managed_path().chmod(0o755)
        (yt.MANAGED_DIR / "yt-dlp.version").write_text("2026.10.01\n")
        if progress:
            progress(1.0)
        return "2026.10.01", True

    yt.update_managed = fake_update
    try:
        results_cb = []
        win.get_ytdlp(results_cb.append, reason="Test. ")
        pump(0.5)
        dlg = win.get_visible_dialog()
        check("yt-dlp download asks first with size", dlg is not None and dlg.get_heading() == "Download yt-dlp?"
              and "3.1 MB" in dlg.get_body() and not calls and not yt.managed_path().exists(),
              dlg.get_body()[:80] if dlg else "no dialog")
        if dlg is None:
            return
        dlg.emit("response", "cancel")
        dlg.close()
        pump(0.2)
        check("declined: nothing downloaded", results_cb == [False] and not calls
              and not win.settings["ytdlp_managed"])
        win.get_ytdlp(results_cb.append, reason="Test. ")
        pump(0.3)
        dlg = win.get_visible_dialog()
        dlg.emit("response", "download")
        dlg.close()
        ok = wait_for(win, lambda: len(results_cb) == 2, 10)
        check("managed yt-dlp installed and preferred", ok and results_cb[1] and calls
              and win.settings["ytdlp_managed"] and yt.managed_enabled
              and yt.ytdlp_path("") == str(yt.managed_path()), str(yt.ytdlp_path("")))
        from astra_player import dialogs
        prefs = dialogs.PreferencesDialog(win)
        prefs.present()
        shown = wait_for(win, lambda: "\u00b7" in (prefs._ytdlp_info.get_subtitle() or ""), 10)
        check("Preferences shows yt-dlp in use", shown and prefs._ytdlp_row.get_active()
              and str(yt.managed_path()) in prefs._ytdlp_info.get_subtitle(),
              prefs._ytdlp_info.get_subtitle())
        prefs._ytdlp_row.set_active(False)
        check("switch off stops using it", not win.settings["ytdlp_managed"] and not yt.managed_enabled
              and yt.ytdlp_path("") == str(fake))
        prefs.dialog.close()
        pump(0.3)
    finally:
        yt.update_managed, yt.remote_size = saved
        yt.managed_enabled = False
        win.settings["ytdlp_managed"] = False


def whisper_checks(win):
    e = win.engine
    act = win.lookup_action("whisper-generate")
    check("whisper menu action", act is not None and act.get_enabled()
          and not win.lookup_action("whisper-cancel").get_enabled())

    # A missing model must open a confirmation dialog, never start a download.
    saved = whisper.find_backend, whisper.model_installed
    whisper.find_backend = lambda: ("python", sys.executable)
    whisper.model_installed = lambda _name: False
    try:
        win.generate_subtitles()
        pump(0.3)
        dlg = win.get_visible_dialog()
        check("model download asks first", dlg is not None and win._whisper_thread is None
              and "MB" in dlg.get_body(), dlg.get_body()[:60] if dlg else "no dialog")
        if dlg:
            dlg.close()
            pump(0.3)
    finally:
        whisper.find_backend, whisper.model_installed = saved

    model = next((n for n in whisper.MODELS if whisper.model_installed(n)), None)
    if not (whisper.find_backend() and model and SPEECH_WAV):
        print("[SKIP] whisper transcription (needs whisper-cli or pywhispercpp, "
              "a downloaded model and a speech sample)", flush=True)
        return
    folder = MEDIA / "speech"
    folder.mkdir()
    clip = folder / "talk.mkv"
    subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-i", SPEECH_WAV,
                         "-t", "20", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                         "-c:a", "aac", str(clip)], check=True)
    win.open_uris([path_to_uri(clip)])
    wait_for(win, lambda: e.playing and (e.position() or 0) > 0.2)
    win.settings["whisper_model"] = model
    win.settings["whisper_language"] = "auto"
    win.generate_subtitles()
    check("whisper job starts", win._whisper_thread is not None
          and win.lookup_action("whisper-cancel").get_enabled())
    srt = folder / "talk.whisper.srt"
    ok = wait_for(win, lambda: win._whisper_thread is None, 180)
    check("whisper writes .whisper.srt", ok and srt.is_file() and "rule" in srt.read_text().lower(),
          srt.read_text()[:80].replace("\n", " ") if srt.is_file() else "missing")
    check("whisper subtitle attached", wait_for(win, lambda: (win.playlist.current.suburi or "").endswith(
        "talk.whisper.srt") and e.playing and len(e.subtitle_tracks()) >= 1),
        str(e.subtitle_tracks()))


def main():
    make_media()
    app = AstraApp()
    app.exit_code = 1

    def on_activate(a):
        GLib.timeout_add(500, lambda: scenario(a) and False)

    app.connect("activate", on_activate)
    app.run([sys.argv[0], "--new-instance"][:1])
    sys.exit(app.exit_code)


if __name__ == "__main__":
    main()
