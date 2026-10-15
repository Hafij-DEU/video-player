"""MPRIS 2 D-Bus interface, so media keys and desktop media controls work."""

from gi.repository import Gio, GLib

BUS_NAME = "org.mpris.MediaPlayer2.astra_player"
PATH = "/org/mpris/MediaPlayer2"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
US = 1_000_000

XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


class Mpris:
    def __init__(self, app, win):
        self.app = app
        self.win = win
        self.conn = None
        self._ids = []
        self._last = {}
        self._pending = 0
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        self._owner = Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                                       self._on_bus, None, None)

    def _on_bus(self, conn, _name):
        self.conn = conn
        for iface in self.node.interfaces:
            self._ids.append(conn.register_object(PATH, iface, self._call, self._get, self._set))

    # ------------------------------------------------------------- values

    def _props(self):
        w, e = self.win, self.win.engine
        if not e.uri:
            status = "Stopped"
        else:
            status = "Playing" if e.playing else "Paused"
        meta = {"mpris:trackid": GLib.Variant("o", "/io/github/hafij/AstraPlayer/track/%d" % max(w.playlist.index, 0))}
        entry = w.playlist.current
        if entry:
            meta["xesam:title"] = GLib.Variant("s", e.tags.get("title") or entry.title)
            meta["xesam:url"] = GLib.Variant("s", entry.uri)
            if e.tags.get("artist"):
                meta["xesam:artist"] = GLib.Variant("as", [e.tags["artist"]])
            if e.tags.get("album"):
                meta["xesam:album"] = GLib.Variant("s", e.tags["album"])
            dur = e.duration()
            if dur:
                meta["mpris:length"] = GLib.Variant("x", int(dur * US))
        n = len(w.playlist)
        return {
            "PlaybackStatus": GLib.Variant("s", status),
            "Rate": GLib.Variant("d", e.rate),
            "Metadata": GLib.Variant("a{sv}", meta),
            "Volume": GLib.Variant("d", e.volume),
            "Position": GLib.Variant("x", int((e.position() or 0) * US)),
            "MinimumRate": GLib.Variant("d", 0.1),
            "MaximumRate": GLib.Variant("d", 8.0),
            "CanGoNext": GLib.Variant("b", n > 1),
            "CanGoPrevious": GLib.Variant("b", n > 1),
            "CanPlay": GLib.Variant("b", n > 0),
            "CanPause": GLib.Variant("b", bool(e.uri)),
            "CanSeek": GLib.Variant("b", bool(e.uri)),
            "CanControl": GLib.Variant("b", True),
            "CanQuit": GLib.Variant("b", True),
            "CanRaise": GLib.Variant("b", True),
            "HasTrackList": GLib.Variant("b", False),
            "Identity": GLib.Variant("s", "Astra Player"),
            "DesktopEntry": GLib.Variant("s", "io.github.hafij.AstraPlayer"),
            "SupportedUriSchemes": GLib.Variant("as", ["file", "http", "https", "rtsp", "rtmp", "mms"]),
            "SupportedMimeTypes": GLib.Variant("as", ["video/mp4", "video/x-matroska", "audio/mpeg",
                                                      "audio/flac", "video/webm"]),
        }

    def _get(self, conn, sender, path, iface, prop):
        return self._props().get(prop)

    def _set(self, conn, sender, path, iface, prop, value):
        if prop == "Volume":
            self.win.engine.volume = value.unpack()
            self.win._update_volume_ui()
        elif prop == "Rate":
            self.win.set_speed(value.unpack())
        return True

    def _call(self, conn, sender, path, iface, method, params, invocation):
        w, e = self.win, self.win.engine
        if method == "Raise":
            w.present()
        elif method == "Quit":
            self.app.activate_action("quit", None)
        elif method == "Next":
            w.step_playlist(1)
        elif method == "Previous":
            w.step_playlist(-1)
        elif method == "Pause":
            e.pause()
        elif method == "Play":
            e.play()
        elif method == "PlayPause":
            e.toggle()
        elif method == "Stop":
            w.stop()
        elif method == "Seek":
            e.seek_relative(params.unpack()[0] / US)
        elif method == "SetPosition":
            e.seek(params.unpack()[1] / US)
        elif method == "OpenUri":
            w.open_uris([params.unpack()[0]])
        invocation.return_value(None)

    # ------------------------------------------------------------ signals

    def changed(self):
        if self.conn is None or self._pending:
            return
        self._pending = GLib.idle_add(self._flush)

    def _flush(self):
        self._pending = 0
        props = self._props()
        props.pop("Position", None)
        diff = {k: v for k, v in props.items() if self._last.get(k) != v}
        self._last = props
        player_keys = {p.name for p in self.node.lookup_interface(PLAYER).properties}
        changed = {k: v for k, v in diff.items() if k in player_keys}
        if changed:
            self.conn.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  GLib.Variant("(sa{sv}as)", (PLAYER, changed, [])))
        return False
