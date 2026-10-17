"""Seek-bar preview frames, decoded by a second, video-only GStreamer pipeline.

Requests arrive as the pointer moves; only the newest pending request is kept,
so a fast sweep across the bar never queues up work. Frames are cached per
time bucket and per URI.
"""

import threading

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

WIDTH = 192
BUCKET = 2.0          # seconds per cached frame
MAX_CACHE = 400


class Thumbnailer:
    def __init__(self, on_frame):
        """on_frame(uri, seconds, rgba_bytes, width, height) runs on the main loop."""
        self.on_frame = on_frame
        self._uri = None
        self._pipe = None
        self._sink = None
        self._cache = {}
        self._want = None
        self._cond = threading.Condition()
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def bucket(seconds):
        return round(seconds / BUCKET) * BUCKET

    def cached(self, uri, seconds):
        return self._cache.get((uri, self.bucket(seconds)))

    def request(self, uri, seconds):
        key = (uri, self.bucket(seconds))
        hit = self._cache.get(key)
        if hit is not None:
            GLib.idle_add(self.on_frame, uri, key[1], *hit)
            return
        with self._cond:
            self._want = key
            self._cond.notify()

    def forget(self):
        with self._cond:
            self._want = None
            self._uri = None
        self._cache.clear()

    def shutdown(self):
        with self._cond:
            self._stop = True
            self._cond.notify()

    # ------------------------------------------------------------ worker

    def _open(self, uri):
        if self._pipe is not None:
            self._pipe.set_state(Gst.State.NULL)
        pipe = Gst.ElementFactory.make("playbin", "astra-thumbs")
        sink = Gst.parse_bin_from_description(
            f"videoconvert ! videoscale ! video/x-raw,format=RGBA,width={WIDTH},pixel-aspect-ratio=1/1 "
            "! appsink name=frames sync=false max-buffers=1 drop=true", True)
        pipe.set_property("video-sink", sink)
        pipe.set_property("audio-sink", Gst.ElementFactory.make("fakesink"))
        pipe.set_property("flags", 1)  # video only
        pipe.set_property("uri", uri)
        pipe.set_state(Gst.State.PAUSED)
        ok = pipe.get_state(15 * Gst.SECOND)[0] != Gst.StateChangeReturn.FAILURE
        if not ok:
            pipe.set_state(Gst.State.NULL)
            return False
        self._pipe, self._sink, self._uri = pipe, sink.get_by_name("frames"), uri
        return True

    def _grab(self, seconds):
        self._pipe.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                               int(seconds * Gst.SECOND))
        self._pipe.get_state(5 * Gst.SECOND)
        sample = self._sink.emit("try-pull-preroll", 3 * Gst.SECOND)
        if sample is None:
            return None
        s = sample.get_caps().get_structure(0)
        w, h = s.get_value("width"), s.get_value("height")
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return None
        data = bytes(info.data)
        buf.unmap(info)
        return data, w, h

    def _run(self):
        while True:
            with self._cond:
                while self._want is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    if self._pipe is not None:
                        self._pipe.set_state(Gst.State.NULL)
                    return
                uri, seconds = self._want
                self._want = None
            try:
                if uri != self._uri and not self._open(uri):
                    continue
                frame = self._grab(seconds)
            except GLib.Error:
                frame = None
            if frame is None:
                continue
            if len(self._cache) > MAX_CACHE:
                self._cache.clear()
            self._cache[(uri, seconds)] = frame
            GLib.idle_add(self.on_frame, uri, seconds, *frame)
