"""python -m rola_results check | show [LOCATION] | commit -m MESSAGE | index | sql QUERY | history|latest LOCATION |
verdict | dashboard --out FILE"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import index
from .store import ROOT, Store, check, locations


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m rola_results")
    ap.add_argument("--root", type=Path, default=ROOT, help="the backend's directory (default: this repository's records/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="every record's key recomputes, its location is its directory, its outputs exist")
    show = sub.add_parser("show", help="the locations, or one location's records")
    show.add_argument("location", nargs="?")
    commit = sub.add_parser("commit", help="commit the records (never the library) in the backend's git repository")
    commit.add_argument("-m", "--message", required=True)
    sub.add_parser("index", help="bring the derived SQLite database beside the records up to date")
    sql = sub.add_parser("sql", help="run a query on the database (tables records, samples; the views in views/)")
    sql.add_argument("query")
    for name, what in (("history", "every sample of a location's matching records, oldest first"),
                       ("latest", "each matching record's newest successful sample, with its output")):
        p = sub.add_parser(name, help=what)
        p.add_argument("location")
        p.add_argument("--where", action="append", default=[], metavar="PATH=VALUE",
                       help="a dotted path into the semantics and the value it holds (repeatable)")
    dashboard = sub.add_parser("dashboard", help="one run's timing sessions and memory rows as a standalone page")
    dashboard.add_argument("--out", type=Path, required=True)
    dashboard.add_argument("--reference", help="the label each member's paired ratio is taken to")
    dashboard.add_argument("--run", help="the run to show (default: the newest)")
    dashboard.add_argument("--session", help="one session only")
    verdict = sub.add_parser("verdict", help="each candidate judged against a reference timed in the same sessions")
    verdict.add_argument("--reference", required=True, help="the label every other label is judged against")
    verdict.add_argument("--candidate", help="one candidate label only")
    verdict.add_argument("--cell")
    verdict.add_argument("--arm")
    verdict.add_argument("--json", action="store_true", help="one JSON object per unit")
    a = ap.parse_args()

    if a.cmd == "dashboard":
        from .dashboard import write

        print(json.dumps(write(a.out, a.root, reference=a.reference, run=a.run, session=a.session)))
        return 0

    if a.cmd == "verdict":
        from .verdict import table, verdicts

        rows = verdicts(a.root, reference=a.reference, candidate=a.candidate, cell=a.cell, arm=a.arm)
        print("\n".join(json.dumps(r) for r in rows) if a.json else table(rows))
        return 0

    if a.cmd == "index":
        print(json.dumps(index.build(a.root)))
        return 0

    if a.cmd == "sql":
        columns, rows = index.query(a.query, root=a.root)
        print("\t".join(columns))
        for row in rows:
            print("\t".join("" if v is None else str(v) for v in row))
        return 0

    if a.cmd in ("history", "latest"):
        cond, params = index.matching(a.location, dict(w.split("=", 1) for w in a.where))
        if a.cmd == "history":
            columns, rows = index.query(
                "SELECT s.key, s.n, s.ok, s.utc, json_extract(s.provenance, '$.git_sha'), substr(s.error, 1, 80) "
                f"FROM samples s JOIN records r USING (location, key) WHERE {cond} ORDER BY s.utc", tuple(params), a.root)
            for row in rows:
                print("\t".join("" if v is None else str(v) for v in row))
            return 0
        columns, rows = index.query(
            "SELECT s.key, s.n, s.utc, r.semantics, s.output FROM samples s JOIN records r USING (location, key) "
            f"WHERE {cond} AND s.ok AND s.n = (SELECT max(n) FROM samples t WHERE t.location = s.location AND t.key = s.key "
            "AND t.ok) ORDER BY s.utc", tuple(params), a.root)
        for k, n, utc, semantics, output in rows:
            print(json.dumps({"key": k, "n": n, "utc": utc, "semantics": json.loads(semantics),
                              "output": json.loads(output) if output else None}))
        return 0

    if a.cmd == "check":
        problems = check(a.root)
        print("\n".join(problems) or f"records: {sum(1 for _ in a.root.rglob('*.json'))} files under {len(locations(a.root))} "
              "locations, all consistent")
        return 1 if problems else 0

    if a.cmd == "show":
        if not a.location:
            for loc in locations(a.root):
                print(f"{loc:<40}{sum(1 for _ in Store(loc, a.root).records())} records")
            return 0
        for record in Store(a.location, a.root).records():
            ok = sum(s["ok"] for s in record["samples"])
            last = record["samples"][-1] if record["samples"] else {}
            print(f"{record['key']}  {ok} ok / {len(record['samples']) - ok} failed  last {last.get('utc', '-')}")
        return 0

    problems = check(a.root)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    repo = subprocess.run(["git", "-C", str(a.root), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                          check=True).stdout.strip()
    subprocess.run(["git", "-C", repo, "add", "--", str(a.root)], check=True)
    return subprocess.run(["git", "-C", repo, "commit", "-m", a.message, "--", str(a.root)], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
