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

    def test_instrument_metrics_is_every_number_long_and_diff_cells_is_every_verdict(self) -> None:
        """The suite reads its own instruments through one long view: a phase time, a counter, a SASS count and a
        register peak are rows of one shape, keyed by (instrument, cell, metric); a stored diff is rows per cell and
        quantity with its verdict, never its tensors."""
        import json

        from .store import Store

        phases = self.root.parent / "phases.json"
        phases.write_text(json.dumps({"cell-a": {"cell": "cell-a", "total": 3.0, "cta_windows": 2, "launches": 1,
                                                  "per_phase": {"fold": 1.0, "head": 2.0}}}))
        Store("rola/phases", self.root).put({"tool": "phases"}, output_file=phases, provenance={"run": "r1"})
        sass = self.root.parent / "sass.json"
        sass.write_text(json.dumps({"": {"arm.cubin": {"ok": True, "functions": {"kern": {"hmma": 7, "instr": 90,
                                                                                            "calls": 0}}}}}))
        Store("rola/sass", self.root).put({"tool": "sass"}, output_file=sass, provenance={"run": "r1"})
        Store("rola/carry-vs-oracle", self.root).put(
            {"diff": 1}, provenance={"run": "r1"},
            output={"strategy": "per-slot", "expect": "same", "held": False, "compared": 1, "quantities": 2,
                    "minimum": 2, "differing": [], "unusable": ["cell-b"],
                    "cells": {"cell-a": {"status": "ok", "same": True,
                                         "quantities": {"num": {"same": True, "slots": 4, "failed": 0},
                                                        "state": {"same": False, "ratio": 2.5, "at": [1, 2],
                                                                  "bound_by": "the envelope", "failed": 1, "slots": 4}}},
                              "cell-b": {"status": "unusable", "left": "RuntimeError: no arm"}}})
        index.build(self.root, views=Path(__file__).resolve().parents[1] / "views")
        rows = self.sql("SELECT instrument, cell, metric, value FROM instrument_metrics ORDER BY metric")
        self.assertIn(("phases", "cell-a", "phase.fold", 1.0), rows)
        self.assertIn(("phases", "cell-a", "total", 3.0), rows)
        self.assertIn(("sass", None, "sass.arm.cubin.kern.hmma", 7), rows)
        self.assertEqual(len(rows), 8)
        verdicts = self.sql("SELECT cell, cell_status, quantity, same, ratio, bound_by, held FROM diff_cells "
                            "ORDER BY cell, quantity")
        self.assertEqual(verdicts, [("cell-a", "ok", "num", 1, None, None, 0),
                                    ("cell-a", "ok", "state", 0, 2.5, "the envelope", 0),
                                    ("cell-b", "unusable", None, None, None, None, 0)])

    def test_instruments_compares_one_run_to_another_by_metric(self) -> None:
        import json

        from .instruments import compare
        from .store import Store

        for run, fold in (("r1", 1.0), ("r2", 1.5)):
            f = self.root.parent / f"phases-{run}.json"
            f.write_text(json.dumps({"c": {"per_phase": {"fold": fold, "head": 2.0}, "total": fold + 2.0}}))
            Store("rola/phases", self.root).put({"tool": "phases", "run": run}, output_file=f, provenance={"run": run})
        index.build(self.root, views=Path(__file__).resolve().parents[1] / "views")
        rows = compare(self.root, against="r1", run="r2", min_change=0.1)
        self.assertEqual([(r["metric"], r["value"], r["reference"], round(r["change"], 3)) for r in rows],
                         [("phase.fold", 1.5, 1.0, 0.5), ("total", 3.5, 3.0, 0.167)])

if __name__ == "__main__":
    unittest.main()
