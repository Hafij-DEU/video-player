"""Main player window."""

import hashlib
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk

from . import dialogs, whisper
from .engine import FLIP_METHODS, Engine, discover
from .playlist import (MEDIA_EXT, PLAYLIST_EXT, Playlist, display_name, expand, ext_of,
                       find_subtitle, fmt_time, folder_media, media_filter, path_to_uri,
                       subtitle_filter, to_uri, uri_to_path, write_playlist_file)
from .shaders import SHADERS

SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0]
ASPECTS = [
    ("default", "Original"), ("stretch", "Stretch to window"), ("crop", "Fill window (crop)"),
    ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "21:9"), ("2.35:1", "2.35:1"),
    ("1:1", "1:1"), ("9:16", "9:16 (vertical)"),
]
COLOR_STEP = {"brightness": 0.05, "contrast": 0.05, "saturation": 0.05, "hue": 0.05}
COLOR_RANGE = {"brightness": (-1, 1), "contrast": (0, 2), "saturation": (0, 2), "hue": (-1, 1)}
COLOR_DEFAULT = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "hue": 0.0}
STREAM_EXT = MEDIA_EXT | PLAYLIST_EXT | {"mpd", "ism"}


def _needs_ytdlp(uri):
    if not uri.startswith(("http://", "https://")) or not shutil.which("yt-dlp"):
        return False
    tail = uri.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return ext_of(tail) not in STREAM_EXT


YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
# Separate video (up to 1080p, no AV1: few GPUs decode it) and audio over plain
# HTTPS. YouTube refuses its combined single-file formats (HTTP 403), and its
# HLS ladder mixes VP9 and H.264, which stalls GStreamer when it switches.
YOUTUBE_FORMAT = ("bv*[height<=1080][vcodec!^=av01][protocol=https]+ba[protocol=https]"
                  "/bv*[height<=1080][protocol=https]+ba[protocol=https]")


def _is_youtube(uri):
    host = urllib.parse.urlsplit(uri).hostname or ""
    return any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS)


def _resolve_ytdlp(uri):
    """Return (title, video_url, audio_url_or_None) for a web page URL.

    YouTube videos come as separate video and audio streams. Everything else
    (and YouTube live streams) prefers an HLS master playlist, then the best
    single file. Raises RuntimeError when yt-dlp fails.
    """
    if _is_youtube(uri):
        proc = subprocess.run(
            ["yt-dlp", "--no-playlist", "--no-warnings", "-f", YOUTUBE_FORMAT,
             "-O", "title", "-O", "urls", uri],
            capture_output=True, text=True, timeout=60)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        if proc.returncode == 0 and len(lines) >= 3:
            return lines[0], lines[1], lines[2]
    proc = subprocess.run(
        ["yt-dlp", "--no-playlist", "--no-warnings",
         "-f", "best*[protocol^=m3u8]/bv*[protocol^=m3u8]/best[vcodec!=none][acodec!=none]/best",
         "-O", "title", "-O", "%(manifest_url,url)s", uri],
        capture_output=True, text=True, timeout=60)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if proc.returncode != 0 or len(lines) < 2:
        raise RuntimeError((proc.stderr.strip().splitlines() or ["yt-dlp failed"])[-1])
    return lines[0], _single_codec_master(lines[1]), None


