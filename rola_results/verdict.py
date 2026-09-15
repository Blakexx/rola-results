"""THE VERDICT QUERY: which stored sessions are a candidate's baseline and its runs, judged by rola-devtools' math.

    python -m rola_results verdict [--cell C] [--subject S] [--baseline LABEL] [--window N] [--json]

A timing session -- a measurement service session (`session_members`) or a suite session from before the service
(`session_arms`), role `subject` against role `reference` on the same cell -- is judged per unit: a cell, a subject, a
call count and the arms' names (a service session's member is named by its registration, `carry_forward`). For the
newest session of each (unit, candidate commit):

- the BASELINE is the reference arm's samples over the newest `window` sessions of that unit whose reference ran the same
  arm on the same device and torch, up to and including this one: the threshold is its own median and spread;
- the RUNS are the candidate arm's samples over every session of that unit at the candidate's commit, oldest first, the
  last the one judged: persistence reads them after the baseline's;
- the PAIRED DIFFERENCES are that last session's per-round medians, candidate minus reference.

`rola_devtools.verdict.classify` decides (effect size, paired significance, persistence). Nothing is stored: a verdict
is a reading of the records, taken again whenever it is asked for.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import index
from .store import ROOT

#: the baseline sessions a threshold is read from, newest first
WINDOW = 10

_ARMS = """SELECT key, n, utc, point, cell, subject, calls, label, role, arm, samples, blocks, device, torch, git_sha, rounds
           FROM session_arms WHERE location = 'suite/timing.session' AND role IN ('subject', 'reference')
           UNION ALL
           SELECT key, n, utc, grp, cell, subject, calls, label, role, arm, samples, blocks, device, torch, git_sha, rounds
           FROM session_members WHERE role IN ('subject', 'reference')
           ORDER BY utc, key, n"""


def verdicts(root: Path | str = ROOT, *, cell: str | None = None, subject: str | None = None, baseline: str | None = None,
             window: int = WINDOW) -> list[dict]:
    from rola_devtools.verdict import classify

    columns, rows = index.query(_ARMS, root=root)
    arms = [dict(zip(columns, row, strict=True)) for row in rows]
    sessions: dict[tuple, dict] = {}
    for arm in arms:
        session = sessions.setdefault((arm["key"], arm["n"], arm["cell"]),
                                      {"utc": arm["utc"], "subject": None, "references": []})
        if arm["role"] == "subject":
            session["subject"] = arm
        else:
            session["references"].append(arm)
    pairs = []
    for session in sessions.values():
        refs = [r for r in session["references"] if baseline is None or r["label"] == baseline]
        if session["subject"] and refs and (cell is None or session["subject"]["cell"] == cell) \
                and (subject is None or session["subject"]["subject"] == subject):
            pairs.append((session["utc"], session["subject"], refs[0]))
    pairs.sort(key=lambda p: p[0])

    def unit(candidate: dict, reference: dict) -> tuple:
        return (candidate["cell"], candidate["subject"], candidate["calls"], candidate["arm"], reference["arm"],
                reference["device"], reference["torch"])

    newest: dict[tuple, int] = {}
    for i, (_utc, candidate, reference) in enumerate(pairs):
        newest[unit(candidate, reference) + (candidate["git_sha"],)] = i
    out = []
    for i in sorted(newest.values()):
        _utc, candidate, reference = pairs[i]
        same = [p for p in pairs[:i + 1] if unit(p[1], p[2]) == unit(candidate, reference)]
        base = [json.loads(p[2]["samples"]) for p in same][-window:]
        runs = [json.loads(p[1]["samples"]) for p in same if p[1]["git_sha"] == candidate["git_sha"]]
        diffs = [c - r for c, r in zip(json.loads(candidate["blocks"]), json.loads(reference["blocks"]), strict=True)]
        judged = classify(base, runs, paired_diffs=diffs)
        out.append({"point": candidate["point"], "cell": candidate["cell"], "subject": candidate["subject"],
                    "calls": candidate["calls"],
                    "candidate": candidate["label"], "arm": candidate["arm"], "git_sha": candidate["git_sha"],
                    "baseline": reference["label"], "baseline_arm": reference["arm"],
                    "baseline_git_sha": reference["git_sha"], "utc": candidate["utc"], **judged})
    return out


def table(rows: list[dict]) -> str:
    head = f"{'verdict':<22}{'unit':<48}{'candidate':<22}{'median':>10}{'limit':>10}{'p':>9}  persistence"
    lines = [head]
    for r in rows:
        name = f"{r['subject']}@{r['cell']}" + (f"@calls={r['calls']}" if r["calls"] != 1 else "")
        p = r.get("significance", {}).get("p")
        median = f"{r['median_ms']:.4f}" if "median_ms" in r else "-"
        limit = f"{r['limit_ms']:.4f}" if "limit_ms" in r else "-"
        lines.append(f"{r['verdict']:<22}{name:<48}{(r['candidate'] + ' ' + (r['git_sha'] or '')[:8]):<22}{median:>10}"
                     f"{limit:>10}{('-' if p is None else f'{p:.4f}'):>9}  {r.get('persistence', '-')}")
    return "\n".join(lines)
