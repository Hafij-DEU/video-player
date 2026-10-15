"""Application entry point."""

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__  # noqa: E402
from .engine import set_hardware_decoding  # noqa: E402
from .settings import Settings  # noqa: E402

APP_ID = "io.github.hafij.KilnPlayer"
HERE = Path(__file__).resolve().parent


class KilnApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE
                         if "--new-instance" in sys.argv else Gio.ApplicationFlags.HANDLES_OPEN)
        self.settings = None
        self.window = None
        self.mpris = None
        GLib.set_application_name("Kiln Player")

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self.settings = Settings()
        set_hardware_decoding(self.settings["hardware_decoding"])

        display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        icons = HERE / "icons"
        if icons.is_dir():
            Gtk.IconTheme.get_for_display(display).add_search_path(str(icons))
        Gtk.Window.set_default_icon_name(APP_ID)

        for name, cb in (("about", self._about), ("quit", lambda *_: self._quit())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

    def _ensure_window(self):
        if self.window is None:
            from .window import PlayerWindow
            self.window = PlayerWindow(self)
            try:
                from .mpris import Mpris
                self.mpris = Mpris(self, self.window)
            except Exception as exc:  # MPRIS is optional; never block playback on it
                print(f"kiln-player: MPRIS disabled: {exc}", file=sys.stderr)
        return self.window

    def do_activate(self):
        self._ensure_window().present()

    def do_open(self, files, n_files, hint):
        win = self._ensure_window()
        win.present()
        win.open_uris([f.get_uri() for f in files])

    def emit_player_changed(self):
        if self.mpris is not None:
            self.mpris.changed()

    def _quit(self):
        if self.window is not None:
            self.window.close()
        self.quit()

    def _about(self, *_args):
        about = Adw.AboutDialog(
            application_name="Kiln Player",
            application_icon=APP_ID,
            version=__version__,
            developer_name="Hafij",
            license_type=Gtk.License.GPL_3_0,
            comments="A free media player for Linux with every codec built in.\n"
                     "Built on GStreamer and FFmpeg (gst-libav).",
            website="https://github.com/Hafij-DEU/video-player",
            issue_url="https://github.com/Hafij-DEU/video-player/issues",
        )
        about.present(self.window)


def main():
    argv = [a for a in sys.argv if a != "--new-instance"]
    return KilnApp().run(argv)