def _single_codec_master(url):
    """Keep one video codec in an HLS master playlist; return a URI to play.

    YouTube lists every quality in both VP9 and H.264. GStreamer's HLS demuxer
    switches between them as bandwidth changes, and the decoder cannot change
    codec mid-stream, so playback freezes. Keep the H.264 variants (decoded in
    hardware on most GPUs) or else the codec of the first variant, and write
    the filtered playlist to a local file. Anything else is returned unchanged.
    """
    if not url.startswith("https://") or "m3u8" not in url and "/manifest/hls" not in url:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read(2_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return url
    lines = text.splitlines()
    variants = [i for i, ln in enumerate(lines) if ln.startswith("#EXT-X-STREAM-INF")]
    families = []
    for i in variants:
        codecs = re.search(r'CODECS="([^"]*)"', lines[i])
        video = [c.split(".")[0] for c in (codecs.group(1) if codecs else "").split(",")
                 if not c.strip().startswith(("mp4a", "opus", "ac-3", "ec-3"))]
        families.append(video[0].strip() if video else "")
    if len(set(families)) < 2:
        return url
    keep = "avc1" if "avc1" in families else families[0]
    out, skip = [], set()
    for i, fam in zip(variants, families):
        if fam != keep:
            skip.update((i, i + 1))  # the tag and the URI line after it
    for i, ln in enumerate(lines):
        if i in skip:
            continue
        if ln and not ln.startswith("#"):
            ln = urllib.parse.urljoin(url, ln)  # local file: make relative URIs absolute
        elif 'URI="' in ln:
            ln = re.sub(r'URI="([^"]*)"', lambda m: f'URI="{urllib.parse.urljoin(url, m.group(1))}"', ln)
        out.append(ln)
    folder = Path(GLib.get_user_runtime_dir() or GLib.get_tmp_dir()) / "astra-player"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.m3u8"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path.as_uri()


class PlayerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Astra Player", default_width=1100, default_height=660)
        self.app = app
        self.settings = app.settings
        self.engine = Engine()
        self.playlist = Playlist()
        self.color = dict(COLOR_DEFAULT)
        self.ab = [None, None]
        self.aspect = "default"
        self.shader_name = "none"
        self._user_seek_until = 0.0
        self._osd_timeout = 0
        self._hide_timeout = 0
        self._click_timeout = 0
        self._inhibit_cookie = 0
        self._last_resume_save = 0.0
        self._loading_index = None
        self._eq_dialog = None
        self._color_dialog = None
        self._whisper_cancel = None
        self._whisper_thread = None

        self.engine.volume = self.settings["volume"]
        self.engine.mute = self.settings["muted"]
        self.engine.set_eq(self.settings["eq_bands"], self.settings["eq_enabled"])
        self.engine.set_subtitle_font(self.settings["subtitle_font"])
        for sig, cb in (("state-changed", self._on_state), ("eos", self._on_eos),
                        ("error", self._on_error), ("loaded", self._on_loaded),
                        ("tags-changed", self._on_tags), ("buffering", self._on_buffering)):
            self.engine.connect(sig, cb)

        self._build_menus()
        self._build_ui()
        self._install_actions()
        self._install_input()
        self._refresh_recent()
        self._set_aspect("default")
        GLib.timeout_add(200, self._tick)
        self.connect("close-request", self._on_close)
        self.connect("notify::fullscreened", self._on_fullscreen_changed)

    # =================================================================== UI

    def _build_ui(self):
        self.title_widget = Adw.WindowTitle(title="Astra Player", subtitle="")
        header = Adw.HeaderBar(title_widget=self.title_widget)
        open_btn = Adw.SplitButton(icon_name="document-open-symbolic", tooltip_text="Open files (Ctrl+O)",
                                   menu_model=self.open_menu)
        open_btn.set_action_name("win.open")
        header.pack_start(open_btn)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self.main_menu,
                                  tooltip_text="Menu", primary=True)
        header.pack_end(menu_btn)

        # Video area ---------------------------------------------------------
        self.picture = Gtk.Picture(paintable=self.engine.paintable, hexpand=True, vexpand=True,
                                   can_shrink=True)
        self.video_holder = Gtk.Box(hexpand=True, vexpand=True, css_classes=["video-holder"])
        self.aspect_frame = Gtk.AspectFrame(obey_child=False, hexpand=True, vexpand=True)

        idle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        idle.append(Gtk.Image(icon_name="io.github.hafij.AstraPlayer", pixel_size=128,
                              css_classes=["idle-logo"]))
        idle.append(Gtk.Label(label="Astra Player", css_classes=["idle-title"]))
        idle.append(Gtk.Label(label="Drop media here, or press Ctrl+O to open files",
                              css_classes=["idle-hint"]))

        audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.art = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                               width_request=260, height_request=260, css_classes=["album-art"])
        self.art_icon = Gtk.Image(icon_name="audio-x-generic-symbolic", pixel_size=160,
                                  css_classes=["idle-logo"])
        self.audio_title = Gtk.Label(css_classes=["idle-title"], wrap=True, justify=Gtk.Justification.CENTER)
        self.audio_sub = Gtk.Label(css_classes=["idle-hint"], wrap=True, justify=Gtk.Justification.CENTER)
        for w in (self.art, self.art_icon, self.audio_title, self.audio_sub):
            audio.append(w)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True, vexpand=True)
        self.stack.add_named(idle, "idle")
        self.stack.add_named(self.video_holder, "video")
        self.stack.add_named(audio, "audio")

        self.overlay = Gtk.Overlay(css_classes=["video-area"], hexpand=True, vexpand=True)
        self.overlay.set_child(self.stack)
        self.osd = Gtk.Label(css_classes=["osd"], halign=Gtk.Align.START, valign=Gtk.Align.START,
                             margin_start=18, margin_top=18, visible=False, wrap=True, xalign=0)
        self.overlay.add_overlay(self.osd)
        self.overlay.set_measure_overlay(self.osd, False)

        # Playlist panel -------------------------------------------------------
        self.listbox = Gtk.ListBox(css_classes=["playlist"], activate_on_single_click=False)
        self.listbox.connect("row-activated", lambda _lb, row: self.play_index(row.get_index()))
        scroller = Gtk.ScrolledWindow(child=self.listbox, vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.playlist_count = Gtk.Label(css_classes=["dim-label", "caption"], xalign=1, hexpand=True)
        phead = Gtk.Box(spacing=6, margin_start=10, margin_end=10, margin_top=8, margin_bottom=6)
        phead.append(Gtk.Label(label="Playlist", css_classes=["heading"], xalign=0))
        phead.append(self.playlist_count)
        ptools = Gtk.Box(spacing=2, margin_start=6, margin_end=6, margin_top=4, margin_bottom=6)
        for icon, tip, action in (
                ("list-add-symbolic", "Add files", "win.playlist-add"),
                ("folder-new-symbolic", "Add folder", "win.playlist-add-folder"),
                ("list-remove-symbolic", "Remove selected", "win.playlist-remove"),
                ("edit-clear-all-symbolic", "Clear", "win.playlist-clear"),
                ("view-sort-ascending-symbolic", "Sort by name", "win.playlist-sort"),
                ("document-save-symbolic", "Save playlist", "win.playlist-save")):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action,
                           css_classes=["flat"], focus_on_click=False)
            ptools.append(b)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=300,
                        css_classes=["playlist-panel"])
        panel.append(phead)
        panel.append(scroller)
        panel.append(ptools)
        # hexpand=False stops the label's hexpand inside the panel from propagating
        # up; otherwise the hidden panel takes half the spare width beside the video.
        self.playlist_revealer = Gtk.Revealer(child=panel, reveal_child=self.settings["show_playlist"],
                                              transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT,
                                              hexpand=False)

        main = Gtk.Box()
        main.append(self.overlay)
        main.append(self.playlist_revealer)

        # Controls -------------------------------------------------------------
        self.pos_label = Gtk.Label(label="00:00", css_classes=["time", "numeric"])
        self.dur_label = Gtk.Label(label="00:00", css_classes=["time", "numeric"])
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_hexpand(True)
        self.seek.set_draw_value(False)
        self.seek.set_focusable(False)
        self.seek.add_css_class("seekbar")
        self.seek.connect("change-value", self._on_seek_drag)
        self.seek.set_has_tooltip(True)
        self.seek.connect("query-tooltip", self._on_seek_tooltip)
        seek_row = Gtk.Box(spacing=8)
        seek_row.append(self.pos_label)
        seek_row.append(self.seek)
        seek_row.append(self.dur_label)

        def btn(icon, tip, action):
            return Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action,
                              css_classes=["flat", "ctl"], focus_on_click=False, focusable=False)

        self.play_btn = btn("media-playback-start-symbolic", "Play / pause (Space)", "win.toggle")
        self.play_btn.add_css_class("play")
        row = Gtk.Box(spacing=2)
        for w in (self.play_btn,
                  btn("media-playback-stop-symbolic", "Stop (F4)", "win.stop"),
                  btn("media-skip-backward-symbolic", "Previous (Page Up)", "win.previous"),
                  btn("media-skip-forward-symbolic", "Next (Page Down)", "win.next"),
                  btn("document-open-symbolic", "Open files (Ctrl+O)", "win.open")):
            row.append(w)
        self.info_label = Gtk.Label(css_classes=["badge-info"], hexpand=True, xalign=0.5)
        row.append(self.info_label)

        def menu_btn(icon, tip, model):
            return Gtk.MenuButton(icon_name=icon, tooltip_text=tip, menu_model=model,
                                  css_classes=["flat", "ctl"], focus_on_click=False,
                                  direction=Gtk.ArrowType.UP)

        row.append(menu_btn("media-view-subtitles-symbolic", "Subtitles", self.subtitle_menu))
        row.append(menu_btn("audio-x-generic-symbolic", "Audio", self.audio_menu))
        row.append(menu_btn("applications-graphics-symbolic", "Video & filters", self.video_menu))
        row.append(btn("view-list-symbolic", "Playlist (F6)", "win.show-playlist"))
        self.mute_btn = btn("audio-volume-high-symbolic", "Mute (M)", "win.mute")
        row.append(self.mute_btn)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
        self.volume.set_draw_value(False)
        self.volume.set_size_request(110, -1)
        self.volume.set_focusable(False)
        self.volume.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.volume.set_value(self.engine.volume * 100)
        self.volume.connect("value-changed", self._on_volume_scale)
        row.append(self.volume)
        self.vol_label = Gtk.Label(css_classes=["time", "numeric"], width_chars=4)
        row.append(self.vol_label)
        row.append(btn("view-fullscreen-symbolic", "Fullscreen (Enter)", "win.fullscreen"))

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["controls"])
        controls.append(seek_row)
        controls.append(row)

        self.toasts = Adw.ToastOverlay(child=main)
        self.view = Adw.ToolbarView(content=self.toasts)
        self.view.add_top_bar(header)
        self.view.add_bottom_bar(controls)
        self.view.set_bottom_bar_style(Adw.ToolbarStyle.RAISED_BORDER)
        self.set_content(self.view)
        self._update_volume_ui()
        self._refresh_playlist()

    # ================================================================ menus

    def _build_menus(self):
        def item(label, action, target=None):
            it = Gio.MenuItem.new(label, None)
            it.set_action_and_target_value(action, target)
            return it

        self.recent_menu = Gio.Menu()
        self.open_menu = Gio.Menu()
        self.open_menu.append("Open files…", "win.open")
        self.open_menu.append("Open folder…", "win.open-folder")
        self.open_menu.append("Open URL…", "win.open-url")
        self.open_menu.append("Play from clipboard", "win.paste")
        self.open_menu.append_submenu("Recent", self.recent_menu)

        speed = Gio.Menu()
        for s in SPEEDS:
            speed.append_item(item(f"{s:g}×", "win.speed", GLib.Variant.new_double(s)))
        loop = Gio.Menu()
        for key, label in (("none", "Play once"), ("one", "Repeat file"), ("playlist", "Repeat playlist")):
            loop.append_item(item(label, "win.loop", GLib.Variant.new_string(key)))
        ab = Gio.Menu()
        ab.append("Set A point", "win.ab-a")
        ab.append("Set B point", "win.ab-b")
        ab.append("Clear A-B repeat", "win.ab-clear")
        frames = Gio.Menu()
        frames.append("Next frame", "win.frame-next")
        frames.append("Previous frame", "win.frame-prev")
        self.chapter_menu = Gio.Menu()
        self.playback_menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append("Play / Pause", "win.toggle")
        sec.append("Stop", "win.stop")
        sec.append("Previous file", "win.previous")
        sec.append("Next file", "win.next")
        self.playback_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append_submenu("Speed", speed)
        sec.append_submenu("Repeat", loop)
        sec.append("Shuffle", "win.shuffle")
        sec.append_submenu("A-B repeat", ab)
        sec.append_submenu("Frame step", frames)
        sec.append_submenu("Chapters", self.chapter_menu)
        self.playback_menu.append_section(None, sec)

        self.audio_tracks = Gio.Menu()
        self.audio_menu = Gio.Menu()
        self.audio_menu.append_section("Audio track", self.audio_tracks)
        sec = Gio.Menu()
        sec.append("Equalizer…", "win.equalizer")
        sec.append("Visualization for music", "win.visualization")
        sec.append("Mute", "win.mute")
        self.audio_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Audio delay +50 ms", "win.audio-later")
        sec.append("Audio delay −50 ms", "win.audio-earlier")
        sec.append("Reset audio delay", "win.audio-reset")
        self.audio_menu.append_section(None, sec)

        self.sub_tracks = Gio.Menu()
        self.subtitle_menu = Gio.Menu()
        self.subtitle_menu.append_section("Subtitle track", self.sub_tracks)
        sec = Gio.Menu()
        sec.append("Load subtitle file…", "win.load-subtitle")
        sec.append("Show subtitles", "win.subs-visible")
        self.subtitle_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Generate subtitles (Whisper)…", "win.whisper-generate")
        sec.append("Cancel subtitle generation", "win.whisper-cancel")
        self.subtitle_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Delay +0.5 s (later)", "win.sub-later")
        sec.append("Delay −0.5 s (earlier)", "win.sub-earlier")
        sec.append("Reset delay", "win.sub-reset")
        self.subtitle_menu.append_section(None, sec)

        aspect = Gio.Menu()
        for key, label in ASPECTS:
            aspect.append_item(item(label, "win.aspect", GLib.Variant.new_string(key)))
        flip = Gio.Menu()
        for label, key in FLIP_METHODS:
            flip.append_item(item(label, "win.flip", GLib.Variant.new_string(key)))
        shaders = Gio.Menu()
        shaders.append_item(item("None", "win.shader", GLib.Variant.new_string("none")))
        for name in SHADERS:
            shaders.append_item(item(name, "win.shader", GLib.Variant.new_string(name)))
        self.video_menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append_submenu("Aspect ratio", aspect)
        sec.append_submenu("Rotate / flip", flip)
        sec.append_submenu("Pixel shaders", shaders)
        self.video_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Adjust colors…", "win.colors")
        sec.append("Reset colors", "win.colors-reset")
        sec.append("Save screenshot", "win.screenshot")
        self.video_menu.append_section(None, sec)

        self.main_menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append_submenu("Open", self.open_menu)
        sec.append_submenu("Playback", self.playback_menu)
        sec.append_submenu("Video", self.video_menu)
        sec.append_submenu("Audio", self.audio_menu)
        sec.append_submenu("Subtitles", self.subtitle_menu)
        self.main_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Playlist", "win.show-playlist")
        sec.append("Fullscreen", "win.fullscreen")
        sec.append("Media info", "win.media-info")
        self.main_menu.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Preferences", "win.preferences")
        sec.append("Keyboard shortcuts", "win.shortcuts")
        sec.append("About Astra Player", "app.about")
        sec.append("Quit", "app.quit")
        self.main_menu.append_section(None, sec)

    def _refresh_recent(self):
        self.recent_menu.remove_all()
        for uri in self.settings["recent"][:12]:
            it = Gio.MenuItem.new(display_name(uri), None)
            it.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(uri))
            self.recent_menu.append_item(it)
        if not self.settings["recent"]:
            self.recent_menu.append("(empty)", "win.noop")
        else:
            self.recent_menu.append("Clear recent", "win.clear-recent")

    def _refresh_tracks(self):
        self.audio_tracks.remove_all()
        for i, label in enumerate(self.engine.audio_tracks()):
            it = Gio.MenuItem.new(label, None)
            it.set_action_and_target_value("win.audio-track", GLib.Variant.new_int32(i))
            self.audio_tracks.append_item(it)
        self.sub_tracks.remove_all()
        it = Gio.MenuItem.new("Off", None)
        it.set_action_and_target_value("win.sub-track", GLib.Variant.new_int32(-1))
        self.sub_tracks.append_item(it)
        for i, label in enumerate(self.engine.subtitle_tracks()):
            it = Gio.MenuItem.new(label, None)
            it.set_action_and_target_value("win.sub-track", GLib.Variant.new_int32(i))
            self.sub_tracks.append_item(it)
        self.lookup_action("audio-track").set_state(GLib.Variant.new_int32(self.engine.current_audio))
        cur = self.engine.current_subtitle if self.engine.subtitles_visible else -1
        self.lookup_action("sub-track").set_state(GLib.Variant.new_int32(cur))

        self.chapter_menu.remove_all()
        for start, title in self.engine.chapters:
            it = Gio.MenuItem.new(f"{fmt_time(start)}  {title}", None)
            it.set_action_and_target_value("win.chapter", GLib.Variant.new_double(start))
            self.chapter_menu.append_item(it)
        if not self.engine.chapters:
            self.chapter_menu.append("(none)", "win.noop")
        self._update_marks()

    # ============================================================== actions

    def _install_actions(self):
        def add(name, cb, param=None, state=None):
            if state is not None:
                act = Gio.SimpleAction.new_stateful(name, GLib.VariantType(param) if param else None, state)
            else:
                act = Gio.SimpleAction.new(name, GLib.VariantType(param) if param else None)
            act.connect("activate" if state is None or param else "change-state", cb)
            self.add_action(act)
            return act

        def simple(fn):
            return lambda _a, _p: fn()

        add("noop", simple(lambda: None)).set_enabled(False)
        add("open", simple(self.open_files_dialog))
        add("open-folder", simple(self.open_folder_dialog))
        add("open-url", simple(lambda: dialogs.ask_url(self, lambda t: self.open_uris([to_uri(t)]))))
        add("paste", simple(self.play_clipboard))
        add("open-recent", lambda _a, p: self.open_uris([p.get_string()]), "s")
        add("clear-recent", simple(self._clear_recent))
        add("toggle", simple(self.engine.toggle))
        add("stop", simple(self.stop))
        add("previous", simple(lambda: self.step_playlist(-1)))
        add("next", simple(lambda: self.step_playlist(1)))
        add("speed", self._act_speed, "d", GLib.Variant.new_double(1.0))
        add("loop", self._act_loop, "s", GLib.Variant.new_string(self.settings["loop_mode"]))
        add("shuffle", self._act_bool("shuffle", self._set_shuffle), state=GLib.Variant.new_boolean(self.settings["shuffle"]))
        add("ab-a", simple(lambda: self.set_ab(0)))
        add("ab-b", simple(lambda: self.set_ab(1)))
        add("ab-clear", simple(self.clear_ab))
        add("frame-next", simple(lambda: self.engine.frame_step(True)))
        add("frame-prev", simple(lambda: self.engine.frame_step(False)))
        add("chapter", lambda _a, p: self.engine.seek(p.get_double()), "d")
        add("audio-track", self._act_audio_track, "i", GLib.Variant.new_int32(0))
        add("sub-track", self._act_sub_track, "i", GLib.Variant.new_int32(0))
        add("equalizer", simple(self.show_equalizer))
        add("visualization", self._act_bool("visualization", self._set_visualization), state=GLib.Variant.new_boolean(False))
        add("mute", simple(self.toggle_mute))
        add("audio-later", simple(lambda: self.shift_audio(0.05)))
        add("audio-earlier", simple(lambda: self.shift_audio(-0.05)))
        add("audio-reset", simple(lambda: self.shift_audio(None)))
        add("load-subtitle", simple(self.load_subtitle_dialog))
        add("subs-visible", self._act_bool("subs-visible", self._set_subs_visible), state=GLib.Variant.new_boolean(True))
        add("whisper-generate", simple(self.generate_subtitles))
        add("whisper-cancel", simple(self.cancel_whisper)).set_enabled(False)
        add("sub-later", simple(lambda: self.shift_subs(0.5)))
        add("sub-earlier", simple(lambda: self.shift_subs(-0.5)))
        add("sub-reset", simple(lambda: self.shift_subs(None)))
        add("aspect", lambda a, p: self._set_aspect(p.get_string()), "s", GLib.Variant.new_string("default"))
        add("flip", self._act_flip, "s", GLib.Variant.new_string("automatic"))
        add("shader", self._act_shader, "s", GLib.Variant.new_string("none"))
        add("colors", simple(self.show_colors))
        add("colors-reset", simple(self.reset_color))
        add("screenshot", simple(self.screenshot))
        add("show-playlist", self._act_bool("show-playlist", self._set_playlist_visible),
            state=GLib.Variant.new_boolean(self.settings["show_playlist"]))
        add("fullscreen", simple(self.toggle_fullscreen))
        add("media-info", simple(self.show_media_info))
        add("preferences", simple(lambda: dialogs.PreferencesDialog(self).present()))
        add("shortcuts", simple(lambda: dialogs.show_shortcuts(self)))
        add("playlist-add", simple(lambda: self.open_files_dialog(append=True)))
        add("playlist-add-folder", simple(lambda: self.open_folder_dialog(append=True)))
        add("playlist-remove", simple(self._playlist_remove_selected))
        add("playlist-clear", simple(self._playlist_clear))
        add("playlist-sort", simple(self._playlist_sort))
        add("playlist-save", simple(self._playlist_save))

    def _act_bool(self, name, setter):
        def change(action, value):
            action.set_state(value)
            setter(value.get_boolean())
        return change

    def _act_speed(self, action, param):
        self.set_speed(param.get_double())

    def _act_loop(self, action, param):
        action.set_state(param)
        self.settings["loop_mode"] = param.get_string()
        labels = {"none": "Play once", "one": "Repeat file", "playlist": "Repeat playlist"}
        self.show_osd(labels[param.get_string()])

    def _act_audio_track(self, action, param):
        idx = param.get_int32()
        self.engine.current_audio = idx
        action.set_state(param)
        tracks = self.engine.audio_tracks()
        if idx < len(tracks):
            self.show_osd(f"Audio: {tracks[idx]}")

    def _act_sub_track(self, action, param):
        idx = param.get_int32()
        action.set_state(param)
        if idx < 0:
            self._set_subs_visible(False)
            self.lookup_action("subs-visible").set_state(GLib.Variant.new_boolean(False))
            return
        self.engine.current_subtitle = idx
        self._set_subs_visible(True, osd=False)
        self.lookup_action("subs-visible").set_state(GLib.Variant.new_boolean(True))
        tracks = self.engine.subtitle_tracks()
        if idx < len(tracks):
            self.show_osd(f"Subtitle: {tracks[idx]}")

    def _act_flip(self, action, param):
        action.set_state(param)
        self.engine.set_flip(param.get_string())
        self.show_osd(dict((k, label) for label, k in FLIP_METHODS)[param.get_string()])

    def _act_shader(self, action, param):
        name = param.get_string()
        if not self.engine.set_shader(SHADERS.get(name)):
            self.toast("Pixel shaders need OpenGL, which is not available here")
            return
        action.set_state(param)
        self.shader_name = name
        self.show_osd(f"Shader: {'off' if name == 'none' else name}")

    # ================================================================ input

    def _install_input(self):
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_video_click)
        self.overlay.add_controller(click)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.overlay.add_controller(scroll)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        drop = Gtk.DropTarget(actions=Gdk.DragAction.COPY)
        drop.set_gtypes([Gdk.FileList, str])
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self.context_menu = Gtk.PopoverMenu.new_from_model(self.main_menu)
        self.context_menu.set_has_arrow(False)
        self.context_menu.set_halign(Gtk.Align.START)
        self.context_menu.set_parent(self.overlay)

        for accel, action in (("<Ctrl>o", "win.open"), ("<Ctrl>f", "win.open-folder"),
                              ("<Ctrl>u", "win.open-url"), ("<Ctrl>v", "win.paste"),
                              ("<Ctrl>e", "win.screenshot"), ("<Ctrl>F1", "win.media-info"),
                              ("F5", "win.preferences"), ("F1", "win.shortcuts"),
                              ("<Ctrl><Shift>s", "win.load-subtitle"), ("<Ctrl>q", "app.quit"),
                              ("<Ctrl>w", "win.stop"), ("F4", "win.stop")):
            self.app.set_accels_for_action(action, [accel])

    def _on_key(self, ctrl, keyval, keycode, state):
        if self.get_visible_dialog() is not None:
            return False
        focus = self.get_focus()
        if isinstance(focus, (Gtk.Text, Gtk.Entry, Gtk.TextView)):
            return False
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK)
        ctrl_on = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        shift_on = bool(mods & Gdk.ModifierType.SHIFT_MASK)
        alt_on = bool(mods & Gdk.ModifierType.ALT_MASK)
        name = (Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or "").lower()
        s = self.settings
        e = self.engine

        if alt_on and not ctrl_on:
            table = {"h": self._toggle_subs, "l": lambda: self._cycle("sub"), "a": lambda: self._cycle("audio")}
        elif ctrl_on and not alt_on:
            table = {
                "left": lambda: self.seek_by(-s["seek_long"]), "right": lambda: self.seek_by(s["seek_long"]),
                "page_up": lambda: self.step_chapter(-1), "page_down": lambda: self.step_chapter(1),
                "equal": lambda: self.shift_audio(0.05), "plus": lambda: self.shift_audio(0.05),
                "kp_add": lambda: self.shift_audio(0.05), "minus": lambda: self.shift_audio(-0.05),
                "kp_subtract": lambda: self.shift_audio(-0.05),
            }
        elif shift_on and not alt_on:
            table = {"left": lambda: self.seek_by(-60), "right": lambda: self.seek_by(60),
                     "less": lambda: self.shift_subs(-0.5), "greater": lambda: self.shift_subs(0.5)}
        else:
            table = {
                "space": e.toggle, "return": self.toggle_fullscreen, "kp_enter": self.toggle_fullscreen,
                "escape": self._leave_fullscreen, "f6": self._toggle_playlist,
                "left": lambda: self.seek_by(-s["seek_short"]), "right": lambda: self.seek_by(s["seek_short"]),
                "up": lambda: self.change_volume(0.05), "down": lambda: self.change_volume(-0.05),
                "m": self.toggle_mute, "home": lambda: e.seek(0),
                "page_up": lambda: self.step_playlist(-1), "page_down": lambda: self.step_playlist(1),
                "f": lambda: e.frame_step(True), "d": lambda: e.frame_step(False),
                "c": lambda: self.set_speed(e.rate + 0.1), "x": lambda: self.set_speed(e.rate - 0.1),
                "z": lambda: self.set_speed(1.0),
                "bracketleft": lambda: self.set_ab(0), "bracketright": lambda: self.set_ab(1),
                "backslash": self.clear_ab,
                "comma": lambda: self.shift_subs(-0.5), "period": lambda: self.shift_subs(0.5),
                "slash": lambda: self.shift_subs(None),
                "q": self.reset_color,
                "w": lambda: self.nudge_color("brightness", -1), "e": lambda: self.nudge_color("brightness", 1),
                "r": lambda: self.nudge_color("contrast", -1), "t": lambda: self.nudge_color("contrast", 1),
                "y": lambda: self.nudge_color("saturation", -1), "u": lambda: self.nudge_color("saturation", 1),
                "i": lambda: self.nudge_color("hue", -1), "o": lambda: self.nudge_color("hue", 1),
                "tab": self.show_status, "f11": self.toggle_fullscreen,
                "audioplay": e.toggle, "audiopause": e.pause, "audiostop": self.stop,
                "audionext": lambda: self.step_playlist(1), "audioprev": lambda: self.step_playlist(-1),
            }
        fn = table.get(name)
        if fn is None:
            return False
        fn()
        return True

    def _on_video_click(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        if button == 3:
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
            self.context_menu.set_pointing_to(rect)
            self.context_menu.popup()
        elif button == 2:
            self.engine.toggle()
        elif button == 1:
            if n_press == 2:
                if self._click_timeout:
                    GLib.source_remove(self._click_timeout)
                    self._click_timeout = 0
                self.toggle_fullscreen()
            elif n_press == 1 and self.engine.uri:
                def single():
                    self._click_timeout = 0
                    self.engine.toggle()
                    return False
                if self._click_timeout:
                    GLib.source_remove(self._click_timeout)
                self._click_timeout = GLib.timeout_add(260, single)
            elif n_press == 1:
                self.open_files_dialog()

    def _on_scroll(self, ctrl, dx, dy):
        self.change_volume(-0.05 if dy > 0 else 0.05)
        return True

    def _on_motion(self, ctrl, x, y):
        if getattr(self, "_last_motion", None) == (int(x), int(y)):
            return
        self._last_motion = (int(x), int(y))
        if not self.is_fullscreen():
            return
        self.view.set_reveal_top_bars(True)
        self.view.set_reveal_bottom_bars(True)
        self.set_cursor(None)
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
        self._hide_timeout = GLib.timeout_add(2500, self._autohide)

    def _autohide(self):
        self._hide_timeout = 0
        if self.is_fullscreen() and self.engine.playing:
            self.view.set_reveal_top_bars(False)
            self.view.set_reveal_bottom_bars(False)
            self.set_cursor(Gdk.Cursor.new_from_name("none", None))
        return False

    def _on_drop(self, target, value, x, y):
        if isinstance(value, Gdk.FileList):
            uris = [f.get_uri() for f in value.get_files()]
        else:
            uris = [to_uri(line) for line in str(value).splitlines() if line.strip()]
        if not uris:
            return False
        subs = [u for u in uris if ext_of(u) in ("srt", "ass", "ssa", "vtt", "sub", "smi")]
        if subs and len(subs) == len(uris) and self.engine.uri:
            self.attach_subtitle(subs[0])
        else:
            self.open_uris(uris)
        return True

    # ============================================================== opening

    def open_files_dialog(self, append=False):
        filters, default = media_filter()
        fd = Gtk.FileDialog(title="Add to playlist" if append else "Open media", filters=filters,
                            default_filter=default)
        fd.set_initial_folder(Gio.File.new_for_path(self.settings["last_dir"]))

        def done(d, res):
            try:
                files = d.open_multiple_finish(res)
            except GLib.Error:
                return
            uris = [files.get_item(i).get_uri() for i in range(files.get_n_items())]
            if uris:
                parent = Gio.File.new_for_uri(uris[0]).get_parent()
                if parent and parent.get_path():
                    self.settings["last_dir"] = parent.get_path()
                self.open_uris(uris, append=append, expand_folder=len(uris) == 1 and not append)

        fd.open_multiple(self, None, done)

    def open_folder_dialog(self, append=False):
        fd = Gtk.FileDialog(title="Open folder")
        fd.set_initial_folder(Gio.File.new_for_path(self.settings["last_dir"]))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self.settings["last_dir"] = folder.get_path() or self.settings["last_dir"]
            self.open_uris([folder.get_uri()], append=append, expand_folder=False)

        fd.select_folder(self, None, done)

    def play_clipboard(self):
        def got(cb, res):
            try:
                text = cb.read_text_finish(res)
            except GLib.Error:
                text = None
            if text and text.strip():
                self.open_uris([to_uri(text.strip().splitlines()[0])])
            else:
                self.toast("Clipboard has no path or URL")

        self.get_clipboard().read_text_async(None, got)

    def open_uris(self, uris, append=False, expand_folder=True):
        uris = expand(uris)
        if not uris:
            self.toast("No playable media found")
            return
        if append:
            first = self.playlist.add(uris)
            self._refresh_playlist()
            if self.playlist.index < 0:
                self.play_index(first)
            return
        self._save_resume()
        self.playlist.clear()
        start_uri = uris[0]
        path = uri_to_path(start_uri)
        if (expand_folder and len(uris) == 1 and path is not None and self.settings["auto_add_folder"]
                and ext_of(path) in MEDIA_EXT):
            siblings = folder_media(path.parent)
            if start_uri in siblings:
                uris = siblings
        self.playlist.add(uris)
        self._refresh_playlist()
        self.play_index([e.uri for e in self.playlist.entries].index(start_uri))

    def play_index(self, idx):
        if idx is None or not 0 <= idx < len(self.playlist):
            return
        self._save_resume()
        self.clear_ab(osd=False)
        self.playlist.index = idx
        entry = self.playlist.current
        self.settings.add_recent(entry.uri)
        self._refresh_recent()
        self._refresh_playlist()
        self.title_widget.set_title(entry.title)
        self.title_widget.set_subtitle(f"{idx + 1} / {len(self.playlist)}")
        self.set_title(f"{entry.title} - Astra Player")
        self.audio_title.set_label(entry.title)
        self.audio_sub.set_label("")
        self.engine.subtitle_delay = 0
        if entry.suburi is None and self.settings["auto_load_subtitles"]:
            entry.suburi = find_subtitle(entry.uri)
        start = 0.0
        if self.settings["resume_playback"]:
            start = self.settings.get_resume(entry.uri) or 0.0
        self._resumed_at = start

        if _needs_ytdlp(entry.uri):
            self.show_osd("Resolving link…", 30000)
            self._loading_index = idx

            def worker():
                try:
                    title, direct, audio = _resolve_ytdlp(entry.uri)
                    err = None
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                    title, direct, audio, err = None, entry.uri, None, str(exc)
                GLib.idle_add(finish, title, direct, audio, err)

            def finish(title, direct, audio, err):
                if self._loading_index != idx:
                    return False
                if title:
                    entry.title = title
                    self.title_widget.set_title(title)
                    self._refresh_playlist()
                if err:
                    self.toast(f"yt-dlp: {err}")
                if audio:
                    self.engine.load(direct, audio, start, external_audio=True)
                else:
                    self.engine.load(direct, entry.suburi, start)
                return False

            threading.Thread(target=worker, daemon=True).start()
        else:
            self._loading_index = idx
            self.engine.load(entry.uri, entry.suburi, start)

    def step_playlist(self, step):
        idx = self.playlist.neighbor(step, "playlist", self.settings["shuffle"])
        if idx is not None:
            self.play_index(idx)

    def stop(self):
        self._save_resume()
        self.engine.stop()
        self.stack.set_visible_child_name("idle")
        self.pos_label.set_label("00:00")
        self.seek.set_value(0)
        self.show_osd("Stopped")

    def attach_subtitle(self, suburi):
        entry = self.playlist.current
        if entry is None:
            return
        if self.engine.external_audio:
            self.toast("Subtitle files cannot be added to this online video")
            return
        entry.suburi = suburi
        self.engine.reload(suburi)
        self.show_osd(f"Subtitle: {display_name(suburi)}")

    def load_subtitle_dialog(self):
        if not self.engine.uri:
            self.toast("Open a video first")
            return
        filters, default = subtitle_filter()
        fd = Gtk.FileDialog(title="Load subtitle", filters=filters, default_filter=default)
        path = uri_to_path(self.engine.uri)
        if path:
            fd.set_initial_folder(Gio.File.new_for_path(str(path.parent)))

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            self.attach_subtitle(f.get_uri())

        fd.open(self, None, done)

    # ------------------------------------------------- speech to subtitles

    def generate_subtitles(self):
        """Subtitles > Generate subtitles (Whisper): transcribe the current file offline."""
        if self._whisper_thread is not None:
            self.toast("Subtitles are already being generated")
            return
        uri = self.engine.uri
        path = uri_to_path(uri) if uri else None
        if path is None or not path.is_file():
            self.toast("Open a local video or audio file first")
            return
        backend = whisper.find_backend()
        if backend is None:
            dialogs.whisper_missing(self)
            return
        name = self.settings["whisper_model"]
        if name not in whisper.MODELS:
            name = self.settings["whisper_model"] = "base"
        if not whisper.model_installed(name):
            # Never fetch anything unasked: the dialog shows what and how big.
            dialogs.confirm_model_download(self, name, lambda: self._download_model(name))
            return
        tracks = len(self.engine.audio_tracks())
        track = min(max(self.engine.current_audio, 0), max(tracks - 1, 0))
        out = whisper.output_path(path)
        opts = dict(model=whisper.model_path(name), language=self.settings["whisper_language"],
                    translate=self.settings["whisper_translate"], gpu=self.settings["whisper_gpu"],
                    track=track, duration=self.engine.duration(), backend=backend)
        stages = {"extract": "Extracting audio", "transcribe": f"Transcribing ({name} model)"}

        def work(progress, cancel):
            whisper.generate(uri, out, progress=lambda st, f: progress(stages[st], f), cancel=cancel, **opts)
            return out

        def finished(result):
            if self.engine.uri == uri:
                self.attach_subtitle(path_to_uri(result))
                self._set_subs_visible(True, osd=False)
                self.lookup_action("subs-visible").set_state(GLib.Variant.new_boolean(True))
            self.toast(f"Subtitles saved as {result.name}" if result.parent == path.parent
                       else f"Subtitles saved to {result}")

        self._run_whisper_task(work, finished, "Subtitle generation")

    def _download_model(self, name):
        size = whisper.fmt_size(whisper.MODELS[name][0])

        def work(progress, cancel):
            whisper.download_model(name, lambda f: progress(f"Downloading {name} model ({size})", f), cancel)

        def finished(_result):
            self.show_osd(f"Whisper {name} model ready")
            self.generate_subtitles()

        self._run_whisper_task(work, finished, "Model download")

    def _run_whisper_task(self, work, finished, what):
        """Run ``work(progress, cancel)`` in a thread, showing progress in the OSD."""
        cancel = threading.Event()
        self._whisper_cancel = cancel
        self.lookup_action("whisper-cancel").set_enabled(True)
        last = [None]

        def progress(label, fraction):
            text = f"{label}… {int(fraction * 100)}%"
            if text != last[0]:
                last[0] = text
                GLib.idle_add(lambda: self.show_osd(text, 6000) if not cancel.is_set() else None)

        def done(result, error):
            self._whisper_thread = None
            self._whisper_cancel = None
            self.lookup_action("whisper-cancel").set_enabled(False)
            if isinstance(error, whisper.Cancelled) or cancel.is_set():
                self.show_osd(f"{what} cancelled")
            elif error is not None:
                self.show_osd(f"{what} failed", 3000)
                self.toast(f"{what} failed: {error}")
            else:
                finished(result)
            return False

        def run():
            try:
                result, error = work(progress, cancel), None
            except Exception as exc:  # reported to the user, never fatal
                result, error = None, exc
            GLib.idle_add(done, result, error)

        self._whisper_thread = threading.Thread(target=run, daemon=True)
        self._whisper_thread.start()

    def cancel_whisper(self):
        if self._whisper_cancel is not None:
            self._whisper_cancel.set()
            self.show_osd("Cancelling…")

    def _clear_recent(self):
        self.settings["recent"] = []
        self._refresh_recent()

    # ============================================================ playlist UI

    def _refresh_playlist(self):
        self.listbox.remove_all()
        for i, entry in enumerate(self.playlist.entries):
            row = Gtk.Box(spacing=8, margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)
            row.append(Gtk.Label(label=f"{i + 1}.", css_classes=["dim-label", "numeric"], width_chars=3, xalign=1))
            label = Gtk.Label(label=entry.title, xalign=0, hexpand=True, ellipsize=3,
                              tooltip_text=entry.uri)
            row.append(label)
            lbrow = Gtk.ListBoxRow(child=row)
            if i == self.playlist.index:
                lbrow.add_css_class("current")
            self.listbox.append(lbrow)
        n = len(self.playlist)
        self.playlist_count.set_label(f"{n} item{'s' if n != 1 else ''}")

    def _playlist_remove_selected(self):
        row = self.listbox.get_selected_row()
        if row is None:
            return
        idx = row.get_index()
        playing = idx == self.playlist.index
        self.playlist.remove(idx)
        if playing:
            self.stop()
            self.playlist.index = -1
        self._refresh_playlist()

    def _playlist_clear(self):
        self.stop()
        self.playlist.clear()
        self._refresh_playlist()
        self.title_widget.set_title("Astra Player")
        self.title_widget.set_subtitle("")

    def _playlist_sort(self):
        self.playlist.sort()
        self._refresh_playlist()

    def _playlist_save(self):
        if not len(self.playlist):
            return
        fd = Gtk.FileDialog(title="Save playlist", initial_name="playlist.m3u8")
        fd.set_initial_folder(Gio.File.new_for_path(self.settings["last_dir"]))

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            write_playlist_file(f.get_path(), self.playlist.entries)
            self.toast(f"Saved {f.get_basename()}")

        fd.save(self, None, done)

    def _set_playlist_visible(self, visible):
        self.playlist_revealer.set_reveal_child(visible)
        self.settings["show_playlist"] = visible

    def _toggle_playlist(self):
        self.activate_action("win.show-playlist", None)

    # ======================================================= engine callbacks

    def _on_state(self, engine, playing):
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")
        if playing and not self._inhibit_cookie:
            self._inhibit_cookie = self.app.inhibit(
                self, Gtk.ApplicationInhibitFlags.IDLE | Gtk.ApplicationInhibitFlags.SUSPEND, "Playing media")
        elif not playing and self._inhibit_cookie:
            self.app.uninhibit(self._inhibit_cookie)
            self._inhibit_cookie = 0
        if not playing and self.is_fullscreen():
            self.view.set_reveal_top_bars(True)
            self.view.set_reveal_bottom_bars(True)
            self.set_cursor(None)
        self.app.emit_player_changed()

    def _on_loaded(self, engine):
        dur = engine.duration()
        self.seek.set_range(0, dur if dur else 1)
        self.dur_label.set_label(fmt_time(dur))
        self._show_media_page()
        self._refresh_tracks()
        if self._resumed_at and self._resumed_at > 1:
            self.show_osd(f"Resumed at {fmt_time(self._resumed_at)}  (Home to restart)")
        self._resumed_at = 0
        self.app.emit_player_changed()

    def _show_media_page(self):
        if self.engine.has_video() or self.lookup_action("visualization").get_state().get_boolean():
            self.stack.set_visible_child_name("video")
        else:
            self.stack.set_visible_child_name("audio")

    def _on_tags(self, engine):
        tags = engine.tags
        title = tags.get("title")
        artist = tags.get("artist")
        if title:
            self.audio_title.set_label(title)
        sub = " — ".join(x for x in (artist, tags.get("album")) if x)
        self.audio_sub.set_label(sub)
        img = tags.get("image")
        if img:
            try:
                tex = Gdk.Texture.new_from_bytes(GLib.Bytes.new(img))
                self.art.set_paintable(tex)
                self.art.set_visible(True)
                self.art_icon.set_visible(False)
            except GLib.Error:
                pass
        else:
            self.art.set_visible(False)
            self.art_icon.set_visible(True)
        self.app.emit_player_changed()

    def _on_eos(self, engine):
        entry = self.playlist.current
        if entry:
            self.settings.set_resume(entry.uri, None)
        mode = self.settings["loop_mode"]
        if mode == "one":
            engine.seek(0)
            engine.play()
            return
        idx = self.playlist.neighbor(1, mode, self.settings["shuffle"])
        if idx is None:
            self.stop()
            self.show_osd("End of playlist")
        else:
            self.play_index(idx)

    def _on_error(self, engine, message):
        self.toast(message)
        self.show_osd(message, 4000)
        if len(self.playlist) > 1 and self.playlist.index < len(self.playlist) - 1:
            GLib.timeout_add(1500, lambda: self.step_playlist(1) and False)

    def _on_buffering(self, engine, pct):
        if pct < 100:
            self.show_osd(f"Buffering {pct}%", 1500)

    # ================================================================ timer

    def _tick(self):
        e = self.engine
        if e.uri:
            pos = e.position()
            dur = e.duration()
            if dur:
                lo, hi = self.seek.get_adjustment().get_lower(), self.seek.get_adjustment().get_upper()
                if abs(hi - dur) > 0.5:
                    self.seek.set_range(0, dur)
                    self.dur_label.set_label(fmt_time(dur))
            if pos is not None and time.monotonic() > self._user_seek_until:
                self.seek.set_value(pos)
                self.pos_label.set_label(fmt_time(pos))
            a, b = self.ab
            if a is not None and b is not None and pos is not None and pos >= b and e.playing:
                e.seek(a)
            if time.monotonic() - self._last_resume_save > 15:
                self._last_resume_save = time.monotonic()
                self._save_resume(write=True)
        return True

    def _on_seek_drag(self, scale, scroll, value):
        if not self.engine.uri:
            return True
        self._user_seek_until = time.monotonic() + 0.4
        self.pos_label.set_label(fmt_time(value))
        self.engine.seek(value, accurate=False)
        return False

    def _on_seek_tooltip(self, widget, x, y, keyboard, tooltip):
        dur = self.engine.duration()
        if not dur:
            return False
        width = widget.get_width()
        frac = min(max((x - 8) / max(width - 16, 1), 0), 1)
        t = frac * dur
        label = fmt_time(t)
        for start, title in reversed(self.engine.chapters):
            if start <= t:
                label += f"  ·  {title}"
                break
        tooltip.set_text(label)
        return True

    # ============================================================ operations

    def seek_by(self, delta):
        if not self.engine.uri:
            return
        self.engine.seek_relative(delta)
        pos = (self.engine.position() or 0) + delta
        sign = "+" if delta > 0 else "−"
        self.show_osd(f"{sign}{abs(delta)} s   {fmt_time(pos)} / {fmt_time(self.engine.duration())}")

    def set_speed(self, rate):
        rate = round(max(0.1, min(rate, 8.0)), 2)
        rate = self.engine.set_rate(rate)
        self.lookup_action("speed").set_state(GLib.Variant.new_double(rate))
        self.show_osd(f"Speed {rate:g}×")
        self._update_info()

    def change_volume(self, delta):
        self.engine.volume = round(self.engine.volume + delta, 2)
        if self.engine.mute and delta > 0:
            self.engine.mute = False
        self._update_volume_ui()
        self.show_osd(f"Volume {round(self.engine.volume * 100)}%")

    def toggle_mute(self):
        self.engine.mute = not self.engine.mute
        self._update_volume_ui()
        self.show_osd("Mute on" if self.engine.mute else "Mute off")

    def _on_volume_scale(self, scale):
        v = scale.get_value() / 100
        if abs(v - self.engine.volume) > 0.004:
            self.engine.volume = v
            self._update_volume_ui()

    def _update_volume_ui(self):
        v = self.engine.volume
        muted = self.engine.mute
        if abs(self.volume.get_value() - v * 100) > 0.4:
            self.volume.set_value(v * 100)
        self.vol_label.set_label(f"{round(v * 100)}%")
        if muted or v == 0:
            icon = "audio-volume-muted-symbolic"
        elif v < 0.34:
            icon = "audio-volume-low-symbolic"
        elif v < 0.67:
            icon = "audio-volume-medium-symbolic"
        else:
            icon = "audio-volume-high-symbolic"
        self.mute_btn.set_icon_name(icon)
        self.settings["volume"] = v
        self.settings["muted"] = muted
        self.app.emit_player_changed()

    def set_ab(self, which):
        pos = self.engine.position()
        if pos is None:
            return
        self.ab[which] = pos
        a, b = self.ab
        if a is not None and b is not None and b <= a:
            self.ab = [b, a] if which == 0 else [a, None]
        self.show_osd(f"A-B repeat: A={fmt_time(self.ab[0])}  B={fmt_time(self.ab[1])}")
        self._update_marks()
        self._update_info()

    def clear_ab(self, osd=True):
        self.ab = [None, None]
        self._update_marks()
        self._update_info()
        if osd:
            self.show_osd("A-B repeat cleared")

    def _update_marks(self):
        self.seek.clear_marks()
        for start, _title in self.engine.chapters:
            if start > 0:
                self.seek.add_mark(start, Gtk.PositionType.TOP, None)
        for label, val in zip("AB", self.ab):
            if val is not None:
                self.seek.add_mark(val, Gtk.PositionType.BOTTOM, label)

    def _update_info(self):
        bits = []
        if abs(self.engine.rate - 1.0) > 0.001:
            bits.append(f"{self.engine.rate:g}×")
        if self.ab[0] is not None:
            bits.append("A-B" if self.ab[1] is not None else "A-")
        if self.shader_name != "none":
            bits.append(self.shader_name)
        self.info_label.set_label("   ".join(bits))

    def step_chapter(self, step):
        chapters = self.engine.chapters
        pos = self.engine.position()
        if not chapters or pos is None:
            self.step_playlist(step)
            return
        if step > 0:
            nxt = [c for c in chapters if c[0] > pos + 1]
        else:
            nxt = [c for c in chapters if c[0] < pos - 3][-1:]
        if nxt:
            start, title = nxt[0]
            self.engine.seek(start)
            self.show_osd(title)
        elif step < 0:
            self.engine.seek(0)

    def _cycle(self, kind):
        if kind == "audio":
            n = len(self.engine.audio_tracks())
            if n > 1:
                self.activate_action("win.audio-track", GLib.Variant.new_int32((self.engine.current_audio + 1) % n))
        else:
            n = len(self.engine.subtitle_tracks())
            if n == 0:
                self.show_osd("No subtitles")
                return
            cur = self.engine.current_subtitle if self.engine.subtitles_visible else -1
            nxt = cur + 1 if cur + 1 < n else -1
            self.activate_action("win.sub-track", GLib.Variant.new_int32(nxt))
            if nxt < 0:
                self.show_osd("Subtitles off")

    def _toggle_subs(self):
        visible = not self.engine.subtitles_visible
        self.lookup_action("subs-visible").set_state(GLib.Variant.new_boolean(visible))
        self._set_subs_visible(visible)

    def _set_subs_visible(self, visible, osd=True):
        self.engine.subtitles_visible = visible
        if osd:
            self.show_osd("Subtitles shown" if visible else "Subtitles hidden")

    def shift_subs(self, delta):
        self.engine.subtitle_delay = 0 if delta is None else self.engine.subtitle_delay + delta
        self.show_osd(f"Subtitle delay {self.engine.subtitle_delay:+.1f} s")

    def shift_audio(self, delta):
        self.engine.audio_delay = 0 if delta is None else self.engine.audio_delay + delta
        self.show_osd(f"Audio delay {self.engine.audio_delay * 1000:+.0f} ms")

    def _set_shuffle(self, on):
        self.settings["shuffle"] = on
        self.show_osd("Shuffle on" if on else "Shuffle off")

    def _set_visualization(self, on):
        self.engine.set_visualization(on)
        if self.engine.uri and not self.engine.has_video() or on is False:
            self.engine.reload(self.playlist.current.suburi if self.playlist.current else None)
        self.show_osd("Visualization on" if on else "Visualization off")

    # ------------------------------------------------------------- video

    def _set_aspect(self, mode):
        self.aspect = mode
        act = self.lookup_action("aspect")
        if act:
            act.set_state(GLib.Variant.new_string(mode))
        parent = self.picture.get_parent()
        if parent is self.aspect_frame:
            self.aspect_frame.set_child(None)
        elif parent is not None:
            parent.remove(self.picture)
        if self.aspect_frame.get_parent() is not None:
            self.video_holder.remove(self.aspect_frame)
        if ":" in mode:
            w, h = mode.split(":")
            self.aspect_frame.set_ratio(float(w) / float(h))
            self.picture.set_content_fit(Gtk.ContentFit.FILL)
            self.aspect_frame.set_child(self.picture)
            self.video_holder.append(self.aspect_frame)
        else:
            fit = {"default": Gtk.ContentFit.CONTAIN, "stretch": Gtk.ContentFit.FILL,
                   "crop": Gtk.ContentFit.COVER}[mode]
            self.picture.set_content_fit(fit)
            self.video_holder.append(self.picture)
        if self.engine.uri:
            self.show_osd(f"Aspect: {dict(ASPECTS)[mode]}")

    def apply_color(self, osd=True, key=None):
        self.engine.set_color(**self.color)
        if osd and key:
            self.show_osd(f"{key.capitalize()} {self.color[key]:+.2f}")

    def nudge_color(self, key, direction):
        lo, hi = COLOR_RANGE[key]
        self.color[key] = round(min(max(self.color[key] + direction * COLOR_STEP[key], lo), hi), 3)
        self.apply_color(key=key)

    def reset_color(self):
        self.color = dict(COLOR_DEFAULT)
        self.apply_color(osd=False)
        if self._color_dialog:
            self._color_dialog.reset()
        self.show_osd("Colors reset")

    def show_colors(self):
        self._color_dialog = dialogs.ColorDialog(self)
        self._color_dialog.present()

    def show_equalizer(self):
        self._eq_dialog = dialogs.EqualizerDialog(self)
        self._eq_dialog.present()

    def show_media_info(self):
        uri = self.engine.uri
        if not uri:
            self.toast("Nothing is playing")
            return
        discover(uri, lambda text: dialogs.show_media_info(self, text) and False)

    def screenshot(self):
        paintable = self.engine.paintable
        w, h = paintable.get_intrinsic_width(), paintable.get_intrinsic_height()
        if not self.engine.uri or w <= 0 or h <= 0:
            self.toast("No video frame to capture")
            return None
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w, h)
        node = snap.to_node()
        if node is None:
            self.toast("No video frame to capture")
            return None
        renderer = self.get_native().get_renderer()
        texture = renderer.render_texture(node, Graphene.Rect().init(0, 0, w, h))
        folder = Path(self.settings["screenshot_dir"]).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        entry = self.playlist.current
        stem = Path(entry.title).stem if entry else "frame"
        pos = self.engine.position() or 0
        name = f"{stem}_{int(pos // 3600):02}.{int(pos // 60 % 60):02}.{pos % 60:06.3f}.png"
        path = folder / name
        texture.save_to_png(str(path))
        self.show_osd(f"Saved {name}")
        return path

    # -------------------------------------------------------- fullscreen

    def toggle_fullscreen(self):
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _leave_fullscreen(self):
        if self.is_fullscreen():
            self.unfullscreen()

    def _on_fullscreen_changed(self, *_args):
        fs = self.is_fullscreen()
        self.view.set_extend_content_to_top_edge(fs)
        self.view.set_extend_content_to_bottom_edge(fs)
        self.view.set_reveal_top_bars(True)
        self.view.set_reveal_bottom_bars(True)
        self.set_cursor(None)
        if fs:
            self._hide_timeout = GLib.timeout_add(2500, self._autohide)

    # --------------------------------------------------------------- OSD

    def show_osd(self, text, ms=1800):
        self.osd.set_label(text)
        self.osd.set_visible(True)
        if self._osd_timeout:
            GLib.source_remove(self._osd_timeout)

        def hide():
            self._osd_timeout = 0
            self.osd.set_visible(False)
            return False

        self._osd_timeout = GLib.timeout_add(ms, hide)

    def show_status(self):
        e = self.engine
        if not e.uri:
            self.show_osd("Idle")
            return
        entry = self.playlist.current
        lines = [entry.title if entry else display_name(e.uri),
                 f"{fmt_time(e.position())} / {fmt_time(e.duration())}   {'playing' if e.playing else 'paused'}"]
        size = e.video_size()
        if size:
            lines.append(f"{size[0]}×{size[1]}  @ {e.framerate():.3g} fps")
        lines.append(f"Volume {round(e.volume * 100)}%{' (muted)' if e.mute else ''}   Speed {e.rate:g}×")
        if e.audio_delay:
            lines.append(f"Audio delay {e.audio_delay * 1000:+.0f} ms")
        if e.subtitle_delay:
            lines.append(f"Subtitle delay {e.subtitle_delay:+.1f} s")
        self.show_osd("\n".join(lines), 4000)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    # ----------------------------------------------------------- lifetime

    def _save_resume(self, write=False):
        entry = self.playlist.current
        if not entry or not self.engine.uri or not self.settings["resume_playback"]:
            return
        pos, dur = self.engine.position(), self.engine.duration()
        if pos is None or dur is None or dur < 60:
            return
        if 10 < pos < dur - 20:
            self.settings.set_resume(entry.uri, pos)
        else:
            self.settings.set_resume(entry.uri, None)
        if write:
            self.settings.save()

    def _on_close(self, *_args):
        if self._whisper_thread is not None:
            self._whisper_cancel.set()
            self._whisper_thread.join(3)
        self._save_resume()
        self.settings.save()
        self.engine.shutdown()
        return False
