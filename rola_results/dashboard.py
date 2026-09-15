"""THE SUITE'S DASHBOARD: the newest composed sessions, memory rows and instrument records as one standalone page.

    python -m rola_results dashboard --out suite.html [--group G]

A reading of the index (`session_members`, `memory_rows`, the instrument locations), rebuilt each time it is asked for
and never stored. For each group, each subject's newest session: every member's median and interquartile range, its
paired ratio to the subject checkout's node of the same name, and the peak memory its arm reached alone. The page
carries its own style and no script, so it opens from a file.
"""
from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from . import index
from .store import ROOT

_SESSIONS = """SELECT m.location, m.key, m.n, m.utc, m.session, m.grp, m.holds, m.label, m.role, m.node, m.cell, m.subject,
                      m.median_ms, m.iqr_ms, m.ratio_median, m.git_sha, m.device
               FROM session_members m
               WHERE m.n = (SELECT max(t.n) FROM samples t WHERE t.location = m.location AND t.key = m.key AND t.ok)
               ORDER BY m.utc"""
_MEMORY = """SELECT label, git_sha, cell, subject, peak_allocated_bytes, peak_reserved_bytes, utc
             FROM memory_rows ORDER BY utc"""
_INSTRUMENTS = """SELECT location, count(DISTINCT key), max(utc) FROM samples
                  WHERE ok AND (location LIKE 'rola/carry.%') GROUP BY location ORDER BY location"""

_STYLE = """
:root { --ink:#1d2330; --muted:#5d6678; --rule:#d9dde5; --ground:#fbfbfc; --band:#eef1f6; --accent:#2f5d9a; }
@media (prefers-color-scheme: dark) { :root { --ink:#e3e7ee; --muted:#9aa3b2; --rule:#343b48; --ground:#161a21;
  --band:#1f2530; --accent:#8fb4e8; } }
body { margin:0; padding:24px 16px; background:var(--ground); color:var(--ink);
       font:14px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1100px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 4px; } h3 { font-size:14px; margin:16px 0 6px; }
p.meta { color:var(--muted); margin:0 0 8px; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:4px 10px; border-bottom:1px solid var(--rule); white-space:nowrap; }
th { color:var(--muted); font-weight:600; }
td.num { text-align:right; } tr.subject td { background:var(--band); }
code { font:12px ui-monospace, SFMono-Regular, Menlo, monospace; color:var(--accent); }
"""


def _mb(value) -> str:
    return "" if value is None else f"{value / 1e6:.1f}"


def _ms(value) -> str:
    return "" if value is None else f"{value:.4f}"


def render(root: Path | str = ROOT, group: str | None = None) -> str:
    _, sessions = index.query(_SESSIONS, root=root)
    _, memory = index.query(_MEMORY, root=root)
    _, instruments = index.query(_INSTRUMENTS, root=root)
    peaks = {}
    for label, _sha, cell, subject, allocated, reserved, _utc in memory:
        peaks[(label, cell, subject)] = (allocated, reserved)
    newest: dict[tuple, dict] = {}
    for row in sessions:
        (location, key, n, utc, session, grp, holds, label, role, node, cell, subject, median, iqr, ratio, sha,
         device) = row
        if group is not None and grp != group:
            continue
        entry = newest.get((grp, session))
        if entry is None or (entry["utc"], entry["key"]) < (utc, key):
            entry = newest[(grp, session)] = {"utc": utc, "key": key, "holds": holds, "device": device, "rows": []}
        if entry["key"] == key:
            entry["rows"].append((label, role, node, cell, subject, median, iqr, ratio, sha))

    out = ["<title>RoLA suite</title>", f"<style>{_STYLE}</style>", "<main>", "<h1>RoLA measurement suite</h1>",
           f"<p class='meta'>{len(newest)} session(s) across {len({g for g, _s in newest})} group(s); "
           f"{len(memory)} memory row(s). Latency is comparable only within one session.</p>"]
    by_group: dict[str, list] = defaultdict(list)
    for (grp, session), entry in sorted(newest.items()):
        by_group[grp].append((session, entry))
    for grp, entries in by_group.items():
        out.append(f"<h2>{html.escape(str(grp))}</h2><p class='meta'>{html.escape(entries[0][1]['holds'] or '')}</p>")
        for session, entry in entries:
            out.append(f"<h3>{html.escape(session)}</h3><p class='meta'>{html.escape(entry['utc'])} &middot; "
                       f"{html.escape(entry['device'] or '')} &middot; <code>{entry['key'][:12]}</code></p>")
            out.append("<div class='scroll'><table><tr><th>checkout</th><th>role</th><th>cell</th><th>median ms</th>"
                       "<th>IQR ms</th><th>ratio to subject</th><th>peak MB</th><th>reserved MB</th><th>commit</th></tr>")
            order = {"subject": 0, "reference": 1, "attention": 2}
            for label, role, _node, cell, subject, median, iqr, ratio, sha in sorted(
                    entry["rows"], key=lambda r: (r[3] or "", order.get(r[1], 3))):
                allocated, reserved = peaks.get((label, cell, subject), (None, None))
                out.append(f"<tr class='{html.escape(role or '')}'><td>{html.escape(label)}</td>"
                           f"<td>{html.escape(role or '')}</td><td>{html.escape(cell or '')}</td>"
                           f"<td class='num'>{_ms(median)}</td><td class='num'>{_ms(iqr)}</td>"
                           f"<td class='num'>{'' if ratio is None else f'{ratio:.3f}'}</td>"
                           f"<td class='num'>{_mb(allocated)}</td><td class='num'>{_mb(reserved)}</td>"
                           f"<td><code>{html.escape((sha or '')[:8])}</code></td></tr>")
            out.append("</table></div>")
    out.append("<h2>Instrument records</h2><div class='scroll'><table><tr><th>location</th><th>records</th>"
               "<th>newest sample</th></tr>")
    out += [f"<tr><td><code>{html.escape(loc)}</code></td><td class='num'>{count}</td><td>{html.escape(utc)}</td></tr>"
            for loc, count, utc in instruments]
    out.append("</table></div></main>")
    return "\n".join(out) + "\n"


def write(out: Path | str, root: Path | str = ROOT, group: str | None = None) -> dict:
    page = render(root, group)
    Path(out).write_text(page)
    return {"out": str(out), "bytes": len(page)}


__all__ = ["render", "write"]
