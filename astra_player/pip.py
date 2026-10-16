"""Picture-in-picture: a small borderless window that shows the same video.

The video paintable from gtk4paintablesink is shared, so nothing is decoded
twice. Wayland does not let an app place itself above other windows, so the
window explains how to pin it (Alt+Space › Always on Top) the first time.
"""

from gi.repository import Gdk, GLib, Graphene, Gtk


class PipWindow(Gtk.Window):
    def __init__(self, player):
        super().__init__(application=player.app, title="Astra Player — Picture in picture",
                         decorated=False, resizable=True, default_width=480, default_height=270,
                         css_classes=["pip-window"])
        self.player = player
        self._hide_id = 0

        picture = Gtk.Picture(paintable=player.engine.paintable, can_shrink=True,
                              content_fit=Gtk.ContentFit.CONTAIN, hexpand=True, vexpand=True)
        overlay = Gtk.Overlay(css_classes=["video-area"])
        overlay.set_child(picture)

        def button(icon, tip, cb):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["circular", "pip-btn"],
                           focus_on_click=False)
            b.connect("clicked", lambda _b: cb())
            return b

        self.play_btn = button("media-playback-pause-symbolic", "Play / pause (Space)", player.engine.toggle)
        bar = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=10)
        bar.append(button("media-seek-backward-symbolic", "Back 10 s", lambda: player.seek_by(-10)))
        bar.append(self.play_btn)
        bar.append(button("media-seek-forward-symbolic", "Forward 10 s", lambda: player.seek_by(10)))
        top = Gtk.Box(spacing=6, halign=Gtk.Align.END, valign=Gtk.Align.START,
                      margin_top=8, margin_end=8)
        top.append(button("view-restore-symbolic", "Back to the full window (Esc, double-click)",
                          player.leave_pip))
        top.append(button("view-fullscreen-symbolic", "Back to fullscreen (Enter)", self._to_fullscreen))
        top.append(button("window-close-symbolic", "Pause and close picture in picture", self._close_all))
        grip = Gtk.Image(icon_name="list-drag-handle-symbolic", halign=Gtk.Align.END,
                         valign=Gtk.Align.END, margin_end=4, margin_bottom=4,
                         css_classes=["pip-grip"], tooltip_text="Drag to resize",
                         cursor=Gdk.Cursor.new_from_name("se-resize", None))
        self.controls = [bar, top, grip]
        for w in self.controls:
            overlay.add_overlay(w)
        self.hint = Gtk.Label(css_classes=["osd", "pip-hint"], wrap=True, visible=False,
                              justify=Gtk.Justification.CENTER, halign=Gtk.Align.CENTER,
                              valign=Gtk.Align.CENTER, margin_start=24, margin_end=24,
                              can_target=False)
        overlay.add_overlay(self.hint)
        self.set_child(overlay)

        # The gestures sit on the picture only, so presses on the buttons stay clicks.
        # Drag the video to move the window, double-click it to go back, drag the grip to resize.
        self._moving = False
        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", lambda *_: setattr(self, "_moving", False))
        drag.connect("drag-update", self._on_drag)
        picture.add_controller(drag)
        dbl = Gtk.GestureClick(button=1)
        dbl.connect("pressed", lambda _g, n, _x, _y: self.player.leave_pip() if n == 2 else None)
        picture.add_controller(dbl)
        resize = Gtk.GestureClick(button=1)
        resize.connect("pressed", self._on_grip)
        grip.add_controller(resize)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda *_: self._show_controls())
        motion.connect("enter", lambda *_: self._show_controls())
        self.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", lambda _c, _dx, dy: player.change_volume(-0.05 if dy > 0 else 0.05) or True)
        overlay.add_controller(scroll)

        self.connect("close-request", self._on_close_request)
        self._state_id = player.engine.connect("state-changed", self._on_state)
        self._on_state(player.engine, player.engine.playing)
        self._show_controls(4000)

    def show_hint(self, text, ms=6000):
        self.hint.set_label(text)
        self.hint.set_visible(True)
        GLib.timeout_add(ms, lambda: self.hint.set_visible(False) or False)

    def _on_state(self, _engine, playing):
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")

    def _event_info(self, gesture):
        surface = self.get_surface()
        device = gesture.get_current_event_device() or gesture.get_device()
        event = gesture.get_current_event()
        ts = event.get_time() if event else Gdk.CURRENT_TIME
        return (surface if isinstance(surface, Gdk.Toplevel) else None), device, ts

    def _on_drag(self, gesture, dx, dy):
        if self._moving or dx * dx + dy * dy < 25:
            return
        surface, device, ts = self._event_info(gesture)
        if surface is None or device is None:
            return
        self._moving = True
        ok, x, y = gesture.get_start_point()
        point = self.get_child().compute_point(self, Graphene.Point().init(x, y))
        px, py = (point[1].x, point[1].y) if isinstance(point, tuple) else (x, y)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        surface.begin_move(device, 1, px, py, ts)

    def _on_grip(self, gesture, _n, _x, _y):
        surface, device, ts = self._event_info(gesture)
        if surface is None or device is None:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        surface.begin_resize(Gdk.SurfaceEdge.SOUTH_EAST, device, 1,
                             self.get_width() - 4, self.get_height() - 4, ts)

    def _to_fullscreen(self):
        player = self.player
        player.leave_pip()
        GLib.idle_add(lambda: player.fullscreen() or False)

    def _on_key(self, _ctrl, keyval, _code, _state):
        name = (Gdk.keyval_name(keyval) or "").lower()
        if name == "escape":
            self.player.leave_pip()
        elif name in ("return", "kp_enter", "f11"):
            self._to_fullscreen()
        elif name == "space":
            self.player.engine.toggle()
        elif name == "left":
            self.player.seek_by(-5)
        elif name == "right":
            self.player.seek_by(5)
        else:
            return False
        return True

    def _show_controls(self, ms=2500):
        for w in self.controls:
            w.set_visible(True)
        if self._hide_id:
            GLib.source_remove(self._hide_id)
        self._hide_id = GLib.timeout_add(ms, self._hide_controls)

    def _hide_controls(self):
        self._hide_id = 0
        for w in self.controls:
            w.set_visible(False)
        return False

    def _close_all(self):
        self.player.engine.pause()
        self.player.leave_pip()

    def _on_close_request(self, *_args):
        self.player.leave_pip(from_close=True)
        return False

    def dispose_handlers(self):
        if self._state_id:
            self.player.engine.disconnect(self._state_id)
            self._state_id = 0
        if self._hide_id:
            GLib.source_remove(self._hide_id)
            self._hide_id = 0
