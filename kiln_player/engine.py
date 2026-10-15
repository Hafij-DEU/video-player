"""Playback engine: a GStreamer playbin with Kiln's video and audio filter chains.

Video: decoder -> playsink subtitle overlay -> video-sink bin
       [glupload ! glcolorconvert ! glcolorbalance ! glvideoflip ! glshader ! glsinkbin(gtk4paintablesink)]
                                                  (GL path, used when GTK has a GL context)
       decoder -> [videobalance ! videoflip] -> gtk4paintablesink   (software fallback)
Audio: decoder -> [scaletempo ! audioconvert ! equalizer-10bands ! audioconvert] -> autoaudiosink
"""

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import GLib, GObject, Gst, GstPbutils  # noqa: E402

from .shaders import PASSTHROUGH  # noqa: E402

Gst.init(None)

SECOND = Gst.SECOND

# GstPlayFlags
FLAG_VIDEO = 1 << 0
FLAG_AUDIO = 1 << 1
FLAG_TEXT = 1 << 2
FLAG_VIS = 1 << 3
FLAG_SOFT_VOLUME = 1 << 4
FLAG_DEINTERLACE = 1 << 9
DEFAULT_FLAGS = FLAG_VIDEO | FLAG_AUDIO | FLAG_TEXT | FLAG_SOFT_VOLUME | FLAG_DEINTERLACE

FLIP_METHODS = [
    ("Automatic (from file)", "automatic"),
    ("No rotation", "none"),
    ("Rotate 90° right", "clockwise"),
    ("Rotate 180°", "rotate-180"),
    ("Rotate 90° left", "counterclockwise"),
    ("Mirror horizontally", "horizontal-flip"),
    ("Flip vertically", "vertical-flip"),
]

EQ_FREQS = ["29", "59", "119", "237", "474", "947", "1.9k", "3.8k", "7.5k", "15k"]

EQ_PRESETS = {
    "Flat": [0] * 10,
    "Bass boost": [7, 6, 5, 3, 1, 0, 0, 0, 0, 0],
    "Treble boost": [0, 0, 0, 0, 0, 1, 3, 5, 6, 7],
    "Vocal": [-2, -2, -1, 1, 4, 4, 3, 1, 0, -1],
    "Rock": [5, 4, 2, -1, -2, -1, 2, 4, 5, 5],
    "Pop": [-1, 1, 3, 4, 3, 0, -1, -1, 0, 1],
    "Classical": [4, 3, 2, 1, -1, -1, 0, 2, 3, 4],
    "Live": [-3, 0, 2, 3, 3, 3, 2, 1, 1, 1],
    "Night (soft loud parts)": [-4, -2, 0, 2, 3, 3, 2, 0, -2, -4],
}


def _make(factory, name=None):
    el = Gst.ElementFactory.make(factory, name)
    if el is None:
        raise RuntimeError(f"GStreamer element '{factory}' is missing")
    return el


def _chain_bin(name, elements):
    """Link elements in order inside a bin with ghost sink/src pads."""
    b = Gst.Bin.new(name)
    for el in elements:
        b.add(el)
    for a, c in zip(elements, elements[1:]):
        if not a.link(c):
            raise RuntimeError(f"cannot link {a.get_name()} to {c.get_name()}")
    b.add_pad(Gst.GhostPad.new("sink", elements[0].get_static_pad("sink")))
    src = elements[-1].get_static_pad("src")
    if src is not None:
        b.add_pad(Gst.GhostPad.new("src", src))
    return b


def _gl_rgba_caps():
    """Pin the chain to RGBA textures; otherwise glupload may pass DMABuf through untouched."""
    caps = _make("capsfilter")
    caps.set_property("caps", Gst.Caps.from_string("video/x-raw(memory:GLMemory),format=RGBA"))
    return caps


def set_hardware_decoding(enabled):
    """Rank VA-API decoders up or out so decodebin picks or skips them."""
    registry = Gst.Registry.get()
    for feature in registry.get_feature_list(Gst.ElementFactory):
        name = feature.get_name()
        if name.startswith(("va", "nv", "v4l2")) and "dec" in name and \
                "Decoder" in (feature.get_metadata("klass") or ""):
            feature.set_rank(Gst.Rank.PRIMARY + 1 if enabled else Gst.Rank.NONE)


