"""The verdict query, on a temporary backend of planted timing sessions: the reference is a label chosen when reading,
each other label's member of the same arm on the same cell is judged within its session, host drift both arms share
cancels, a unit is the code both members ran, and a member that failed or has no reference is not judged."""
from __future__ import annotations

import itertools
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import index
from . import store as store_module
from .store import Store
from .verdict import verdicts

VIEWS = Path(__file__).resolve().parents[1] / "views"
ROUNDS = 8
REPS = 3


def plant(root: Path, *, tip_ms: float, master_ms: float = 1.0, tip_sha: str = "a", drift: float = 1.0,
          tip_owner: str = "tip/carry_forward") -> None:
    """One stored session: tip and master timing `carry_forward` on `dense` with a host drift both share and a per-round
    swing, the attention reference on its own cell, and a tip registration that could not run."""
    members = [{"id": "m0", "owner": tip_owner, "cell": "dense", "status": "ok", "built": {"device": "gpu"}},
               {"id": "m1", "owner": "master/carry_forward", "cell": "dense", "status": "ok", "built": {"device": "gpu"}},
               {"id": "m2", "owner": "bench/flash", "cell": "q", "status": "ok", "built": {"device": "gpu"}},
               {"id": "m3", "owner": "tip/prefill_op", "cell": "dense", "status": "failed", "error": "no prefill arm"}]
    samples, position = [], itertools.count()
    for rnd, rep in itertools.product(range(ROUNDS), range(REPS)):
        swing = drift * (1 + 0.05 * (rnd % 3)) * (1 + 0.01 * rep)
        for member, ms in (("m0", tip_ms), ("m1", master_ms), ("m2", 0.1)):
            samples.append({"member": member, "round": rnd, "rep": rep, "position": next(position) % 3, "ms": ms * swing})
    output = {"session": "session/G/carry_forward+flash", "run": "r", "instrument": "cuda_events", "rounds": ROUNDS,
              "reps": REPS, "clock": {"before": 1.665, "after": 1.665}, "members": members, "samples": samples}
    checkouts = {tip_owner: {"checkout": "tip", "git_sha": tip_sha, "diff_sha256": None},
                 "master/carry_forward": {"checkout": "master", "git_sha": "base", "diff_sha256": None},
                 "bench/flash": {"checkout": "rola-bench", "git_sha": "bench", "diff_sha256": None}}
    Store("timing/session", root).put({"executor": "measure", "cells": ["dense", "q"]}, output=output,
                                      provenance={"run": "r", "checkouts": checkouts}, run="r")


class VerdictQuery(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "records"
        shutil.copytree(VIEWS, Path(self.tmp.name) / "views")
        clock = (f"2026-09-15T00:{m:02d}:00Z" for m in itertools.count())
        patcher = mock.patch.object(store_module, "utc", lambda: next(clock))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_slow_session_is_flagged_and_a_second_at_the_same_code_confirms(self):
        plant(self.root, tip_ms=1.0)
        plant(self.root, tip_ms=1.0)
        self.assertEqual([r["verdict"] for r in verdicts(self.root, reference="master")], ["no_regression"])
        plant(self.root, tip_ms=1.6, tip_sha="slow")
        slow = [r for r in verdicts(self.root, reference="master") if r["git_sha"] == "slow"]
        self.assertEqual([(r["verdict"], r["n_sessions"]) for r in slow], [("flagged_not_confirmed", 1)])
        plant(self.root, tip_ms=1.6, tip_sha="slow")
        (got,) = [r for r in verdicts(self.root, reference="master") if r["git_sha"] == "slow"]
        self.assertEqual((got["verdict"], got["n_sessions"], got["arm"], got["cell"], got["candidate"]),
                         ("regression", 2, "carry_forward", "dense", "tip"))
        self.assertAlmostEqual(got["ratio"], 1.6)
        self.assertEqual(got["significance"]["verdict"], "b_slower")

    def test_host_drift_both_arms_share_is_no_regression(self):
        plant(self.root, tip_ms=1.0)
        plant(self.root, tip_ms=1.0, drift=1.3)
        (got,) = verdicts(self.root, reference="master")
        self.assertEqual((got["verdict"], got["ratio"], got["n_sessions"]), ("no_regression", 1.0, 2))

    def test_the_reference_is_the_readers_and_only_paired_members_are_judged(self):
        plant(self.root, tip_ms=1.6)
        (inverse,) = verdicts(self.root, reference="tip")
        self.assertEqual((inverse["candidate"], inverse["verdict"]), ("master", "no_regression"))
        self.assertAlmostEqual(inverse["ratio"], 1 / 1.6)
        self.assertEqual(verdicts(self.root, reference="someone-else"), [])
        self.assertEqual(verdicts(self.root, reference="master", arm="prefill_op"), [])

    def test_a_members_label_is_its_owners_scope_and_its_arm_the_last_segment(self):
        plant(self.root, tip_ms=1.0, tip_owner="suite/tip/entmax_solve@layer=w16")
        _, rows = index.query("SELECT label, arm, git_sha FROM timing_members WHERE member = 'm0'", root=self.root)
        self.assertEqual(rows, [("suite/tip", "entmax_solve@layer=w16", "a")])
        _, rows = index.query("SELECT count(*), min(round), max(round), max(rep) FROM timing_samples WHERE member = 'm0'",
                              root=self.root)
        self.assertEqual(rows, [(ROUNDS * REPS, 0, ROUNDS - 1, REPS - 1)])

    def test_a_null_gates_cells_are_rows(self):
        cells = {"dense": {"trusted": True, "ratio_median": 1.0, "ratio_q1": 0.99, "ratio_q3": 1.01},
                 "sparse": {"trusted": None, "error": "a copy could not run"}}
        Store("timing/null", self.root).put({"executor": "null_gate"}, output={"members": [], "samples": [], "null": cells},
                                            provenance={"run": "r"}, run="r")
        _, rows = index.query("SELECT cell, trusted, ratio_median, error FROM null_gates ORDER BY cell", root=self.root)
        self.assertEqual(rows, [("dense", 1, 1.0, None), ("sparse", None, None, "a copy could not run")])

    def test_an_instruments_cells_are_rows_with_their_status(self):
        summary = {"cells": {"dense": {"status": "ok", "exit": 0}, "deep": {"status": "failed", "exit": 1, "error": "no arm"}}}
        Store("rola/phases", self.root).put({"executor": "run_tool"}, output={"dense": {}}, provenance={"run": "r"},
                                            run="r", summary=summary)
        _, rows = index.query("SELECT instrument, cell, status, error FROM instrument_cells ORDER BY cell", root=self.root)
        self.assertEqual(rows, [("phases", "deep", "failed", "no arm"), ("phases", "dense", "ok", None)])


if __name__ == "__main__":
    unittest.main()
