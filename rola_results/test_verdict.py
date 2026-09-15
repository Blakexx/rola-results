"""The verdict query, on a temporary backend of planted suite sessions: the reference's sessions are the baseline, the
candidate commit's sessions are its runs, and the newest session's paired rounds decide significance."""
from __future__ import annotations

import itertools
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import store as store_module
from .store import Store
from .verdict import verdicts

VIEWS = Path(__file__).resolve().parents[1] / "views"
ROUNDS = 8


def _arm(label: str, ms: float) -> dict:
    samples = [ms] * (ROUNDS * 3)
    return {"label": label, "arm": "carry_forward", "ms": samples, "blocks_ms": [ms] * ROUNDS, "median_ms": ms,
            "cell": {"subject": "carry_forward", "calls": 1, "device": "gpu", "torch": "2.14"}}


class VerdictQuery(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "records"
        (Path(self.tmp.name) / "views").mkdir()
        for view in ("session_arms.sql", "session_members.sql"):
            shutil.copy(VIEWS / view, Path(self.tmp.name) / "views" / view)
        self.store = Store("suite/timing.session", self.root)
        clock = (f"2026-09-14T00:{m:02d}:00Z" for m in itertools.count())
        patcher = mock.patch.object(store_module, "utc", lambda: next(clock))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def session(self, candidate_sha: str, candidate_ms: float, reference_ms: float = 1.0) -> None:
        output = {"subject": "carry_forward", "calls": 1, "cell": "c", "roles": {"tip": "subject", "master": "reference"},
                  "result": {"point": {"cell": "c"}, "instrument": "cuda_events", "rounds": ROUNDS, "clock": {"held": True},
                             "arms": [_arm("tip", candidate_ms), _arm("master", reference_ms)]}}
        provenance = {"arms": [{"role": "subject", "label": "tip", "git_sha": candidate_sha},
                               {"role": "reference", "label": "master", "git_sha": "base"}]}
        self.store.put({"unit": "carry_forward@c", "candidate": candidate_sha}, output=output, provenance=provenance)

    def test_an_unchanged_candidate_is_no_regression(self):
        for sha in ("a", "b", "c", "d"):
            self.session(sha, 1.0)
        rows = verdicts(self.root)
        self.assertEqual([r["verdict"] for r in rows], ["insufficient_data", "insufficient_data", "no_regression",
                                                        "no_regression"])

    def test_one_slow_session_is_flagged_and_a_second_confirms(self):
        for sha in ("a", "b", "c"):
            self.session(sha, 1.0)
        self.session("slow", 1.6)
        self.assertEqual(verdicts(self.root)[-1]["verdict"], "flagged_not_confirmed")
        self.session("slow", 1.6)
        got = verdicts(self.root)[-1]
        self.assertEqual((got["verdict"], got["git_sha"], got["n_runs"]), ("regression", "slow", 2))
        self.assertEqual(got["significance"]["verdict"], "b_slower")

    def point_session(self, candidate_sha: str, ms: dict[str, tuple[float, float]]) -> None:
        """A session on a point: tip and master on every cell, and an attention row on a cell of its own."""
        arms = []
        for label, which in (("tip", 0), ("master", 1)):
            for cell, pair in ms.items():
                arm = _arm(label, pair[which])
                arms.append({**{k: v for k, v in arm.items() if k != "cell"}, "row": f"{label}|{cell}", "cell": cell,
                             "built": arm["cell"]})
        arms.append({**{k: v for k, v in _arm("attention", 0.1).items() if k != "cell"}, "row": "attention|q",
                     "cell": "q", "arm": "flash", "built": {"device": "gpu", "torch": "2.14"}})
        output = {"point": "P", "subject": "carry_forward", "calls": 1,
                  "roles": {"tip": "subject", "master": "reference", "attention": "attention"},
                  "result": {"point": {"name": "P"}, "instrument": "cuda_events", "rounds": ROUNDS,
                             "clock": {"held": True}, "arms": arms}}
        provenance = {"arms": [{"role": "subject", "label": "tip", "git_sha": candidate_sha},
                               {"role": "reference", "label": "master", "git_sha": "base"}]}
        self.store.put({"unit": "carry_forward@P", "candidate": candidate_sha}, output=output, provenance=provenance)

    def composed(self, candidate_sha: str, ms: dict[str, tuple[float, float]]) -> None:
        """A service session (rola_devtools.measure): tip and master members on every cell, and the attention member."""
        members = []
        for label, which in (("tip", 0), ("master", 1)):
            for cell, pair in ms.items():
                members.append({"member": f"{label}:carry_forward@{cell}", "label": label,
                                "role": "subject" if label == "tip" else "reference", "arm": "carry_forward",
                                "cell": cell, "unit": "benchmarks.registry:Subject",
                                "built": {"cell": cell, "subject": "carry_forward", "calls": 1, "device": "gpu",
                                          "torch": "2.14"},
                                "ms": [pair[which]] * (ROUNDS * 3), "blocks_ms": [pair[which]] * ROUNDS,
                                "median_ms": pair[which], "iqr_ms": 0.0, "post": {}, "paired": []})
        members.append({"member": "bench:flash@q", "label": "bench", "role": "library", "arm": "flash", "cell": "q",
                        "unit": "rola_bench.measure.registry:Flash",
                        "built": {"cell": "q", "backend": "flash", "device": "gpu", "torch": "2.14"},
                        "ms": [0.1] * (ROUNDS * 3), "blocks_ms": [0.1] * ROUNDS, "median_ms": 0.1, "iqr_ms": 0.0,
                        "post": {}, "paired": []})
        output = {"session": "carry_forward@G", "instrument": "cuda_events", "rounds": ROUNDS, "members": members,
                  "refusals": {}, "relation": {"group": "G", "roles": {"tip": "subject", "master": "reference",
                                                                       "bench": "library"}}}
        provenance = {"members": [{"label": "tip", "git_sha": candidate_sha}, {"label": "master", "git_sha": "base"},
                                  {"label": "bench", "git_sha": "bench"}]}
        Store("bench/session", self.root).put({"members": [candidate_sha]}, output=output, provenance=provenance)

    def test_a_composed_session_judges_each_cell_against_the_reference_on_that_cell(self):
        for sha in ("a", "b", "c"):
            self.composed(sha, {"dense": (1.0, 1.0), "sparse": (0.2, 0.2)})
        self.composed("slow", {"dense": (1.0, 1.0), "sparse": (0.4, 0.2)})
        self.composed("slow", {"dense": (1.0, 1.0), "sparse": (0.4, 0.2)})
        newest = {r["cell"]: r for r in verdicts(self.root) if r["git_sha"] == "slow"}
        self.assertEqual({cell: r["verdict"] for cell, r in newest.items()}, {"dense": "no_regression",
                                                                               "sparse": "regression"})
        self.assertEqual(newest["sparse"]["arm"], "carry_forward")

    def test_a_points_session_judges_each_cell_against_the_reference_on_that_cell(self):
        for sha in ("a", "b", "c"):
            self.point_session(sha, {"dense": (1.0, 1.0), "sparse": (0.2, 0.2)})
        self.point_session("slow", {"dense": (1.0, 1.0), "sparse": (0.4, 0.2)})
        self.point_session("slow", {"dense": (1.0, 1.0), "sparse": (0.4, 0.2)})
        newest = {r["cell"]: r for r in verdicts(self.root) if r["git_sha"] == "slow"}
        self.assertEqual({cell: r["verdict"] for cell, r in newest.items()}, {"dense": "no_regression",
                                                                            "sparse": "regression"})
        self.assertEqual(newest["sparse"]["point"], "P")

    def test_the_baseline_is_filtered_by_label(self):
        for sha in ("a", "b", "c"):
            self.session(sha, 1.0)
        self.assertEqual(verdicts(self.root, baseline="someone-else"), [])


if __name__ == "__main__":
    unittest.main()
