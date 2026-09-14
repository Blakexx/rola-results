"""THE INDEX: the records as one SQLite database, derived and never committed, for queries across every location.

    records(location, key, format, semantics)
    samples(location, key, n, ok, utc, wall_s, provenance, error, output_path, output, extra)

`semantics`, `provenance`, `output` (a JSON output's text) and `extra` (whatever else a tool kept on the sample) are
JSON, read with SQLite's JSON functions -- `json_extract(semantics, '$.cell')`, `json_each(output)` -- so the tables
know no tool's shape. A tool's shape is a VIEW: each `views/*.sql` beside the records is run after the tables are
filled. The database is rebuilt incrementally: a record file whose size or modification time changed is read again, a
vanished one dropped. It refuses a record of a format it does not know.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .store import _RECORD, FORMAT, ROOT

_STANDARD = {"n", "ok", "utc", "wall_s", "provenance", "error", "output"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER);
CREATE TABLE IF NOT EXISTS records(location TEXT, key TEXT, format INTEGER, semantics TEXT, PRIMARY KEY (location, key));
CREATE TABLE IF NOT EXISTS samples(location TEXT, key TEXT, n INTEGER, ok INTEGER, utc TEXT, wall_s REAL, provenance TEXT,
                                   error TEXT, output_path TEXT, output TEXT, extra TEXT, PRIMARY KEY (location, key, n));
CREATE INDEX IF NOT EXISTS samples_by_location ON samples(location, utc);
"""


def default_db(root: Path) -> Path:
    return Path(root).parent / "index.sqlite"


def default_views(root: Path) -> Path:
    return Path(root).parent / "views"


def build(root: Path | str = ROOT, db: Path | str | None = None, views: Path | str | None = None) -> dict:
    """Bring the database up to date with the records; return what changed."""
    root = Path(root)
    db = Path(db) if db else default_db(root)
    views = Path(views) if views else default_views(root)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    known = {path: (mtime, size) for path, mtime, size in con.execute("SELECT path, mtime_ns, size FROM files")}
    present = {}
    for path in root.rglob("*.json"):
        if _RECORD.match(path.name):
            stat = path.stat()
            present[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
    changed = [p for p, st in present.items() if known.get(p) != st]
    gone = [p for p in known if p not in present]
    for rel in gone + changed:
        location, key = str(Path(rel).parent), Path(rel).stem
        con.execute("DELETE FROM records WHERE location = ? AND key = ?", (location, key))
        con.execute("DELETE FROM samples WHERE location = ? AND key = ?", (location, key))
        con.execute("DELETE FROM files WHERE path = ?", (rel,))
    for rel in changed:
        _load(con, root, rel, present[rel])
    pending = sorted(views.glob("*.sql")) if views.is_dir() else []
    for view in pending:
        con.execute(f"DROP VIEW IF EXISTS {view.stem}")
    #: a view may read another: create what can be created until a pass adds nothing
    while pending:
        failed = []
        for view in pending:
            try:
                con.executescript(view.read_text())
            except sqlite3.OperationalError as ex:
                failed.append((view, ex))
        if len(failed) == len(pending):
            raise SystemExit(f"index: views that do not create: {[(v.name, str(e)) for v, e in failed]}")
        pending = [v for v, _ in failed]
    con.commit()
    con.close()
    return {"db": str(db), "read": len(changed), "dropped": len(gone), "records": len(present)}


def _load(con: sqlite3.Connection, root: Path, rel: str, stat: tuple[int, int]) -> None:
    record = json.loads((root / rel).read_text())
    if record.get("format") != FORMAT:
        raise SystemExit(f"index: {rel} is format {record.get('format')!r}; this library reads {FORMAT}")
    location, key = str(Path(rel).parent), record["key"]
    con.execute("INSERT INTO records VALUES (?, ?, ?, ?)", (location, key, record["format"], json.dumps(record["semantics"])))
    for s in record["samples"]:
        output_path, output = s.get("output"), None
        if output_path and output_path.endswith(".json"):
            output = (root / location / output_path).read_text()
        extra = {k: v for k, v in s.items() if k not in _STANDARD}
        con.execute("INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (location, key, s["n"], int(s["ok"]), s["utc"], s.get("wall_s"), json.dumps(s.get("provenance", {})),
                     s.get("error"), output_path, output, json.dumps(extra) if extra else None))
    con.execute("INSERT INTO files VALUES (?, ?, ?)", (rel, *stat))


def query(sql: str, params: tuple = (), root: Path | str = ROOT, db: Path | str | None = None) -> tuple[list[str], list]:
    """Run a query on an up-to-date database: (column names, rows)."""
    build(root, db)
    con = sqlite3.connect(Path(db) if db else default_db(Path(root)))
    cur = con.execute(sql, params)
    columns = [d[0] for d in cur.description or ()]
    rows = cur.fetchall()
    con.close()
    return columns, rows


def matching(location: str, where: dict[str, str]) -> tuple[str, list]:
    """The SQL condition for samples of `location` whose semantics hold each `path=value` (a dotted path into the
    semantics; the value compared as text)."""
    clauses, params = ["s.location = ?"], [location]
    for path, value in where.items():
        if not all(part.isidentifier() for part in path.split(".")):
            raise ValueError(f"--where {path!r} is not a dotted path of names")
        clauses.append(f"CAST(json_extract(r.semantics, '$.{path}') AS TEXT) = ?")
        params.append(value)
    return " AND ".join(clauses), params
