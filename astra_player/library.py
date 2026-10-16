"""Saved playlists ("library"), kept as JSON in the XDG data folder.

Each playlist has a stable id, a name, and items of {uri, title, duration,
thumbnail}. Items can be YouTube pages, streams or local files. No GTK here,
so the model is unit tested on its own.
"""

import json
import os
import time
import uuid
from pathlib import Path

from .settings import DATA_HOME

LIBRARY_FILE = DATA_HOME / "astra-player" / "playlists.json"


class SavedPlaylist:
    __slots__ = ("id", "name", "created", "items")

    def __init__(self, id, name, created=None, items=None):
        self.id = id
        self.name = name
        self.created = created or time.time()
        self.items = items or []

    def to_json(self):
        return {"id": self.id, "name": self.name, "created": self.created, "items": self.items}

    @classmethod
    def from_json(cls, data):
        items = [dict(uri=str(i["uri"]), title=str(i.get("title") or i["uri"]),
                      duration=i.get("duration"), thumbnail=i.get("thumbnail"))
                 for i in data.get("items", []) if isinstance(i, dict) and i.get("uri")]
        return cls(str(data["id"]), str(data.get("name") or "Playlist"), data.get("created"), items)


def make_item(uri, title=None, duration=None, thumbnail=None):
    return {"uri": uri, "title": title or uri, "duration": duration, "thumbnail": thumbnail}


class Library:
    def __init__(self, path=None):
        self.path = Path(path) if path else LIBRARY_FILE
        self.playlists = []
        self.load()

    # ------------------------------------------------------------ storage

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.playlists = []
        for p in data.get("playlists", []) if isinstance(data, dict) else []:
            try:
                self.playlists.append(SavedPlaylist.from_json(p))
            except (KeyError, TypeError):
                continue

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"version": 1, "playlists": [p.to_json() for p in self.playlists]}
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # -------------------------------------------------------------- edits

    def get(self, pid):
        return next((p for p in self.playlists if p.id == pid), None)

    def unique_name(self, name):
        name = (name or "").strip() or "New playlist"
        taken = {p.name.casefold() for p in self.playlists}
        if name.casefold() not in taken:
            return name
        n = 2
        while f"{name} ({n})".casefold() in taken:
            n += 1
        return f"{name} ({n})"

    def create(self, name, items=None):
        pl = SavedPlaylist(uuid.uuid4().hex[:12], self.unique_name(name))
        self.playlists.append(pl)
        if items:
            self.add_items(pl.id, items, save=False)
        self.save()
        return pl

    def rename(self, pid, name):
        pl = self.get(pid)
        name = (name or "").strip()
        if pl is None or not name or name == pl.name:
            return pl
        pl.name = self.unique_name(name)
        self.save()
        return pl

    def delete(self, pid):
        before = len(self.playlists)
        self.playlists = [p for p in self.playlists if p.id != pid]
        if len(self.playlists) != before:
            self.save()
            return True
        return False

    def add_items(self, pid, items, save=True):
        """Append items not already in the playlist. Returns how many were added."""
        pl = self.get(pid)
        if pl is None:
            return 0
        known = {i["uri"] for i in pl.items}
        added = 0
        for item in items:
            if item["uri"] in known:
                continue
            pl.items.append(make_item(item["uri"], item.get("title"), item.get("duration"),
                                      item.get("thumbnail")))
            known.add(item["uri"])
            added += 1
        if save:
            self.save()
        return added

    def remove_item(self, pid, index):
        pl = self.get(pid)
        if pl is None or not 0 <= index < len(pl.items):
            return False
        del pl.items[index]
        self.save()
        return True

    def move_item(self, pid, src, dst):
        pl = self.get(pid)
        if pl is None or not (0 <= src < len(pl.items) and 0 <= dst < len(pl.items)):
            return False
        pl.items.insert(dst, pl.items.pop(src))
        self.save()
        return True
