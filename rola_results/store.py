"""The store: records under a location, keyed by their semantics, every sample kept."""
from __future__ import annotations

import fcntl
import hashlib
import json
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

#: THE DEFAULT BACKEND: this repository's own files
ROOT = Path(__file__).resolve().parents[1] / "records"
#: THE RECORD FORMAT: the envelope every record carries (key, location, format, semantics, samples). A reader refuses a
#: format it does not know rather than guessing at it; a change to the envelope is a new number.
FORMAT = 1

_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_RECORD = re.compile(r"^[0-9a-f]{24}\.json$")
#: A MACHINE PATH: an absolute path into one user's home directory. A record is read on other machines and published,
#: so it names a file by its path inside its checkout and a checkout by `checkout()`, never by where either sat here.
_MACHINE_PATH = re.compile(r"/home/[^/\s\"']+/|/Users/[^/\s\"']+/")


def key(semantics: dict) -> str:
    """sha256 over the semantics, canonical JSON, the first 24 hex digits."""
    return hashlib.sha256(json.dumps(semantics, sort_keys=True).encode()).hexdigest()[:24]


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def digest(path: Path | str) -> str:
    """sha256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def portable(text: str, root: Path | str) -> str:
    """`text` (a traceback, a tool's message) with paths inside the checkout `root` made relative to it and any other
    path under the home directory spelled from `~`."""
    text = text.replace(str(Path(root).resolve()) + "/", "")
    return text.replace(str(Path.home()) + "/", "~/")


def machine_paths(blob: object) -> list[str]:
    """The machine paths anywhere in a JSON-able value, as they appear."""
    return sorted({m.group(0) for m in _MACHINE_PATH.finditer(json.dumps(blob))})


def checkout(path: Path | str) -> dict:
    """A git checkout's identity: its directory's name (never its path), its branch (None when detached), HEAD, and
    `diff_sha256` -- sha256 of its tracked changes against HEAD, None when clean -- so two different uncommitted trees
    over one commit differ."""
    path = Path(path)

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
        return done.stdout if done.returncode == 0 else ""

    diff = git("diff", "HEAD", "--", ".")
    return {"checkout": path.resolve().name, "branch": git("symbolic-ref", "--short", "-q", "HEAD").strip() or None,
            "git_sha": git("rev-parse", "HEAD").strip() or None,
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff.strip() else None}




class Store:
    """The records of one location. `root` is the backend's directory; the default is this repository's `records/`."""

    def __init__(self, location: str, root: Path | str = ROOT):
        parts = location.split("/")
        if not location or not all(_SEGMENT.match(p) and p not in (".", "..") for p in parts):
            raise ValueError(f"location {location!r} is not a relative path of plain names")
        self.location = location
        self.root = Path(root)
        self.dir = self.root / location

    def path(self, k: str) -> Path:
        return self.dir / f"{k}.json"

    def get(self, k: str) -> dict | None:
        path = self.path(k)
        return json.loads(path.read_text()) if path.exists() else None

    @staticmethod
    def complete(record: dict | None) -> bool:
        """A record is complete when one of its samples succeeded."""
        return bool(record) and any(s["ok"] for s in record["samples"])

    def output(self, record: dict, n: int | None = None) -> Path:
        """The output of sample `n`, or of the latest sample that succeeded."""
        ok = [s for s in record["samples"] if s["ok"] and (n is None or s["n"] == n)]
        if not ok:
            raise LookupError(f"{self.location}/{record['key']} has no successful sample" + (f" {n}" if n is not None else ""))
        return self.dir / ok[-1]["output"]

    def records(self) -> Iterator[dict]:
        for path in sorted(self.dir.glob("*.json")):
            if _RECORD.match(path.name):
                yield json.loads(path.read_text())

    def put(self, semantics: dict, *, output: object = None, output_file: Path | str | None = None,
            error: str | None = None, wall_s: float | None = None, provenance: dict | None = None, **extra) -> dict:
        """Add one sample under the semantics' key and return it. A success hands either `output` (stored as JSON) or
        `output_file` (moved in, its suffix kept); a failure hands `error`. `provenance` is what the tool knows of where
        the sample came from (its checkouts, a stage); the host is added. `extra` is kept on the sample as given."""
        if (error is None) == (output is None and output_file is None) or (output is not None and output_file is not None):
            raise ValueError("a sample is exactly one of output, output_file or error")
        stored = [semantics, output, error, provenance, extra]
        if output_file is not None and Path(output_file).suffix == ".json":
            stored.append(json.loads(Path(output_file).read_text()))
        found = machine_paths(stored)
        if found:
            raise ValueError(f"{self.location}: a record carries no machine path, found {found}: name a file by its path "
                             "inside its checkout and a checkout by checkout(); portable() rewrites a message")
        k = key(semantics)
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._locked(k):
            record = self.get(k) or {"key": k, "location": self.location, "format": FORMAT, "semantics": semantics,
                                     "samples": []}
            if record.get("format") != FORMAT:
                raise RuntimeError(f"{self.location}/{k} is format {record.get('format')}, this library writes {FORMAT}")
            if record["semantics"] != semantics:
                raise RuntimeError(f"{self.location}/{k}: stored semantics differ from the ones given (a key collision)")
            n = len(record["samples"])
            sample = {"n": n, "ok": error is None, "utc": utc(), "wall_s": None if wall_s is None else round(wall_s, 3),
                      "provenance": {"host": platform.node(), **(provenance or {})}, **extra}
            if error is not None:
                sample["error"] = error[-4000:]
            else:
                suffix = Path(output_file).suffix if output_file is not None else ".json"
                dest = self.dir / f"{k}.{n}.out{suffix}"
                if output_file is not None:
                    shutil.move(str(output_file), dest)
                else:
                    dest.write_text(json.dumps(output, indent=1, sort_keys=True) + "\n")
                sample["output"] = dest.name
            record["samples"].append(sample)
            tmp = self.path(k).with_suffix(".tmp")
            tmp.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
            tmp.replace(self.path(k))
        return sample

    @contextmanager
    def _locked(self, k: str) -> Iterator[None]:
        with open(self.dir / f"{k}.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def locations(root: Path | str = ROOT) -> list[str]:
    """Every location under a backend that holds a record."""
    root = Path(root)
    return sorted({str(p.parent.relative_to(root)) for p in root.rglob("*.json") if _RECORD.match(p.name)})


def outputs(prefix: str, root: Path | str = ROOT) -> Iterator[tuple[dict, dict, object]]:
    """Every successful sample under the locations `prefix` names (the location itself or any below it), oldest first
    per record: (record, sample, its output -- parsed when JSON, else the output's path)."""
    root = Path(root)
    for loc in locations(root):
        if loc != prefix and not loc.startswith(prefix.rstrip("/") + "/"):
            continue
        store = Store(loc, root)
        for record in store.records():
            for sample in record["samples"]:
                if sample["ok"]:
                    path = store.dir / sample["output"]
                    yield record, sample, json.loads(path.read_text()) if path.suffix == ".json" else path


def check(root: Path | str = ROOT) -> list[str]:
    """What is wrong with the stored records: a key that does not recompute, a location that is not the record's
    directory, samples out of order, a successful sample whose output is missing, a machine path in a record or a JSON
    output."""
    root = Path(root)
    problems = []
    for loc in locations(root):
        for path in sorted((root / loc).glob("*.json")):
            if not _RECORD.match(path.name):
                continue
            where = f"{loc}/{path.name}"
            try:
                record = json.loads(path.read_text())
            except json.JSONDecodeError as ex:
                problems.append(f"{where}: not JSON ({ex})")
                continue
            if record.get("key") != path.stem or key(record.get("semantics", {})) != path.stem:
                problems.append(f"{where}: the key does not recompute from the semantics")
            if record.get("location") != loc:
                problems.append(f"{where}: location {record.get('location')!r} is not its directory")
            if record.get("format") != FORMAT:
                problems.append(f"{where}: format {record.get('format')!r} is not {FORMAT}")
            if machine_paths(record):
                problems.append(f"{where}: carries machine paths {machine_paths(record)}")
            for i, sample in enumerate(record.get("samples", [])):
                if sample.get("n") != i:
                    problems.append(f"{where}: sample {i} is numbered {sample.get('n')}")
                out = root / loc / str(sample.get("output"))
                if sample.get("ok") and not out.is_file():
                    problems.append(f"{where}: sample {i}'s output {sample.get('output')} is missing")
                elif sample.get("ok") and out.suffix == ".json" and machine_paths(json.loads(out.read_text())):
                    problems.append(f"{where}: sample {i}'s output carries machine paths")
                if not sample.get("ok") and not sample.get("error"):
                    problems.append(f"{where}: failed sample {i} carries no error")
    return problems
