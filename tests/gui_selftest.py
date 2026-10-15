"""End-to-end smoke test: drives a real Kiln Player window.

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
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="kiln-cfg-"))

from gi.repository import GLib  # noqa: E402

from kiln_player.app import KilnApp  # noqa: E402
from kiln_player.playlist import path_to_uri  # noqa: E402
from kiln_player.shaders import SHADERS  # noqa: E402

MEDIA = Path(tempfile.mkdtemp(prefix="kiln-media-"))
FF = ["ffmpeg", "-v", "error", "-y"]


def make_media():
    subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                         "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
                         "-t", "90", "-map", "0:v", "-map", "1:a", "-map", "2:a",
                         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
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
                         "-metadata", "title=Test Tone", "-metadata", "artist=Kiln",
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

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed", flush=True)
    app.exit_code = 1 if failed else 0
    app.quit()


def main():
    make_media()
    app = KilnApp()
    app.exit_code = 1

    def on_activate(a):
        GLib.timeout_add(500, lambda: scenario(a) and False)

    app.connect("activate", on_activate)
    app.run([sys.argv[0], "--new-instance"][:1])
    sys.exit(app.exit_code)


if __name__ == "__main__":
    main()
