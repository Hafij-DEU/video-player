"""Saved playlists UI: browse, play, rename, delete; plus the "save to playlist" picker."""

from urllib.parse import urlparse

from gi.repository import Adw, GLib, Gtk

from .library import make_item
from .playlist import fmt_time

NEW = "__new__"


def choose_playlist(win, library, suggested_name, callback, heading="Save to playlist", body=None):
    """Ask which saved playlist to use (or name a new one). Calls callback(playlist, created)."""
    names = [p.name for p in library.playlists]
    dlg = Adw.AlertDialog(heading=heading, body=body or "")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    choice = Gtk.DropDown.new_from_strings(["New playlist…"] + names)
    entry = Gtk.Entry(text=suggested_name or "", placeholder_text="Playlist name",
                      activates_default=True)
    if names:
        box.append(choice)
    box.append(entry)

    def on_choice(dd, _pspec):
        entry.set_visible(dd.get_selected() == 0)

    choice.connect("notify::selected", on_choice)
    dlg.set_extra_child(box)
    dlg.add_response("cancel", "Cancel")
    dlg.add_response("save", "Save")
    dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("save")
    dlg.set_close_response("cancel")

    def on_response(_d, response):
        if response != "save":
            return
        idx = choice.get_selected() if names else 0
        if idx == 0:
            callback(library.create(entry.get_text()), True)
        else:
            callback(library.playlists[idx - 1], False)

    dlg.connect("response", on_response)
    dlg.present(win)
    entry.grab_focus()


def _confirm(win, heading, body, label, callback):
    dlg = Adw.AlertDialog(heading=heading, body=body)
    dlg.add_response("cancel", "Cancel")
    dlg.add_response("ok", label)
    dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    dlg.set_close_response("cancel")
    dlg.connect("response", lambda _d, r: callback() if r == "ok" else None)
    dlg.present(win)


def _ask_name(win, heading, current, callback):
    dlg = Adw.AlertDialog(heading=heading)
    entry = Gtk.Entry(text=current or "", activates_default=True)
    dlg.set_extra_child(entry)
    dlg.add_response("cancel", "Cancel")
    dlg.add_response("ok", "Save")
    dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("ok")
    dlg.set_close_response("cancel")
    dlg.connect("response", lambda _d, r: callback(entry.get_text()) if r == "ok" else None)
    dlg.present(win)
    entry.grab_focus()


def _item_subtitle(item):
    bits = []
    if item.get("duration"):
        bits.append(fmt_time(item["duration"]))
    uri = item["uri"]
    if uri.startswith("file://"):
        bits.append("local file")
    else:
        host = urlparse(uri).netloc.removeprefix("www.")
        if host:
            bits.append(host)
    return "  ·  ".join(bits)


def _icon_button(icon, tip, cb, destructive=False):
    b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER,
                   css_classes=["flat", "circular"])
    if destructive:
        b.add_css_class("error")
    b.connect("clicked", lambda _b: cb())
    return b


