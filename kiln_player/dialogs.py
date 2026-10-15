"""Secondary dialogs: equalizer, color adjust, media info, preferences, shortcuts, URL."""

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .engine import EQ_FREQS, EQ_PRESETS


def _dialog(title, child, width=480, height=-1):
    dlg = Adw.Dialog(title=title, content_width=width, content_height=height)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    view.set_content(child)
    dlg.set_child(view)
    return dlg


class EqualizerDialog:
    def __init__(self, win):
        self.win = win
        s = win.settings
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)

        top = Gtk.Box(spacing=12)
        self.enabled = Gtk.Switch(active=s["eq_enabled"], valign=Gtk.Align.CENTER)
        self.enabled.connect("notify::active", self._apply)
        top.append(Gtk.Label(label="Enable equalizer"))
        top.append(self.enabled)
        top.append(Gtk.Box(hexpand=True))
        names = list(EQ_PRESETS)
        self.preset = Gtk.DropDown.new_from_strings(["Preset…"] + names)
        self.preset.connect("notify::selected", self._on_preset)
        top.append(self.preset)
        box.append(top)

        bands = Gtk.Box(spacing=6, homogeneous=True)
        self.scales = []
        for i, freq in enumerate(EQ_FREQS):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -24, 12, 0.5)
            sc.set_inverted(True)
            sc.set_draw_value(True)
            sc.set_value_pos(Gtk.PositionType.TOP)
            sc.set_size_request(-1, 220)
            sc.add_mark(0, Gtk.PositionType.LEFT, None)
            sc.set_value(s["eq_bands"][i])
            sc.connect("value-changed", self._apply)
            self.scales.append(sc)
            col.append(sc)
            col.append(Gtk.Label(label=freq, css_classes=["caption", "dim-label"]))
            bands.append(col)
        box.append(bands)
        self.dialog = _dialog("Equalizer", box, width=620)

    def _on_preset(self, dd, _pspec):
        idx = dd.get_selected()
        if idx == 0:
            return
        gains = EQ_PRESETS[list(EQ_PRESETS)[idx - 1]]
        for sc, g in zip(self.scales, gains):
            sc.set_value(g)
        self.enabled.set_active(True)

    def _apply(self, *_args):
        s = self.win.settings
        s["eq_enabled"] = self.enabled.get_active()
        s["eq_bands"] = [round(sc.get_value(), 1) for sc in self.scales]
        self.win.engine.set_eq(s["eq_bands"], s["eq_enabled"])

    def present(self):
        self.dialog.present(self.win)


class ColorDialog:
    ROWS = [
        ("brightness", "Brightness", -1.0, 1.0, 0.0),
        ("contrast", "Contrast", 0.0, 2.0, 1.0),
        ("saturation", "Saturation", 0.0, 2.0, 1.0),
        ("hue", "Hue", -1.0, 1.0, 0.0),
    ]

    def __init__(self, win):
        self.win = win
        grid = Gtk.Grid(column_spacing=12, row_spacing=10,
                        margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
        self.scales = {}
        for row, (key, label, lo, hi, _default) in enumerate(self.ROWS):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 0.01)
            sc.set_hexpand(True)
            sc.set_value(win.color[key])
            sc.set_digits(2)
            sc.set_draw_value(True)
            sc.connect("value-changed", self._apply)
            grid.attach(sc, 1, row, 1, 1)
            self.scales[key] = sc
        reset = Gtk.Button(label="Reset", halign=Gtk.Align.END)
        reset.connect("clicked", lambda _b: self.reset())
        grid.attach(reset, 1, len(self.ROWS), 1, 1)
        self.dialog = _dialog("Video Color", grid, width=460)

    def reset(self):
        for key, _l, _lo, _hi, default in self.ROWS:
            self.scales[key].set_value(default)

    def _apply(self, *_args):
        for key, sc in self.scales.items():
            self.win.color[key] = sc.get_value()
        self.win.apply_color(osd=False)

    def present(self):
        self.dialog.present(self.win)


