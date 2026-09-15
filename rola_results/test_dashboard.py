"""The dashboard reads composed sessions and memory rows from the index: each group's newest session per subject, every
member's median and ratio, and the peak its arm reached alone."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from .dashboard import render
from .store import Store

VIEWS = Path(__file__).resolve().parents[1] / "views"


class Dashboard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "records"
        (Path(self.tmp.name) / "views").mkdir()
        for view in ("session_members.sql", "memory_rows.sql"):
            shutil.copy(VIEWS / view, Path(self.tmp.name) / "views" / view)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_session_and_its_memory_rows_are_one_table(self):
        members = [{"member": f"{label}:time.carry_forward@dense", "label": label, "node": "time.carry_forward@dense",
                    "built": {"cell": "dense", "subject": "carry_forward", "device": "gpu"}, "ms": [ms], "blocks_ms": [ms],
                    "median_ms": ms, "iqr_ms": 0.001, "paired": [] if label == "tip" else [{"ratio_median": ms / 0.5}]}
                   for label, ms in (("tip", 0.5), ("master", 0.75))]
        Store("bench/session", self.root).put(
            {"members": ["tip", "master"]},
            output={"session": "carry_forward@G", "members": members, "refused": {},
                    "relation": {"group": "G", "holds": "1024 tokens", "roles": {"tip": "subject", "master": "reference"}}},
            provenance={"members": [{"label": "tip", "git_sha": "aaaa1111"}, {"label": "master", "git_sha": "bbbb2222"}]})
        Store("rola/memory", self.root).put(
            {"params": {"cell": "dense", "arm": "carry_forward"}},
            output={"peak_allocated_bytes": 19_700_000, "peak_reserved_bytes": 52_400_000, "allocated_after_bytes": 1,
                    "built": {"device": "gpu"}},
            provenance={"label": "tip", "git_sha": "aaaa1111"})
        page = render(self.root)
        self.assertIn("<h2>G</h2>", page)
        self.assertIn("carry_forward@G", page)
        self.assertIn("0.7500", page)
        self.assertIn("1.500", page)
        self.assertIn("19.7", page)


if __name__ == "__main__":
    unittest.main()
