"""Unit tests for the saved-playlist library (no GTK, no network)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astra_player.library import Library, make_item  # noqa: E402

YT = "https://www.youtube.com/watch?v="


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="astra-lib-")) / "playlists.json"
        self.lib = Library(self.path)

    def test_create_and_persist(self):
        pl = self.lib.create("Lofi", [make_item(YT + "a", "A", 120), make_item(YT + "b", "B")])
        again = Library(self.path)
        self.assertEqual([p.name for p in again.playlists], ["Lofi"])
        self.assertEqual([i["title"] for i in again.get(pl.id).items], ["A", "B"])
        self.assertEqual(again.get(pl.id).items[0]["duration"], 120)

    def test_unique_names(self):
        self.lib.create("Mix")
        self.assertEqual(self.lib.create("mix").name, "mix (2)")
        self.assertEqual(self.lib.create("Mix").name, "Mix (3)")
        self.assertEqual(self.lib.create("  ").name, "New playlist")

    def test_add_skips_duplicates(self):
        pl = self.lib.create("Q")
        self.assertEqual(self.lib.add_items(pl.id, [make_item(YT + "a"), make_item(YT + "a")]), 1)
        self.assertEqual(self.lib.add_items(pl.id, [make_item(YT + "a"), make_item(YT + "c")]), 1)
        self.assertEqual(len(self.lib.get(pl.id).items), 2)

    def test_remove_move_rename_delete(self):
        pl = self.lib.create("X", [make_item(YT + c, c) for c in "abc"])
        self.assertTrue(self.lib.move_item(pl.id, 2, 0))
        self.assertEqual([i["title"] for i in pl.items], ["c", "a", "b"])
        self.assertTrue(self.lib.remove_item(pl.id, 1))
        self.assertFalse(self.lib.remove_item(pl.id, 9))
        self.lib.rename(pl.id, "Renamed")
        reloaded = Library(self.path)
        self.assertEqual(reloaded.get(pl.id).name, "Renamed")
        self.assertEqual([i["title"] for i in reloaded.get(pl.id).items], ["c", "b"])
        self.assertTrue(reloaded.delete(pl.id))
        self.assertEqual(Library(self.path).playlists, [])

    def test_corrupt_file_is_tolerated(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(Library(self.path).playlists, [])
        self.path.write_text('{"playlists": [{"name": "no id"}, {"id": "1", "name": "ok", '
                             '"items": [{"title": "missing uri"}, {"uri": "x://y"}]}]}', encoding="utf-8")
        lib = Library(self.path)
        self.assertEqual([p.name for p in lib.playlists], ["ok"])
        self.assertEqual(lib.playlists[0].items[0]["title"], "x://y")


if __name__ == "__main__":
    unittest.main()
