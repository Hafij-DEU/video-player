"""Search YouTube dialog: results from yt-dlp, thumbnails loaded in the background."""

import queue
import threading
import urllib.request

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import youtube
from .library import make_item
from .library_dialog import choose_playlist

THUMB_W, THUMB_H = 128, 72
THUMB_THREADS = 4


class SearchDialog:
    def __init__(self, win, query=""):
        self.win = win
        self.results = []
        self._gen = 0          # bumped by every search and on close; stale work is dropped
        self._proc = None
        self._thumbs = queue.Queue()
        self._thumb_threads = []

        self.entry = Gtk.SearchEntry(placeholder_text="Search YouTube", hexpand=True,
                                     text=query or "")
        self.entry.connect("activate", lambda _e: self.search(self.entry.get_text()))
        go = Gtk.Button(icon_name="system-search-symbolic", tooltip_text="Search")
        go.add_css_class("suggested-action")
        go.connect("clicked", lambda _b: self.search(self.entry.get_text()))
        bar = Gtk.Box(spacing=6, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        bar.append(self.entry)
        bar.append(go)
        self.save_all_btn = Gtk.Button(icon_name="bookmark-new-symbolic", sensitive=False,
                                       tooltip_text="Save all results as a playlist")
        self.save_all_btn.connect("clicked", lambda _b: self.save_all())
        bar.append(self.save_all_btn)
        self._query = ""

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,
                                   activate_on_single_click=True,
                                   margin_start=12, margin_end=12, margin_top=6, margin_bottom=12)
        self.listbox.add_css_class("boxed-list")
        self.listbox.connect("row-activated", lambda _l, row: self.play(row.get_index()))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=900, child=self.listbox))

        self.spinner = Gtk.Spinner(width_request=32, height_request=32,
                                   halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        searching = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        searching.append(self.spinner)
        searching.append(Gtk.Label(label="Searching YouTube…", css_classes=["dim-label"]))

        self.status = Adw.StatusPage(icon_name="system-search-symbolic", title="Search YouTube",
                                     description="Type what to watch and press Enter. "
                                                 "Free, no account needed.")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.status, "status")
        self.stack.add_named(searching, "searching")
        self.stack.add_named(scroller, "results")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.add_top_bar(bar)
        view.set_content(self.toasts)

        self.dialog = Adw.Dialog(title="Search YouTube", content_width=680, content_height=600)
        self.dialog.set_child(view)
        self.dialog.set_focus(self.entry)
        self.dialog.connect("closed", self._on_closed)

        group = Gio.SimpleActionGroup()
        for name, fn in (("play", self.play), ("add", self.add), ("save", self.save)):
            act = Gio.SimpleAction.new(name, GLib.VariantType("i"))
            act.connect("activate", lambda _a, p, fn=fn: fn(p.get_int32()))
            group.add_action(act)
        self.dialog.insert_action_group("yt", group)

    def present(self):
        self.dialog.present(self.win)
        if self.entry.get_text().strip():
            self.search(self.entry.get_text())
        return self

    # ------------------------------------------------------------ search
    def search(self, query):
        query = query.strip()
        if not query:
            return
        if not youtube.have_ytdlp():
            self.toast("Install yt-dlp to search YouTube")
            return
        self._cancel()
        gen = self._gen
        self.listbox.remove_all()
        self.results = []
        self._query = query
        self.save_all_btn.set_sensitive(False)
        self.spinner.start()
        self.stack.set_visible_child_name("searching")

        def remember(proc):
            if gen == self._gen:
                self._proc = proc
            else:  # cancelled before yt-dlp started
                proc.kill()

        def worker():
            try:
                results, err = youtube.search(query, on_process=remember), None
            except (RuntimeError, OSError) as exc:
                results, err = [], str(exc)
            GLib.idle_add(self._show, gen, query, results, err)

        threading.Thread(target=worker, daemon=True).start()

    def _show(self, gen, query, results, err):
        if gen != self._gen:
            return False
        self._proc = None
        self.spinner.stop()
        self.results = results
        if err and youtube.is_bot_block(err):
            err = ("YouTube is limiting this connection. Play a video to sign in with a "
                   "browser, choose one in Preferences › YouTube, or wait a few hours.")
            self.toast(err)
        elif err:
            self.toast(f"YouTube search failed: {err}")
        if not results:
            self.status.set_title("No results" if not err else "Search failed")
            self.status.set_description(f"Nothing found for “{query}”."
                                        if not err else err)
            self.stack.set_visible_child_name("status")
            return False
        for i, res in enumerate(results):
            self.listbox.append(self._row(i, res))
        self.save_all_btn.set_sensitive(True)
        self.stack.set_visible_child_name("results")
        self._start_thumbs(gen)
        return False

    def _row(self, index, res):
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                          width_request=THUMB_W, height_request=THUMB_H,
                          valign=Gtk.Align.CENTER)
        frame = Gtk.Frame(child=pic, valign=Gtk.Align.CENTER)

        title = Gtk.Label(label=res.title, xalign=0, wrap=True, lines=2,
                          ellipsize=Pango.EllipsizeMode.END,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, tooltip_text=res.title)
        title.add_css_class("heading")
        meta = Gtk.Label(label=youtube.describe(res), xalign=0,
                         ellipsize=Pango.EllipsizeMode.END)
        meta.add_css_class("dim-label")
        meta.add_css_class("caption")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True,
                       valign=Gtk.Align.CENTER)
        text.append(title)
        text.append(meta)

        def button(icon, tip, action):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER,
                           action_name=action, action_target=GLib.Variant.new_int32(index))
            b.add_css_class("flat")
            b.add_css_class("circular")
            return b

        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        box.append(frame)
        box.append(text)
        box.append(button("media-playback-start-symbolic", "Play", "yt.play"))
        box.append(button("list-add-symbolic", "Add to play queue", "yt.add"))
        box.append(button("bookmark-new-symbolic", "Save to a playlist", "yt.save"))

        row = Gtk.ListBoxRow(child=box, activatable=True)
        row.thumb = pic

        menu = Gio.Menu()
        it = Gio.MenuItem.new("Play", None)
        it.set_action_and_target_value("yt.play", GLib.Variant.new_int32(index))
        menu.append_item(it)
        it = Gio.MenuItem.new("Add to play queue", None)
        it.set_action_and_target_value("yt.add", GLib.Variant.new_int32(index))
        menu.append_item(it)
        it = Gio.MenuItem.new("Save to a playlist…", None)
        it.set_action_and_target_value("yt.save", GLib.Variant.new_int32(index))
        menu.append_item(it)
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_has_arrow(False)
        popover.set_parent(row)

        def on_right_click(gesture, _n, x, y):
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
            popover.set_pointing_to(rect)
            popover.popup()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", on_right_click)
        row.add_controller(click)
        return row

    # ------------------------------------------------------------ thumbnails
    def _start_thumbs(self, gen):
        for i, res in enumerate(self.results):
            if res.thumbnail:
                self._thumbs.put((gen, i, res.thumbnail))
        self._thumb_threads = [t for t in self._thumb_threads if t.is_alive()]
        while len(self._thumb_threads) < THUMB_THREADS:
            t = threading.Thread(target=self._thumb_worker, daemon=True)
            t.start()
            self._thumb_threads.append(t)

    def _thumb_worker(self):
        while True:
            try:
                gen, index, url = self._thumbs.get(timeout=5)
            except queue.Empty:
                return
            if gen != self._gen:
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read(1_000_000)
            except (OSError, ValueError):
                continue  # thumbnails are optional
            GLib.idle_add(self._set_thumb, gen, index, data)

    def _set_thumb(self, gen, index, data):
        if gen != self._gen:
            return False
        row = self.listbox.get_row_at_index(index)
        if row is None:
            return False
        try:
            row.thumb.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
        except GLib.Error:
            pass
        return False

    # ------------------------------------------------------------ actions
    def play(self, index):
        if 0 <= index < len(self.results):
            res = self.results[index]
            self.win.open_uris([res.url], titles={res.url: res.title})
            self.dialog.close()

    def add(self, index):
        if 0 <= index < len(self.results):
            res = self.results[index]
            self.win.open_uris([res.url], append=True, titles={res.url: res.title})
            self.toast(f"Added to playlist: {res.title}")

    @staticmethod
    def _item(res):
        return make_item(res.url, res.title, res.duration, res.thumbnail)

    def save(self, index):
        if not 0 <= index < len(self.results):
            return
        res = self.results[index]

        def done(pl, _created):
            added = self.win.library.add_items(pl.id, [self._item(res)])
            self.toast(f"Saved to “{pl.name}”" if added else f"Already in “{pl.name}”")

        choose_playlist(self.dialog, self.win.library, self._query, done, body=res.title)

    def save_all(self):
        if not self.results:
            return
        items = [self._item(r) for r in self.results]

        def done(pl, _created):
            added = self.win.library.add_items(pl.id, items)
            self.toast(f"Saved {added} videos to “{pl.name}”")

        choose_playlist(self.dialog, self.win.library, self._query, done,
                        heading="Save results as playlist", body=f"{len(items)} videos")

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def _cancel(self):
        self._gen += 1
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.kill()
        while True:
            try:
                self._thumbs.get_nowait()
            except queue.Empty:
                break

    def _on_closed(self, _dialog):
        self._cancel()
        self.spinner.stop()
