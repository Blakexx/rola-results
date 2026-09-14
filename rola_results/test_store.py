"""The store's contract, on a temporary backend (no GPU, no git)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .store import Store, check, checkout, key, locations, outputs, portable

#: a home-directory prefix, joined so this file carries none
HOME = "/".join(("", "home", "someone"))


class StoreContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store("tool/sub", self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_same_semantics_land_on_one_record_and_every_sample_is_kept(self) -> None:
        sem = {"cell": "a", "binary": "b1"}
        self.store.put(sem, output={"ms": 1.0}, provenance={"git_sha": "x"}, wall_s=0.5)
        self.store.put(sem, error="boom")
        self.store.put(sem, output={"ms": 2.0})
        record = self.store.get(key(sem))
        self.assertEqual([s["ok"] for s in record["samples"]], [True, False, True])
        self.assertEqual(record["samples"][0]["provenance"]["git_sha"], "x")
        self.assertIn("host", record["samples"][0]["provenance"])
        self.assertEqual(json.loads(self.store.output(record).read_text()), {"ms": 2.0})
        self.assertEqual(json.loads(self.store.output(record, 0).read_text()), {"ms": 1.0})
        self.assertTrue(Store.complete(record))

    def test_a_record_of_failures_is_not_complete(self) -> None:
        sem = {"cell": "b"}
        self.store.put(sem, error="first")
        record = self.store.get(key(sem))
        self.assertFalse(Store.complete(record))
        with self.assertRaises(LookupError):
            self.store.output(record)

    def test_a_changed_input_is_a_new_record(self) -> None:
        self.store.put({"binary": "b1"}, output=1)
        self.store.put({"binary": "b2"}, output=1)
        self.assertEqual(len(list(self.store.records())), 2)

    def test_an_output_file_is_moved_in_with_its_suffix(self) -> None:
        src = self.root / "capture.csv"
        src.write_text("a,b\n")
        sample = self.store.put({"cell": "c"}, output_file=src)
        self.assertEqual(sample["output"], f"{key({'cell': 'c'})}.0.out.csv")
        self.assertFalse(src.exists())

    def test_a_sample_is_exactly_one_of_output_or_error(self) -> None:
        with self.assertRaises(ValueError):
            self.store.put({"x": 1})
        with self.assertRaises(ValueError):
            self.store.put({"x": 1}, output=1, error="e")

    def test_a_location_is_a_relative_path_of_plain_names(self) -> None:
        for bad in ("", "/abs", "a/../b", "a b", "a//b"):
            with self.assertRaises(ValueError):
                Store(bad, self.root)

    def test_outputs_walks_a_prefix_and_skips_failures(self) -> None:
        Store("mqar/a", self.root).put({"cell": "x"}, output={"acc": 1})
        Store("mqar/a", self.root).put({"cell": "y"}, error="oom")
        Store("mqar/b", self.root).put({"cell": "z"}, output={"acc": 2})
        Store("mqarx", self.root).put({"cell": "w"}, output={"acc": 3})
        self.assertEqual(sorted(o["acc"] for _r, _s, o in outputs("mqar", self.root)), [1, 2])
        self.assertEqual([o["acc"] for _r, _s, o in outputs("mqar/b", self.root)], [2])

    def test_check_finds_a_record_whose_semantics_were_edited(self) -> None:
        self.store.put({"cell": "d"}, output=1)
        self.assertEqual(check(self.root), [])
        self.assertEqual(locations(self.root), ["tool/sub"])
        path = self.store.path(key({"cell": "d"}))
        record = json.loads(path.read_text())
        record["semantics"]["cell"] = "e"
        path.write_text(json.dumps(record))
        self.assertTrue(any("does not recompute" in p for p in check(self.root)))

    def test_a_checkout_names_its_directory_and_digests_its_diff(self) -> None:
        import subprocess

        repo = self.root / "repo"
        repo.mkdir()
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        (repo / "f").write_text("a\n")
        subprocess.run([*git, "add", "f"], check=True)
        subprocess.run([*git, "commit", "-qm", "c"], check=True)
        clean = checkout(repo)
        self.assertEqual((clean["checkout"], clean["diff_sha256"]), ("repo", None))
        self.assertIsNotNone(clean["branch"])
        subprocess.run([*git, "checkout", "-q", "--detach"], check=True)
        self.assertIsNone(checkout(repo)["branch"])
        (repo / "f").write_text("b\n")
        one = checkout(repo)["diff_sha256"]
        (repo / "f").write_text("c\n")
        self.assertNotIn(None, (one, checkout(repo)["diff_sha256"]))
        self.assertNotEqual(one, checkout(repo)["diff_sha256"])

    def test_a_record_carries_no_machine_path(self) -> None:
        for sample in ({"output": {"rola_file": f"{HOME}/wt/rola/__init__.py"}},
                       {"error": f'File "{HOME}/bench/engine.py", line 1'},
                       {"output": {"ms": 1.0}, "provenance": {"venv": f"{HOME}/venv"}}):
            with self.assertRaisesRegex(ValueError, "machine path"):
                self.store.put({"cell": "p"}, **sample)
        self.assertIsNone(self.store.get(key({"cell": "p"})))
        self.store.put({"cell": "p"}, output={"rola_file": "rola/__init__.py"})
        self.assertEqual(check(self.root), [])

    def test_check_finds_a_machine_path_written_around_the_store(self) -> None:
        sem = {"cell": "q"}
        sample = self.store.put(sem, output={"rola_file": "rola/__init__.py"})
        (self.store.dir / sample["output"]).write_text(json.dumps({"rola_file": f"{HOME}/wt/rola/__init__.py"}))
        self.assertTrue(any("machine paths" in p for p in check(self.root)))

    def test_portable_makes_checkout_paths_relative_and_other_home_paths_tilde(self) -> None:
        home, root = Path.home(), Path(self.tmp.name) / "bench"
        root.mkdir()
        text = f'File "{root.resolve()}/pkg/engine.py"\nFile "{home}/venv/lib/torch.py"'
        self.assertEqual(portable(text, root), 'File "pkg/engine.py"\nFile "~/venv/lib/torch.py"')


if __name__ == "__main__":
    unittest.main()
