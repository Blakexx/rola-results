"""THE INSTRUMENTS READ ACROSS RUNS: every number an instrument recorded (`instrument_metrics`) for one run against
the same number in a reference run -- a phase time, an HMMA count, a register peak, a roofline fraction -- as one
table of deltas. This is the suite reading its own instruments: the same records the timing verdict reads, joined on
(instrument, cell, metric) rather than parsed per tool.

    python -m rola_results instruments --against RUN [--run RUN] [--instrument phases] [--min-change 0.05]

Which run is the reference is the reader's choice; nothing here ranks one. A metric present in one run and absent in
the other is a row with one side empty -- a kernel that lost a phase or gained a region is a finding, not a join miss.
"""
from __future__ import annotations

from pathlib import Path

from . import index
from .store import ROOT

_RUNS = "SELECT run, max(utc) AS utc FROM instrument_metrics GROUP BY run ORDER BY utc DESC"
_METRICS = """SELECT instrument, cell, metric, value FROM instrument_metrics
              WHERE run = ? AND (? IS NULL OR instrument = ?)"""
_SHA = """SELECT DISTINCT json_extract(c.value, '$.git_sha') FROM samples s, json_each(s.provenance, '$.checkouts') c
          WHERE json_extract(s.provenance, '$.run') = ? AND s.location LIKE 'rola/%'"""


def runs(root: Path | str = ROOT) -> list[dict]:
    columns, rows = index.query(_RUNS, root=root)
    return [dict(zip(columns, r, strict=True)) for r in rows]


def compare(root: Path | str = ROOT, *, against: str, run: str | None = None, instrument: str | None = None,
            min_change: float = 0.0) -> list[dict]:
    """One row per (instrument, cell, metric) of `run` (default: the newest) beside `against`: both values and the
    relative change where both are numbers; rows under `min_change` in relative terms are dropped."""
    run = run or (runs(root)[0]["run"] if runs(root) else None)
    if run is None:
        return []
    sides = {}
    for name, which in (("value", run), ("reference", against)):
        _cols, rows = index.query(_METRICS, (which, instrument, instrument), root=root)
        sides[name] = {(i, c, m): v for i, c, m, v in rows}
    out = []
    for key in sorted(set(sides["value"]) | set(sides["reference"]), key=lambda k: tuple(str(x) for x in k)):
        value, reference = sides["value"].get(key), sides["reference"].get(key)
        if value is None and reference is None:
            continue
        change = None
        if isinstance(value, (int, float)) and isinstance(reference, (int, float)):
            change = (value - reference) / reference if reference else (0.0 if value == reference else None)
        if change is not None and abs(change) < min_change:
            continue
        instrument_, cell, metric = key
        out.append({"instrument": instrument_, "cell": cell, "metric": metric, "value": value,
                    "reference": reference, "change": change, "run": run, "against": against})
    return out


def sha(root: Path | str, run: str) -> str | None:
    _cols, rows = index.query(_SHA, (run,), root=root)
    return rows[0][0] if rows else None


def table(rows: list[dict]) -> str:
    if not rows:
        return "no instrument metrics to compare"
    head = f"{'instrument':10} {'cell':30} {'metric':48} {'value':>14} {'reference':>14} {'change':>8}"
    lines = [head, "-" * len(head)]
    for r in rows:
        fmt = lambda v: "-" if v is None else (f"{v:.6g}" if isinstance(v, (int, float)) else str(v))  # noqa: E731
        change = "-" if r["change"] is None else f"{r['change']:+.1%}"
        lines.append(f"{r['instrument']:10} {str(r['cell'] or ''):30} {r['metric'][:48]:48} {fmt(r['value']):>14} "
                     f"{fmt(r['reference']):>14} {change:>8}")
    return "\n".join(lines)


__all__ = ["compare", "runs", "sha", "table"]