class Engine(GObject.Object):
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "eos": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "loaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "tags-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "buffering": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__()
        self.playbin = _make("playbin", "kiln")
        self.playbin.set_property("flags", DEFAULT_FLAGS)

        self.gtksink = _make("gtk4paintablesink")
        self.paintable = self.gtksink.get_property("paintable")
        self.gl = self.paintable.get_property("gl-context") is not None

        if self.gl:
            # The GL chain lives inside the video sink, after playsink's own subtitle
            # overlay, so text, ASS and bitmap subtitles are burned in before upload.
            glsink = _make("glsinkbin")
            glsink.set_property("sink", self.gtksink)
            self.balance = _make("glcolorbalance")
            self.flip = _make("glvideoflip")
            self.shader = _make("glshader")
            self.shader.set_property("fragment", PASSTHROUGH)
            # playbin asks the sink which memory decoders may output. Answer "system
            # memory": the subtitle overlay in front of the sink cannot read DMABuf.
            sysmem = _make("capsfilter")
            sysmem.set_property("caps", Gst.Caps.from_string("video/x-raw"))
            sink = _chain_bin("kiln-video-sink", [
                sysmem, _make("glupload"), _make("glcolorconvert"), _gl_rgba_caps(),
                self.balance, self.flip, self.shader, glsink,
            ])
            vfilter = None
        else:
            sink = self.gtksink
            self.balance = _make("videobalance")
            self.flip = _make("videoflip")
            self.shader = None
            vfilter = _chain_bin("kiln-video", [self.balance, self.flip, _make("videoconvert")])
        Gst.util_set_object_arg(self.flip, "method", "automatic")
        self.playbin.set_property("video-sink", sink)
        if vfilter is not None:
            self.playbin.set_property("video-filter", vfilter)

        self.equalizer = _make("equalizer-10bands")
        afilter = _chain_bin("kiln-audio", [
            _make("scaletempo"), _make("audioconvert"), self.equalizer, _make("audioconvert"),
        ])
        self.playbin.set_property("audio-filter", afilter)

        vis = Gst.ElementFactory.make("goom") or Gst.ElementFactory.make("wavescope")
        if vis is not None:
            self.playbin.set_property("vis-plugin", vis)

        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

        self.uri = None
        self.rate = 1.0
        self.playing = False
        self.tags = {}
        self.chapters = []
        self._pending_seek = None
        self._pending_play = True
        self._loaded = False
        self._buffering = False
        self._suburi = None
        self._start = 0.0
        self.hw_fallback = False

    # ---------------------------------------------------------------- loading

    def load(self, uri, suburi=None, start=0.0, play=True):
        self.playbin.set_state(Gst.State.NULL)
        self.uri = uri
        self._suburi = suburi
        self._start = start or 0.0
        self.tags = {}
        self.chapters = []
        self._loaded = False
        self._pending_seek = start if start and start > 0 else None
        self._pending_play = play
        self.playbin.set_property("uri", uri)
        self.playbin.set_property("suburi", suburi)
        self.playbin.set_state(Gst.State.PAUSED)

    def reload(self, suburi=None):
        """Restart the current media at the same spot, e.g. after adding a subtitle file."""
        if not self.uri:
            return
        pos = self.position() or 0.0
        self.load(self.uri, suburi=suburi, start=pos, play=self.playing)

    def stop(self):
        self.playbin.set_state(Gst.State.NULL)
        self.uri = None
        self._loaded = False
        self._set_playing(False)

    def shutdown(self):
        self.playbin.set_state(Gst.State.NULL)
        self.playbin.get_bus().remove_signal_watch()

    # --------------------------------------------------------------- transport

    def play(self):
        if self.uri:
            self.playbin.set_state(Gst.State.PLAYING)

    def pause(self):
        if self.uri:
            self.playbin.set_state(Gst.State.PAUSED)

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def position(self):
        ok, pos = self.playbin.query_position(Gst.Format.TIME)
        return pos / SECOND if ok and pos >= 0 else None

    def duration(self):
        ok, dur = self.playbin.query_duration(Gst.Format.TIME)
        return dur / SECOND if ok and dur > 0 else None

    def seekable(self):
        q = Gst.Query.new_seeking(Gst.Format.TIME)
        if self.playbin.query(q):
            return q.parse_seeking()[1]
        return False

    def seek(self, seconds, accurate=True):
        if not self.uri:
            return
        dur = self.duration()
        seconds = max(0.0, seconds if dur is None else min(seconds, max(dur - 0.05, 0)))
        if not self._loaded:
            self._pending_seek = seconds
            return
        flags = Gst.SeekFlags.FLUSH
        flags |= Gst.SeekFlags.ACCURATE if accurate else (Gst.SeekFlags.KEY_UNIT | Gst.SeekFlags.SNAP_NEAREST)
        self.playbin.seek(self.rate, Gst.Format.TIME, flags,
                          Gst.SeekType.SET, int(seconds * SECOND), Gst.SeekType.NONE, -1)

    def seek_relative(self, delta):
        pos = self.position()
        if pos is not None:
            self.seek(pos + delta, accurate=False)

    def set_rate(self, rate):
        self.rate = max(0.1, min(rate, 8.0))
        pos = self.position()
        if pos is not None and self._loaded:
            self.playbin.seek(self.rate, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                              Gst.SeekType.SET, int(pos * SECOND), Gst.SeekType.NONE, -1)
        return self.rate

    def frame_step(self, forward=True):
        if not self.uri:
            return
        self.pause()
        if forward:
            self.playbin.send_event(Gst.Event.new_step(Gst.Format.BUFFERS, 1, 1.0, True, False))
        else:
            pos = self.position()
            if pos is not None:
                self.seek(max(0.0, pos - 1.0 / self.framerate()), accurate=True)

    def framerate(self):
        pad = self.playbin.emit("get-video-pad", 0)
        caps = pad.get_current_caps() if pad else None
        if caps:
            ok, num, den = caps.get_structure(0).get_fraction("framerate")
            if ok and num > 0 and den > 0:
                return num / den
        return 25.0

    def video_size(self):
        pad = self.playbin.emit("get-video-pad", 0)
        caps = pad.get_current_caps() if pad else None
        if caps:
            s = caps.get_structure(0)
            ok_w, w = s.get_int("width")
            ok_h, h = s.get_int("height")
            if ok_w and ok_h:
                return w, h
        return None

    def has_video(self):
        return self.playbin.get_property("n-video") > 0

    # ------------------------------------------------------------------ audio

    @property
    def volume(self):
        return self.playbin.get_property("volume")

    @volume.setter
    def volume(self, value):
        self.playbin.set_property("volume", max(0.0, min(value, 2.0)))

    @property
    def mute(self):
        return self.playbin.get_property("mute")

    @mute.setter
    def mute(self, value):
        self.playbin.set_property("mute", bool(value))

    def set_eq(self, bands, enabled=True):
        for i, gain in enumerate(bands):
            self.equalizer.set_property(f"band{i}", float(gain) if enabled else 0.0)

    @property
    def audio_delay(self):
        return self.playbin.get_property("av-offset") / SECOND

    @audio_delay.setter
    def audio_delay(self, seconds):
        self.playbin.set_property("av-offset", int(seconds * SECOND))

    def set_visualization(self, enabled):
        self._set_flag(FLAG_VIS, enabled)

    # ---------------------------------------------------------------- tracks

    def _tracks(self, kind):
        n = self.playbin.get_property(f"n-{kind}")
        out = []
        for i in range(n):
            tags = self.playbin.emit(f"get-{kind}-tags", i)
            label = f"Track {i + 1}"
            if tags:
                parts = []
                for tag in (Gst.TAG_TITLE, Gst.TAG_LANGUAGE_NAME, Gst.TAG_LANGUAGE_CODE,
                            Gst.TAG_AUDIO_CODEC if kind == "audio" else Gst.TAG_SUBTITLE_CODEC,
                            Gst.TAG_VIDEO_CODEC if kind == "video" else None):
                    if tag is None:
                        continue
                    ok, val = tags.get_string(tag)
                    if ok and val and val not in parts:
                        parts.append(val)
                if parts:
                    label += " - " + ", ".join(parts)
            out.append(label)
        return out

    def audio_tracks(self):
        return self._tracks("audio")

    def subtitle_tracks(self):
        return self._tracks("text")

    @property
    def current_audio(self):
        return self.playbin.get_property("current-audio")

    @current_audio.setter
    def current_audio(self, idx):
        self.playbin.set_property("current-audio", idx)

    @property
    def current_subtitle(self):
        return self.playbin.get_property("current-text")

    @current_subtitle.setter
    def current_subtitle(self, idx):
        self.playbin.set_property("current-text", idx)

    @property
    def subtitles_visible(self):
        return bool(self.playbin.get_property("flags") & FLAG_TEXT)

    @subtitles_visible.setter
    def subtitles_visible(self, visible):
        self._set_flag(FLAG_TEXT, visible)

    @property
    def subtitle_delay(self):
        return self.playbin.get_property("text-offset") / SECOND

    @subtitle_delay.setter
    def subtitle_delay(self, seconds):
        self.playbin.set_property("text-offset", int(seconds * SECOND))

    def set_subtitle_font(self, desc):
        self.playbin.set_property("subtitle-font-desc", desc)

    def _set_flag(self, flag, on):
        flags = self.playbin.get_property("flags")
        flags = (flags | flag) if on else (flags & ~flag)
        self.playbin.set_property("flags", flags)

    # ----------------------------------------------------------------- video

    def set_color(self, brightness=0.0, contrast=1.0, saturation=1.0, hue=0.0):
        self.balance.set_property("brightness", brightness)
        self.balance.set_property("contrast", contrast)
        self.balance.set_property("saturation", saturation)
        self.balance.set_property("hue", hue)

    def set_flip(self, method):
        Gst.util_set_object_arg(self.flip, "method", method)

    def set_shader(self, source):
        if self.shader is None:
            return False
        self.shader.set_property("fragment", source or PASSTHROUGH)
        self.shader.set_property("update-shader", True)
        return True

    # ------------------------------------------------------------------- bus

    def _set_playing(self, playing):
        if playing != self.playing:
            self.playing = playing
            self.emit("state-changed", playing)

    def _on_message(self, bus, msg):
        t = msg.type
        if t == Gst.MessageType.STATE_CHANGED and msg.src is self.playbin:
            _old, new, _pending = msg.parse_state_changed()
            self._set_playing(new == Gst.State.PLAYING)
        elif t == Gst.MessageType.ASYNC_DONE:
            if not self._loaded:
                self._loaded = True
                if self._pending_seek is not None or self.rate != 1.0:
                    target = self._pending_seek or 0.0
                    self._pending_seek = None
                    self.playbin.seek(self.rate, Gst.Format.TIME,
                                      Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                                      Gst.SeekType.SET, int(target * SECOND), Gst.SeekType.NONE, -1)
                if self._pending_play:
                    self.playbin.set_state(Gst.State.PLAYING)
                self.emit("loaded")
        elif t == Gst.MessageType.EOS:
            self.emit("eos")
        elif t == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            if not self._loaded and "not-negotiated" in (debug or "") and not self.hw_fallback:
                # Some VA-API drivers cannot hand frames to this display; decode in software.
                set_hardware_decoding(False)
                self.hw_fallback = True
                GLib.idle_add(lambda: self.load(self.uri, self._suburi, self._start, self._pending_play) and False)
                return
            self.playbin.set_state(Gst.State.NULL)
            self._set_playing(False)
            self.emit("error", err.message)
        elif t == Gst.MessageType.ELEMENT and GstPbutils.is_missing_plugin_message(msg):
            desc = GstPbutils.missing_plugin_message_get_description(msg)
            self.emit("error", f"Missing decoder: {desc}")
        elif t == Gst.MessageType.TAG:
            self._merge_tags(msg.parse_tag())
        elif t == Gst.MessageType.TOC:
            toc, _updated = msg.parse_toc()
            self._read_toc(toc)
        elif t == Gst.MessageType.BUFFERING:
            pct = msg.parse_buffering()
            if self.uri and not self.uri.startswith("file:"):
                if pct < 100 and self.playing and not self._buffering:
                    self._buffering = True
                    self.playbin.set_state(Gst.State.PAUSED)
                elif pct >= 100 and self._buffering:
                    self._buffering = False
                    self.playbin.set_state(Gst.State.PLAYING)
                self.emit("buffering", pct)

    def _merge_tags(self, taglist):
        changed = False
        for tag in (Gst.TAG_TITLE, Gst.TAG_ARTIST, Gst.TAG_ALBUM):
            ok, val = taglist.get_string(tag)
            if ok and val and self.tags.get(tag) != val:
                self.tags[tag] = val
                changed = True
        if "image" not in self.tags:
            for tag in (Gst.TAG_IMAGE, Gst.TAG_PREVIEW_IMAGE):
                ok, sample = taglist.get_sample(tag)
                if ok and sample:
                    buf = sample.get_buffer()
                    ok, info = buf.map(Gst.MapFlags.READ)
                    if ok:
                        self.tags["image"] = bytes(info.data)
                        buf.unmap(info)
                        changed = True
                        break
        if changed:
            self.emit("tags-changed")

    def _read_toc(self, toc):
        chapters = []

        def walk(entries):
            for entry in entries:
                if entry.get_entry_type() == Gst.TocEntryType.CHAPTER:
                    ok, start, _stop = entry.get_start_stop_times()
                    title = None
                    tags = entry.get_tags()
                    if tags:
                        ok_t, title = tags.get_string(Gst.TAG_TITLE)
                    if ok:
                        chapters.append((start / SECOND, title or f"Chapter {len(chapters) + 1}"))
                walk(entry.get_sub_entries())

        walk(toc.get_entries())
        self.chapters = sorted(chapters)