class LibraryDialog:
    def __init__(self, win):
        self.win = win
        self.library = win.library
        self.library.load()
        self.nav = Adw.NavigationView()
        self.toasts = Adw.ToastOverlay(child=self.nav)
        self.dialog = Adw.Dialog(title="Saved playlists", content_width=640, content_height=600,
                                 child=self.toasts)
        self._detail = None
        self.nav.add(self._build_index())

    def present(self):
        self.dialog.present(self.win)
        return self

    # ------------------------------------------------------------ index page

    def _build_index(self):
        self.index_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                      valign=Gtk.Align.START,
                                      margin_start=12, margin_end=12, margin_top=12, margin_bottom=12)
        self.index_list.connect("row-activated", lambda _l, row: self.open_playlist(row.pid))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=760, child=self.index_list))
        self.empty = Adw.StatusPage(icon_name="view-list-symbolic", title="No saved playlists",
                                    description="Save videos from YouTube search (Ctrl+Y) with the "
                                                "bookmark button, or save the current queue below.")
        self.index_stack = Gtk.Stack()
        self.index_stack.add_named(self.empty, "empty")
        self.index_stack.add_named(scroller, "list")

        header = Adw.HeaderBar()
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New empty playlist")
        new_btn.connect("clicked", lambda _b: _ask_name(self.dialog, "New playlist", "",
                                                         self._create_empty))
        header.pack_start(new_btn)

        save_queue = Gtk.Button(label="Save current queue as playlist…", halign=Gtk.Align.CENTER,
                                margin_top=6, margin_bottom=12, css_classes=["pill"])
        save_queue.connect("clicked", lambda _b: self.save_queue())
        self.save_queue_btn = save_queue

        view = Adw.ToolbarView(content=self.index_stack)
        view.add_top_bar(header)
        view.add_bottom_bar(save_queue)
        self.refresh_index()
        return Adw.NavigationPage(title="Saved playlists", tag="index", child=view)

    def refresh_index(self):
        self.index_list.remove_all()
        for pl in self.library.playlists:
            n = len(pl.items)
            row = Adw.ActionRow(title=GLib.markup_escape_text(pl.name),
                                subtitle=f"{n} item{'s' if n != 1 else ''}", activatable=True)
            row.pid = pl.id
            row.add_prefix(Gtk.Image(icon_name="view-list-symbolic"))
            row.add_suffix(_icon_button("media-playback-start-symbolic", "Play",
                                        lambda pid=pl.id: self.play(pid)))
            row.add_suffix(_icon_button("document-edit-symbolic", "Rename",
                                        lambda pid=pl.id: self.rename(pid)))
            row.add_suffix(_icon_button("user-trash-symbolic", "Delete playlist",
                                        lambda pid=pl.id: self.delete(pid), destructive=True))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            self.index_list.append(row)
        self.index_stack.set_visible_child_name("list" if self.library.playlists else "empty")
        self.save_queue_btn.set_sensitive(len(self.win.playlist) > 0)

    # ----------------------------------------------------------- detail page

    def open_playlist(self, pid):
        pl = self.library.get(pid)
        if pl is None:
            return
        self._detail_pid = pid
        self.detail_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                       valign=Gtk.Align.START,
                                       margin_start=12, margin_end=12, margin_top=12, margin_bottom=12)
        self.detail_list.connect("row-activated", lambda _l, row: self.play(pid, row.get_index()))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=760, child=self.detail_list))
        self.detail_empty = Adw.StatusPage(icon_name="view-list-symbolic", title="Empty playlist",
                                           description="Add videos from YouTube search or the "
                                                       "“Add what's playing” button.")
        self.detail_stack = Gtk.Stack()
        self.detail_stack.add_named(self.detail_empty, "empty")
        self.detail_stack.add_named(scroller, "list")

        header = Adw.HeaderBar()
        play_all = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Play all",
                              css_classes=["suggested-action"])
        play_all.connect("clicked", lambda _b: self.play(pid))
        header.pack_end(play_all)
        add_cur = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add what's playing")
        add_cur.connect("clicked", lambda _b: self.add_current(pid))
        header.pack_end(add_cur)

        view = Adw.ToolbarView(content=self.detail_stack)
        view.add_top_bar(header)
        self._detail = Adw.NavigationPage(title=pl.name, tag="detail", child=view)
        self._detail.connect("hidden", lambda _p: self.refresh_index())
        self.refresh_detail()
        self.nav.push(self._detail)

    def refresh_detail(self):
        pl = self.library.get(getattr(self, "_detail_pid", None))
        if pl is None or self._detail is None:
            return
        self._detail.set_title(pl.name)
        self.detail_list.remove_all()
        for i, item in enumerate(pl.items):
            row = Adw.ActionRow(title=GLib.markup_escape_text(item["title"]),
                                subtitle=GLib.markup_escape_text(_item_subtitle(item)),
                                activatable=True, title_lines=2)
            row.add_prefix(Gtk.Label(label=f"{i + 1}.", css_classes=["dim-label", "numeric"],
                                     width_chars=3, xalign=1))
            up = _icon_button("go-up-symbolic", "Move up", lambda i=i: self.move(pl.id, i, i - 1))
            up.set_sensitive(i > 0)
            row.add_suffix(up)
            row.add_suffix(_icon_button("list-remove-symbolic", "Remove from playlist",
                                        lambda i=i: self.remove_item(pl.id, i), destructive=True))
            self.detail_list.append(row)
        self.detail_stack.set_visible_child_name("list" if pl.items else "empty")

    # --------------------------------------------------------------- actions

    def play(self, pid, start=0):
        pl = self.library.get(pid)
        if pl is None or not pl.items:
            self.toast("This playlist is empty")
            return
        self.win.play_saved(pl, start)
        self.dialog.close()

    def rename(self, pid):
        pl = self.library.get(pid)
        if pl is None:
            return

        def done(name):
            self.library.rename(pid, name)
            self.refresh_index()
            self.refresh_detail()

        _ask_name(self.dialog, "Rename playlist", pl.name, done)

    def delete(self, pid):
        pl = self.library.get(pid)
        if pl is None:
            return

        def done():
            self.library.delete(pid)
            self.refresh_index()
            self.toast(f"Deleted “{pl.name}”")

        _confirm(self.dialog, "Delete playlist?",
                 f"“{pl.name}” and its {len(pl.items)} items will be removed from Astra Player. "
                 "Your video files are not touched.", "Delete", done)

    def remove_item(self, pid, index):
        self.library.remove_item(pid, index)
        self.refresh_detail()

    def move(self, pid, src, dst):
        if self.library.move_item(pid, src, dst):
            self.refresh_detail()

    def add_current(self, pid):
        entry = self.win.playlist.current
        if entry is None:
            self.toast("Nothing is playing")
            return
        added = self.library.add_items(pid, [make_item(entry.uri, entry.title)])
        self.refresh_detail()
        self.toast("Added" if added else "Already in this playlist")

    def _create_empty(self, name):
        self.library.create(name)
        self.refresh_index()

    def save_queue(self):
        items = self.win.queue_items()
        if not items:
            return

        def done(pl, created):
            added = self.library.add_items(pl.id, items)
            self.refresh_index()
            self.toast(f"Saved {added} item{'s' if added != 1 else ''} to “{pl.name}”")

        choose_playlist(self.dialog, self.library, "My playlist", done,
                        heading="Save current queue", body=f"{len(items)} items")

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=3))

