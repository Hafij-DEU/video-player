"""Secondary dialogs: equalizer, color adjust, media info, preferences, shortcuts, URL, Whisper."""

import threading

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import whisper, youtube
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
    dlg = Adw.AlertDialog(heading="Open URL", body="Stream address, YouTube link, file path, or ytsearch:words")
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


def confirm_model_download(win, name, on_yes):
    """Ask before fetching a Whisper model; nothing is downloaded unless the user agrees."""
    size = whisper.fmt_size(whisper.MODELS[name][0])
    dlg = Adw.AlertDialog(
        heading="Download speech model?",
        body=(f"Making subtitles needs the Whisper \u201c{name}\u201d model ({size}). "
              f"It is downloaded once from huggingface.co and kept in "
              f"{whisper.MODELS_DIR}. Speech recognition then runs offline on this computer.\n\n"
              f"You can pick a smaller or more accurate model in Preferences."))
    dlg.add_response("cancel", "Cancel")
    dlg.add_response("download", f"Download {size}")
    dlg.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("download")
    dlg.set_close_response("cancel")
    dlg.connect("response", lambda _d, r: on_yes() if r == "download" else None)
    dlg.present(win)
    return dlg


def _mb(n):
    return f"{n / 1e6:.1f} MB"


def confirm_ytdlp_download(win, reason, on_yes, on_no=None):
    """Ask before fetching yt-dlp; nothing is downloaded unless the user agrees."""
    def body(size, exact):
        return (f"{reason}Astra Player can download the official yt-dlp "
                f"({'' if exact else 'about '}{_mb(size)}) from github.com/yt-dlp/yt-dlp, check it "
                f"against the release checksums and keep it in {youtube.MANAGED_DIR}. It then "
                f"looks for a new version once a week, because YouTube changes often.\n\n"
                f"You can turn this off in Preferences \u203a YouTube.")

    dlg = Adw.AlertDialog(heading="Download yt-dlp?", body=body(youtube.MANAGED_SIZE, False))
    dlg.add_response("cancel", "Not now")
    dlg.add_response("download", f"Download {_mb(youtube.MANAGED_SIZE)}")
    dlg.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("download")
    dlg.set_close_response("cancel")

    answered = []

    def on_response(_d, response):
        if answered:  # closing after a response must not count as a second answer
            return
        answered.append(response)
        if response == "download":
            on_yes()
        elif on_no:
            on_no()

    def show_size(size):
        dlg.set_body(body(size, True))
        dlg.set_response_label("download", f"Download {_mb(size)}")
        return False

    def fetch_size():
        size = youtube.remote_size()  # a HEAD request; the file itself is not fetched
        if size:
            GLib.idle_add(show_size, size)

    dlg.connect("response", on_response)
    threading.Thread(target=fetch_size, daemon=True).start()
    dlg.present(win)
    return dlg