def discover(uri, callback):
    """Collect media info off the main loop; calls callback(text) on the main loop."""
    import threading

    def worker():
        try:
            disc = GstPbutils.Discoverer.new(10 * SECOND)
            info = disc.discover_uri(uri)
            text = format_info(info)
        except GLib.Error as exc:
            text = f"Could not read media info:\n{exc.message}"
        GLib.idle_add(callback, text)

    threading.Thread(target=worker, daemon=True).start()


def format_info(info):
    lines = [f"URI: {info.get_uri()}"]
    dur = info.get_duration()
    if dur and dur > 0:
        s = dur // SECOND
        lines.append(f"Duration: {s // 3600}:{s // 60 % 60:02}:{s % 60:02}")
    lines.append(f"Seekable: {'yes' if info.get_seekable() else 'no'}")
    tags = info.get_tags()
    if tags:
        for tag, label in ((Gst.TAG_TITLE, "Title"), (Gst.TAG_ARTIST, "Artist"),
                           (Gst.TAG_ALBUM, "Album"), (Gst.TAG_CONTAINER_FORMAT, "Container")):
            ok, val = tags.get_string(tag)
            if ok:
                lines.append(f"{label}: {val}")
        ok, br = tags.get_uint(Gst.TAG_BITRATE)
        if ok:
            lines.append(f"Overall bitrate: {br // 1000} kb/s")
    for i, v in enumerate(info.get_video_streams()):
        num, den = v.get_framerate_num(), v.get_framerate_denom()
        fps = f"{num / den:.3f} fps" if num and den else "variable fps"
        lines += ["", f"Video #{i + 1}",
                  f"  Codec: {GstPbutils.pb_utils_get_codec_description(v.get_caps())}",
                  f"  Size: {v.get_width()} x {v.get_height()}",
                  f"  Frame rate: {fps}",
                  f"  Bit depth: {v.get_depth() or 'n/a'}",
                  f"  Interlaced: {'yes' if v.is_interlaced() else 'no'}"]
        if v.get_bitrate():
            lines.append(f"  Bitrate: {v.get_bitrate() // 1000} kb/s")
    for i, a in enumerate(info.get_audio_streams()):
        lines += ["", f"Audio #{i + 1}",
                  f"  Codec: {GstPbutils.pb_utils_get_codec_description(a.get_caps())}",
                  f"  Channels: {a.get_channels()}",
                  f"  Sample rate: {a.get_sample_rate()} Hz",
                  f"  Language: {a.get_language() or 'n/a'}"]
        if a.get_bitrate():
            lines.append(f"  Bitrate: {a.get_bitrate() // 1000} kb/s")
    for i, s in enumerate(info.get_subtitle_streams()):
        lines += ["", f"Subtitle #{i + 1}",
                  f"  Format: {GstPbutils.pb_utils_get_codec_description(s.get_caps())}",
                  f"  Language: {s.get_language() or 'n/a'}"]
    return "\n".join(lines)
