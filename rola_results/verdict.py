"""THE VERDICT QUERY: each candidate's timing judged against a reference timed in the same sessions, by rola-devtools' math.

    python -m rola_results verdict --reference LABEL [--candidate LABEL] [--cell C] [--arm A] [--json]

The reference is the reader's choice, never the run's. In every stored timing session (`timing_members`,
`timing_samples`) that timed the reference label's arm on a cell, each other label's member of that arm on that cell is a
candidate, and the pair is judged within the session: `rola_devtools.verdict.session` turns the two members' samples,
by round, into the session's paired ratio, its limit and its per-round differences. A UNIT is (arm, cell, candidate
label, reference label) and the code both members ran (each checkout's commit and uncommitted diff): `classify` reads a
unit's sessions oldest first and judges the newest. Nothing is stored: a verdict is a reading of the records, taken again
whenever it is asked for.
"""
from __future__ import annotations

from pathlib import Path

from . import index
from .store import ROOT

_MEMBERS = """SELECT location, key, n, utc, member, label, arm, cell, git_sha, diff_sha256, device
              FROM timing_members WHERE status = 'ok' ORDER BY utc, location, key, n"""
_SAMPLES = "SELECT location, key, n, member, round, ms FROM timing_samples"


def verdicts(root: Path | str = ROOT, *, reference: str, candidate: str | None = None, cell: str | None = None,
             arm: str | None = None) -> list[dict]:
    from rola_devtools.verdict import classify, session

    columns, rows = index.query(_MEMBERS, root=root)
    members = [dict(zip(columns, row, strict=True)) for row in rows]
    rounds: dict[tuple, dict[int, list[float]]] = {}
    for location, key, n, member, rnd, ms in index.query(_SAMPLES, root=root)[1]:
        rounds.setdefault((location, key, n, member), {}).setdefault(rnd, []).append(ms)

    stored: dict[tuple, list[dict]] = {}
    for m in members:
        stored.setdefault((m["location"], m["key"], m["n"]), []).append(m)
    units: dict[tuple, list[tuple[dict, dict]]] = {}
    for sample, ms in stored.items():
        refs = {(m["arm"], m["cell"]): m for m in ms if m["label"] == reference}
        for m in ms:
            base = refs.get((m["arm"], m["cell"]))
            if base is None or m is base or (candidate is not None and m["label"] != candidate) \
                    or (cell is not None and m["cell"] != cell) or (arm is not None and m["arm"] != arm):
                continue
            c, b = rounds.get((*sample, m["member"]), {}), rounds.get((*sample, base["member"]), {})
            if not c or sorted(c) != sorted(b):
                continue
            unit = (m["arm"], m["cell"], m["label"], m["git_sha"], m["diff_sha256"], base["git_sha"], base["diff_sha256"])
            units.setdefault(unit, []).append((m, session([c[r] for r in sorted(c)], [b[r] for r in sorted(b)])))
    out = []
    for (unit_arm, unit_cell, label, sha, diff, base_sha, base_diff), judged in units.items():
        newest = judged[-1][0]
        out.append({"arm": unit_arm, "cell": unit_cell, "candidate": label, "git_sha": sha, "diff_sha256": diff,
                    "reference": reference, "reference_git_sha": base_sha, "reference_diff_sha256": base_diff,
                    "utc": newest["utc"], "device": newest["device"], **classify([paired for _m, paired in judged])})
    return sorted(out, key=lambda r: (r["utc"], r["arm"], r["cell"], r["candidate"]))


def table(rows: list[dict]) -> str:
    head = f"{'verdict':<22}{'unit':<56}{'candidate':<20}{'ratio':>8}{'limit':>8}{'p':>9}  sessions  persistence"
    lines = [head]
    for r in rows:
        p = r["significance"].get("p")
        unit, candidate = f"{r['arm']}@{r['cell']}", f"{r['candidate']} {(r['git_sha'] or '')[:8]}"
        lines.append(f"{r['verdict']:<22}{unit:<56}{candidate:<20}"
                     f"{r['ratio']:>8.3f}{r['limit']:>8.3f}{('-' if p is None else f'{p:.4f}'):>9}  "
                     f"{r['n_sessions']:>8}  {r['persistence']}")
    return "\n".join(lines)