def youtube_consent(win, browsers, offer_ytdlp, on_allow):
    """One-time consent to use a browser's YouTube login; on_allow(spec, get_ytdlp)."""
    labels = [label for label, _spec in browsers]

    def body(i):
        return (f"YouTube needs a sign-in for this connection. Use your YouTube login from "
                f"{labels[i]}?\n\nyt-dlp reads that browser\u2019s cookies on this computer and "
                f"sends them only to YouTube. If that browser isn\u2019t signed in, Astra Player "
                f"tries your other browsers. You can change this in Preferences \u203a YouTube.")

    dlg = Adw.AlertDialog(heading="Sign in to YouTube?", body=body(0))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    dropdown = Gtk.DropDown.new_from_strings(labels)
    dropdown.connect("notify::selected", lambda d, _p: dlg.set_body(body(d.get_selected())))
    box.append(dropdown)
    check = None
    if offer_ytdlp:
        check = Gtk.CheckButton(label=f"Also download the latest yt-dlp (about "
                                      f"{_mb(youtube.MANAGED_SIZE)}) and keep it up to date")
        box.append(check)
    dlg.set_extra_child(box)
    dlg.add_response("later", "Not now")
    dlg.add_response("allow", "Allow")
    dlg.set_response_appearance("allow", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("allow")
    dlg.set_close_response("later")
    dlg.connect("response", lambda _d, r: on_allow(browsers[dropdown.get_selected()][1],
                                                   bool(check and check.get_active()))
                if r == "allow" else None)
    dlg.browser_dropdown, dlg.ytdlp_check = dropdown, check  # for the self-test
    dlg.present(win)
    return dlg


def whisper_missing(win):
    dlg = Adw.AlertDialog(heading="Speech engine not installed",
                          body="Astra Player uses whisper.cpp to turn speech into subtitles offline.")
    hint = Gtk.Label(label=whisper.install_hint(), selectable=True, xalign=0, wrap=True,
                     css_classes=["monospace"])
    dlg.set_extra_child(hint)
    dlg.add_response("close", "Close")
    dlg.present(win)
    return dlg


SHORTCUTS = [
    ("Playback", [
        ("Space", "Play / pause"),
        ("Ctrl+L", "Repeat: once / file / playlist"),
        ("Ctrl+R", "Record: start, then stop and save that portion"),
        ("Ctrl+Shift+R", "Save the A-B segment to a file"),
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
        ("Menu \u203a Subtitles", "Generate subtitles (Whisper)"),
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
        ("Ctrl+F", "Play a folder"),
        ("Ctrl+P", "Picture in picture"),
        ("Ctrl+B", "Saved playlists"),
        ("Ctrl+U", "Open URL"),
        ("Ctrl+Y", "Search YouTube"),
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
        page.add(self._whisper_group())
        page.add(self._youtube_group())

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

    def _whisper_group(self):
        s = self.win.settings
        backend = whisper.find_backend()
        group = Adw.PreferencesGroup(
            title="Speech to text (Whisper)",
            description="Subtitles \u203a Generate subtitles turns speech into an .srt file offline.")
        engine = Adw.ActionRow(title="Speech engine", subtitle=whisper.backend_label(backend))
        if backend is None:
            engine.set_subtitle("Not installed: sudo apt install whisper.cpp, "
                                "or pip install --user pywhispercpp")
        group.add(engine)

        names = list(whisper.MODELS)
        self.model_row = Adw.ComboRow(
            title="Model", subtitle="Tiny is fastest, small most accurate. "
                                    "Downloaded on first use, after you confirm")
        self.model_row.set_model(Gtk.StringList.new([self._model_label(n) for n in names]))
        self.model_row.set_selected(names.index(s["whisper_model"]) if s["whisper_model"] in names else 1)
        self.model_row.connect("notify::selected",
                               lambda r, _p: s.__setitem__("whisper_model", names[r.get_selected()]))
        group.add(self.model_row)

        codes = [c for c, _l in whisper.LANGUAGES]
        lang = Adw.ComboRow(title="Spoken language")
        lang.set_model(Gtk.StringList.new([label for _c, label in whisper.LANGUAGES]))
        lang.set_selected(codes.index(s["whisper_language"]) if s["whisper_language"] in codes else 0)
        lang.connect("notify::selected", lambda r, _p: s.__setitem__("whisper_language", codes[r.get_selected()]))
        group.add(lang)

        group.add(self._switch("Translate to English", "whisper_translate"))
        gpu = self._switch("Use the GPU (Vulkan)", "whisper_gpu",
                           "whisper-cli with libggml0-backend-vulkan; otherwise the CPU is used")
        gpu.set_sensitive(backend is not None and backend[0] == "cli")
        group.add(gpu)

        folder = Adw.ActionRow(title="Model folder", subtitle=str(whisper.MODELS_DIR))
        open_btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text="Open folder")
        open_btn.connect("clicked", self._open_models)
        folder.add_suffix(open_btn)
        group.add(folder)
        return group

    @staticmethod
    def _model_label(name):
        size = whisper.fmt_size(whisper.MODELS[name][0])
        mark = " \u2713" if whisper.model_installed(name) else ""
        return f"{name} ({size}){mark}"

    def _open_models(self, _btn):
        whisper.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        Gtk.FileLauncher(file=Gio.File.new_for_path(str(whisper.MODELS_DIR))).launch(self.win, None, None)

    def _youtube_group(self):
        group = Adw.PreferencesGroup(
            title="YouTube",
            description="If YouTube says “Sign in to confirm you’re not a bot”, let yt-dlp use "
                        "the YouTube login of a browser you are signed in with. The cookies are "
                        "read on this computer only and are never sent anywhere but YouTube.")
        self._yt_sources = [("", "Off")] + [(spec, label) for label, spec in youtube.detect_browsers()]
        current = self.win.settings["youtube_cookies"]
        if current.startswith("file:"):
            self._yt_sources.append((current, f"File: {current[5:].rsplit('/', 1)[-1]}"))
        elif current and current not in [k for k, _ in self._yt_sources]:
            self._yt_sources.append((current, current))
        labels = [label for _k, label in self._yt_sources]
        row = Adw.ComboRow(title="Use sign-in from", model=Gtk.StringList.new(labels))
        keys = [k for k, _ in self._yt_sources]
        row.set_selected(keys.index(current) if current in keys else 0)
        row.connect("notify::selected", self._yt_source_changed)
        self._yt_row = row
        group.add(row)

        file_row = Adw.ActionRow(title="Use a cookies.txt file",
                                 subtitle="Exported from your browser in Netscape format")
        pick = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Choose cookies.txt")
        pick.connect("clicked", self._pick_cookies_file)
        file_row.add_suffix(pick)
        group.add(file_row)

        self._ytdlp_busy = False
        self._ytdlp_row = Adw.SwitchRow(
            title="Keep yt-dlp up to date", active=self.win.settings["ytdlp_managed"],
            subtitle=f"Use Astra Player\u2019s own copy from github.com/yt-dlp (about "
                     f"{youtube.MANAGED_SIZE / 1e6:.0f} MB), checked weekly")
        self._ytdlp_row.connect("notify::active", self._ytdlp_toggled)
        group.add(self._ytdlp_row)
        self._ytdlp_info = Adw.ActionRow(title="yt-dlp in use", subtitle="\u2026",
                                         subtitle_selectable=True)
        group.add(self._ytdlp_info)
        self._refresh_ytdlp_info()
        return group

    def _refresh_ytdlp_info(self, *_args):
        def work():
            prog = youtube.ytdlp_path()
            version = youtube.ytdlp_version(prog) if prog else None
            hint = youtube.SECRETSTORAGE_HINT if youtube.keyring_missing() else ""
            GLib.idle_add(show, prog, version, hint)

        def show(prog, version, hint):
            text = f"{version or 'unknown version'}  \u00b7  {prog}" if prog else "Not installed"
            self._ytdlp_info.set_subtitle(GLib.markup_escape_text(text + (f"\n{hint}" if hint else "")))
            return False

        threading.Thread(target=work, daemon=True).start()

    def _ytdlp_toggled(self, row, _pspec):
        if self._ytdlp_busy:
            return
        s, win = self.win.settings, self.win
        if not row.get_active():
            s["ytdlp_managed"] = False
            youtube.managed_enabled = False
            self._refresh_ytdlp_info()
            return
        if youtube.managed_version():  # downloaded before: no need to ask again
            s["ytdlp_managed"] = True
            youtube.managed_enabled = True
            self._refresh_ytdlp_info()
            if youtube.update_due(s["ytdlp_last_check"]):
                win._download_ytdlp(self._refresh_ytdlp_info, quiet=True)
            return

        def revert():
            self._ytdlp_busy = True
            row.set_active(False)
            self._ytdlp_busy = False

        win.get_ytdlp(lambda ok: self._refresh_ytdlp_info() if ok else revert(),
                      reason="Astra Player will use its own yt-dlp instead of the one installed "
                             "on the system. ")

    def _set_yt_source(self, source):
        self.win.settings["youtube_cookies"] = source
        youtube.cookie_source = source
        self.win._yt_attempt = None

    def _yt_source_changed(self, row, _pspec):
        idx = row.get_selected()
        if 0 <= idx < len(self._yt_sources):
            self._set_yt_source(self._yt_sources[idx][0])

    def _pick_cookies_file(self, _btn):
        fd = Gtk.FileDialog(title="Choose cookies.txt")

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            source = f"file:{f.get_path()}"
            self._yt_sources.append((source, f"File: {f.get_basename()}"))
            self._yt_row.get_model().append(f"File: {f.get_basename()}")
            self._yt_row.set_selected(len(self._yt_sources) - 1)

        fd.open(self.win, None, done)

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
