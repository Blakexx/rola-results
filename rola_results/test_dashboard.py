"""The dashboard reads one run's timing sessions and memory rows from the index: every member's median, its paired ratio
to the reference label named when reading, a member that could not run, and the peak its entry reached alone."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from .dashboard import render
from .store import Store
from .test_verdict import plant

VIEWS = Path(__file__).resolve().parents[1] / "views"


class Dashboard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "records"
        shutil.copytree(VIEWS, Path(self.tmp.name) / "views")

    def test_a_session_and_its_memory_rows_are_one_table(self):
        plant(self.root, tip_ms=1.5)
        rows = [{"owner": "tip/carry_forward", "cell": "dense", "status": "ok", "calls": 5,
                 "peak_allocated_bytes": 17_600_000, "peak_reserved_bytes": 52_400_000, "allocated_after_bytes": 1,
                 "allocated_before_build_bytes": 1, "outside_allocator_bytes": 2_100_000, "built": {"device": "gpu"}}]
        Store("timing/memory", self.root).put({"executor": "memory"}, output={"run": "r", "rows": rows},
                                              provenance={"run": "r", "checkouts": {}}, run="r")
        page = render(self.root, reference="master")
        self.assertIn("<h2>session/G/carry_forward+flash</h2>", page)
        self.assertIn(">1.500<", page)
        self.assertIn("failed", page)
        self.assertIn("19.7", page)
        self.assertIn("54.5", page)
        self.assertNotIn(">1.500<", render(self.root))


if __name__ == "__main__":
    unittest.main()
