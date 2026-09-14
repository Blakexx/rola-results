"""The index's contract, on a temporary backend: every sample is a row, only changed records are read again, a vanished
record is dropped, views are created in dependency order, and an unknown format is refused."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from . import index
from .store import Store, key


class IndexContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "records"
        self.views = Path(self.tmp.name) / "views"
        self.views.mkdir()
        self.store = Store("tool", self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def sql(self, q: str, params: tuple = ()) -> list:
        return index.query(q, params, self.root)[1]

    def test_every_sample_is_a_row_with_its_json_fields_queryable(self) -> None:
        self.store.put({"cell": "a"}, output={"ms": 1.5}, provenance={"git_sha": "x"})
        self.store.put({"cell": "a"}, error="boom")
        rows = self.sql("SELECT n, ok, json_extract(output, '$.ms'), json_extract(provenance, '$.git_sha'), error "
                        "FROM samples ORDER BY n")
        self.assertEqual(rows, [(0, 1, 1.5, "x", None), (1, 0, None, None, "boom")])
        cond, params = index.matching("tool", {"cell": "a"})
        self.assertEqual(len(self.sql(f"SELECT 1 FROM samples s JOIN records r USING (location, key) WHERE {cond}",
                                      tuple(params))), 2)

    def test_only_changed_records_are_read_and_vanished_ones_dropped(self) -> None:
        self.store.put({"cell": "a"}, output=1)
        self.store.put({"cell": "b"}, output=2)
        self.assertEqual(index.build(self.root)["read"], 2)
        self.assertEqual(index.build(self.root)["read"], 0)
        time.sleep(0.01)
        self.store.put({"cell": "a"}, output=3)
        self.assertEqual(index.build(self.root)["read"], 1)
        self.store.path(key({"cell": "b"})).unlink()
        self.assertEqual(index.build(self.root)["dropped"], 1)
        self.assertEqual(self.sql("SELECT count(*) FROM samples"), [(2,)])

    def test_a_view_reading_another_view_is_created_whatever_its_name(self) -> None:
        (self.views / "a_outer.sql").write_text("CREATE VIEW a_outer AS SELECT count(*) AS c FROM z_inner;")
        (self.views / "z_inner.sql").write_text("CREATE VIEW z_inner AS SELECT * FROM samples WHERE ok;")
        self.store.put({"cell": "a"}, output=1)
        self.assertEqual(self.sql("SELECT c FROM a_outer"), [(1,)])

    def test_a_record_of_an_unknown_format_is_refused(self) -> None:
        self.store.put({"cell": "a"}, output=1)
        path = self.store.path(key({"cell": "a"}))
        record = json.loads(path.read_text())
        record["format"] = 99
        path.write_text(json.dumps(record))
        with self.assertRaises(SystemExit):
            index.build(self.root)

    def test_a_where_path_is_names_only(self) -> None:
        with self.assertRaises(ValueError):
            index.matching("tool", {"cell') OR 1=1 --": "x"})


if __name__ == "__main__":
    unittest.main()