def show_media_info(win, text):
    buf = Gtk.TextBuffer(text=text)
    view = Gtk.TextView(buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
    scroll = Gtk.ScrolledWindow(child=view, vexpand=True)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.append(scroll)
    copy = Gtk.Button(label="Copy to clipboard", halign=Gtk.Align.END,
                      margin_top=6, margin_bottom=12, margin_end=12)
    copy.connect("clicked", lambda _b: win.get_clipboard().set(text))
    box.append(copy)
    _dialog("Media Info", box, width=560, height=520).present(win)


def ask_url(win, callback):
    dlg = Adw.AlertDialog(heading="Open URL", body="Stream address, YouTube link, or file path")
    entry = Gtk.Entry(placeholder_text="https://…", activates_default=True, width_chars=46)
    clip = win.get_clipboard()

    def on_text(cb, res):
        try:
            text = cb.read_text_finish(res)
        except GLib.Error:
            return
        if text and "://" in text and not entry.get_text():
            entry.set_text(text.strip())
            entry.select_region(0, -1)

    clip.read_text_async(None, on_text)
    dlg.set_extra_child(entry)
    dlg.add_response("cancel", "Cancel")
    dlg.add_response("open", "Open")
    dlg.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("open")
    dlg.set_close_response("cancel")

    def on_response(_d, response):
        if response == "open" and entry.get_text().strip():
            callback(entry.get_text().strip())

    dlg.connect("response", on_response)
    dlg.present(win)


SHORTCUTS = [
    ("Playback", [
        ("Space", "Play / pause"),
        ("F4  /  Ctrl+W", "Stop"),
        ("Left / Right", "Seek 5 s"),
        ("Ctrl+Left / Ctrl+Right", "Seek 30 s"),
        ("Shift+Left / Shift+Right", "Seek 1 min"),
        ("Home", "Jump to start"),
        ("D / F", "Previous / next frame"),
        ("X / C / Z", "Slower / faster / normal speed"),
        ("[  /  ]  /  \\", "A-B repeat: set A / set B / clear"),
        ("Page Up / Page Down", "Previous / next file"),
        ("Ctrl+Page Up / Ctrl+Page Down", "Previous / next chapter"),
    ]),
    ("Audio", [
        ("Up / Down  ·  mouse wheel", "Volume"),
        ("M", "Mute"),
        ("Alt+A", "Next audio track"),
        ("Ctrl+=  /  Ctrl+-", "Audio delay ±50 ms"),
    ]),
    ("Subtitles", [
        ("Alt+H", "Show / hide subtitles"),
        ("Alt+L", "Next subtitle track"),
        (",  /  .", "Subtitle delay ±0.5 s"),
        ("/", "Reset subtitle delay"),
        ("Ctrl+Shift+S", "Load subtitle file"),
    ]),
    ("Video", [
        ("Enter  ·  double-click", "Fullscreen"),
        ("Esc", "Leave fullscreen"),
        ("Q", "Reset colors"),
        ("W / E", "Brightness − / +"),
        ("R / T", "Contrast − / +"),
        ("Y / U", "Saturation − / +"),
        ("I / O", "Hue − / +"),
        ("Ctrl+E", "Save screenshot"),
    ]),
    ("General", [
        ("Ctrl+O", "Open files"),
        ("Ctrl+F", "Open folder"),
        ("Ctrl+U", "Open URL"),
        ("Ctrl+V", "Play path or URL from clipboard"),
        ("F6", "Playlist"),
        ("Tab", "Show status"),
        ("Ctrl+F1", "Media info"),
        ("F5", "Preferences"),
        ("F1", "This list"),
        ("Ctrl+Q", "Quit"),
        ("Right-click", "Full menu"),
    ]),
]


def show_shortcuts(win):
    page = Adw.PreferencesPage()
    for title, rows in SHORTCUTS:
        group = Adw.PreferencesGroup(title=title)
        for keys, desc in rows:
            row = Adw.ActionRow(title=desc)
            row.add_suffix(Gtk.Label(label=keys, css_classes=["dim-label", "monospace"]))
            group.add(row)
        page.add(group)
    _dialog("Keyboard Shortcuts", page, width=520, height=640).present(win)


class PreferencesDialog:
    def __init__(self, win):
        self.win = win
        s = win.settings
        dlg = Adw.PreferencesDialog(title="Preferences")

        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        play = Adw.PreferencesGroup(title="Playback")
        play.add(self._switch("Resume where you left off", "resume_playback"))
        play.add(self._switch("Add other files from the same folder", "auto_add_folder"))
        play.add(self._switch("Hardware video decoding (VA-API)", "hardware_decoding",
                              "Takes effect on the next file", self._hw_changed))
        play.add(self._spin("Short seek (seconds)", "seek_short", 1, 60))
        play.add(self._spin("Long seek (seconds)", "seek_long", 5, 600))
        page.add(play)

        subs = Adw.PreferencesGroup(title="Subtitles")
        subs.add(self._switch("Load matching subtitle files", "auto_load_subtitles"))
        font_row = Adw.ActionRow(title="Subtitle font")
        font_btn = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), valign=Gtk.Align.CENTER)
        font_btn.set_font_desc(Pango.FontDescription.from_string(s["subtitle_font"]))
        font_btn.connect("notify::font-desc", self._font_changed)
        font_row.add_suffix(font_btn)
        subs.add(font_row)
        page.add(subs)

        shots = Adw.PreferencesGroup(title="Screenshots")
        self.shot_row = Adw.ActionRow(title="Save folder", subtitle=s["screenshot_dir"])
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Choose folder")
        pick.connect("clicked", self._pick_folder)
        self.shot_row.add_suffix(pick)
        shots.add(self.shot_row)
        page.add(shots)

        dlg.add(page)
        self.dialog = dlg
        dlg.connect("closed", lambda _d: s.save())

    def _switch(self, title, key, subtitle=None, on_change=None):
        row = Adw.SwitchRow(title=title, active=self.win.settings[key])
        if subtitle:
            row.set_subtitle(subtitle)

        def changed(r, _p):
            self.win.settings[key] = r.get_active()
            if on_change:
                on_change(r.get_active())

        row.connect("notify::active", changed)
        return row

    def _spin(self, title, key, lo, hi):
        row = Adw.SpinRow.new_with_range(lo, hi, 1)
        row.set_title(title)
        row.set_value(self.win.settings[key])
        row.connect("notify::value", lambda r, _p: self.win.settings.__setitem__(key, int(r.get_value())))
        return row

    def _hw_changed(self, enabled):
        from .engine import set_hardware_decoding
        set_hardware_decoding(enabled)

    def _font_changed(self, btn, _p):
        desc = btn.get_font_desc()
        if desc:
            self.win.settings["subtitle_font"] = desc.to_string()
            self.win.engine.set_subtitle_font(desc.to_string())

    def _pick_folder(self, _btn):
        fd = Gtk.FileDialog(title="Screenshot folder")
        fd.set_initial_folder(Gio.File.new_for_path(self.win.settings["screenshot_dir"]))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self.win.settings["screenshot_dir"] = folder.get_path()
            self.shot_row.set_subtitle(folder.get_path())

        fd.select_folder(self.win, None, done)

    def present(self):
        self.dialog.present(self.win)
