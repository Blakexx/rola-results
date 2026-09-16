"""THE SUITE'S DASHBOARD: one run's timing sessions, memory rows and instrument records as one standalone page.

    python -m rola_results dashboard --out suite.html [--reference LABEL] [--run RUN] [--session S]

A reading of the index (`timing_members`, `timing_samples`, `memory_rows`, the instrument locations), rebuilt each time it
is asked for and never stored. The run is the newest stored unless `--run` names one. For each of its sessions, every
member's median and interquartile range over its samples, the LEVEL it prices (`kernel`, `op`, `layer`: a reading
compares one level), its paired ratio to the reference label's member of the same arm on the same cell (the median of
the per-round ratios, within the session) when a reference is named, and the peak
memory its entry reached alone in the same run (the caching allocator's peak plus what it holds outside it, a paged
state). The page carries its own style and no script, so it opens from a file.
"""
from __future__ import annotations

import html
import statistics
from pathlib import Path

from . import index
from .store import ROOT

_RUNS = "SELECT run, max(utc) FROM timing_members GROUP BY run ORDER BY max(utc) DESC"
_MEMBERS = """SELECT location, key, n, utc, session, member, label, arm, cell, level, status, error, git_sha, device
              FROM timing_members WHERE run = ? ORDER BY session, cell, label"""
_SAMPLES = "SELECT location, key, n, member, round, ms FROM timing_samples WHERE run = ?"
_MEMORY = "SELECT label, arm, cell, peak_bytes, peak_reserved_total_bytes FROM memory_rows WHERE run = ? AND status = 'ok'"
_INSTRUMENTS = """SELECT location, count(DISTINCT key), max(utc) FROM samples
                  WHERE ok AND location LIKE 'rola/%' GROUP BY location ORDER BY location"""
_METRICS = "SELECT instrument, cell, metric, value FROM instrument_metrics WHERE run = ?"
_DIFFS = """SELECT location, run, strategy, expect, held, compared, quantities, minimum, cell, cell_status, why, quantity,
                   same, ratio, bound_by FROM diff_cells WHERE run = ? ORDER BY location, cell, quantity"""
#: THE HEADLINE METRICS an instrument's table shows per cell; the whole-binary instruments show every row they have
_HEADLINES = {
    "phases": ["total", "phase.head", "phase.fold", "phase.readout", "phase.sweep"],
    "counters": ["counter.gpu__time_duration.sum", "counter.dram__bytes_read.sum",
                 "counter.sm__inst_executed_pipe_tensor_op_hmma.sum"],
    "census": ["census.instructions_per_unit", "census.wavefronts.excess_per_unit", "census.budget_red"],
    "timeline": ["timeline.duration_us", "timeline.tensor_mean_full", "timeline.tensor_idle_share_full"],
    "roofline": ["roofline.ms", "roofline.fraction", "roofline.tflop_per_s"],
}

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
td.num { text-align:right; } tr.reference td { background:var(--band); }
code { font:12px ui-monospace, SFMono-Regular, Menlo, monospace; color:var(--accent); }
"""


def _mb(value) -> str:
    return "" if value is None else f"{value / 1e6:.1f}"


def _ms(value) -> str:
    return "" if value is None else f"{value:.4f}"


def _iqr(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[int(0.75 * len(ordered))] - ordered[int(0.25 * len(ordered))]


def _ratio(candidate: dict[int, list[float]], reference: dict[int, list[float]]) -> float | None:
    if not candidate or sorted(candidate) != sorted(reference):
        return None
    return statistics.median(statistics.median(candidate[r]) / statistics.median(reference[r]) for r in sorted(candidate))


def render(root: Path | str = ROOT, *, reference: str | None = None, run: str | None = None,
           session: str | None = None, baseline: str | None = None) -> str:
    runs = index.query(_RUNS, root=root)[1]
    if not runs:
        runs = index.query("SELECT run, max(utc) FROM instrument_metrics GROUP BY run ORDER BY max(utc) DESC", root=root)[1]
    run = run or (runs[0][0] if runs else None)
    columns, rows = index.query(_MEMBERS, (run,), root=root)
    members = [dict(zip(columns, row, strict=True)) for row in rows if session is None or row[4] == session]
    rounds: dict[tuple, dict[int, list[float]]] = {}
    for location, key, n, member, rnd, ms in index.query(_SAMPLES, (run,), root=root)[1]:
        rounds.setdefault((location, key, n, member), {}).setdefault(rnd, []).append(ms)
    _, memory = index.query(_MEMORY, (run,), root=root)
    peaks = {(label, arm, cell): (peak, reserved) for label, arm, cell, peak, reserved in memory}
    _, instruments = index.query(_INSTRUMENTS, root=root)
    sessions: dict[tuple, list[dict]] = {}
    for m in members:
        sessions.setdefault((m["session"], m["location"], m["key"], m["n"]), []).append(m)

    out = ["<title>RoLA suite</title>", f"<style>{_STYLE}</style>", "<main>", "<h1>RoLA measurement suite</h1>",
           f"<p class='meta'>run <code>{html.escape(run or 'none')}</code> &middot; {len(sessions)} session(s); "
           f"ratios to <code>{html.escape(reference or 'no reference')}</code>. Latency is comparable only within one "
           "session.</p>"]
    for (name, location, key, n), ms in sorted(sessions.items()):
        out.append(f"<h2>{html.escape(name or '')}</h2><p class='meta'>{html.escape(ms[0]['utc'])} &middot; "
                   f"{html.escape(ms[0]['device'] or '')} &middot; <code>{html.escape(key[:12])}</code></p>")
        out.append("<div class='scroll'><table><tr><th>label</th><th>arm</th><th>level</th><th>cell</th><th>median ms</th>"
                   "<th>IQR ms</th><th>ratio to reference</th><th>peak MB</th><th>reserved MB</th><th>commit</th></tr>")
        refs = {(m["arm"], m["cell"]): m for m in ms if m["label"] == reference}
        for m in ms:
            got = rounds.get((location, key, n, m["member"]), {})
            samples = [v for r in got.values() for v in r]
            base = refs.get((m["arm"], m["cell"]))
            ratio = None if base is None or base is m else _ratio(got, rounds.get((location, key, n, base["member"]), {}))
            allocated, reserved = peaks.get((m["label"], m["arm"], m["cell"]), (None, None))
            median = _ms(statistics.median(samples)) if samples else html.escape(m["status"] or "")
            spread = _ms(_iqr(samples)) if samples else html.escape((m["error"] or "")[:60])
            out.append(f"<tr class='{'reference' if base is m else ''}'><td>{html.escape(m['label'])}</td>"
                       f"<td>{html.escape(m['arm'])}</td><td>{html.escape(m['level'] or '')}</td>"
                       f"<td>{html.escape(m['cell'] or '')}</td>"
                       f"<td class='num'>{median}</td><td class='num'>{spread}</td>"
                       f"<td class='num'>{'' if ratio is None else f'{ratio:.3f}'}</td>"
                       f"<td class='num'>{_mb(allocated)}</td><td class='num'>{_mb(reserved)}</td>"
                       f"<td><code>{html.escape((m['git_sha'] or '')[:8])}</code></td></tr>")
        out.append("</table></div>")
    out += _instrument_sections(root, run, baseline)
    out += _diff_sections(root, run)
    out.append("<h2>Instrument records</h2><div class='scroll'><table><tr><th>location</th><th>records</th>"
               "<th>newest sample</th></tr>")
    out += [f"<tr><td><code>{html.escape(loc)}</code></td><td class='num'>{count}</td><td>{html.escape(utc)}</td></tr>"
            for loc, count, utc in instruments]
    out.append("</table></div></main>")
    return "\n".join(out) + "\n"


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return html.escape(str(value))


def _instrument_sections(root, run: str | None, baseline: str | None) -> list[str]:
    """One table per instrument: its headline metrics per cell, and beside each the relative change baseline the
    reference run where one is named -- the suite reading its own instruments."""
    if run is None:
        return []
    _, rows = index.query(_METRICS, (run,), root=root)
    by: dict[str, dict[str | None, dict[str, object]]] = {}
    for instrument, cell, metric, value in rows:
        by.setdefault(instrument, {}).setdefault(cell, {})[metric] = value
    base: dict[tuple, object] = {}
    if baseline:
        for instrument, cell, metric, value in index.query(_METRICS, (baseline,), root=root)[1]:
            base[(instrument, cell, metric)] = value
    out = []
    for instrument in sorted(by):
        cells = by[instrument]
        metrics = _HEADLINES.get(instrument) or sorted({m for c in cells.values() for m in c})
        out.append(f"<h2>{html.escape(instrument)}</h2><p class='meta'>{len(cells)} cell(s); "
                   f"{'change baseline ' + html.escape(baseline) if baseline else 'no reference run'}</p>")
        out.append("<div class='scroll'><table><tr><th>cell</th>" + "".join(
            f"<th>{html.escape(m.split('.', 1)[-1] if instrument in _HEADLINES else m)}</th>"
            + ("<th>Δ</th>" if baseline else "") for m in metrics) + "</tr>")
        for cell in sorted(cells, key=lambda c: c or ""):
            tds = []
            for m in metrics:
                value = cells[cell].get(m)
                tds.append(f"<td class='num'>{_fmt(value)}</td>")
                if baseline:
                    ref = base.get((instrument, cell, m))
                    numeric = isinstance(value, (int, float)) and isinstance(ref, (int, float))
                    change = ((value - ref) / ref if ref else None) if numeric else None
                    tds.append(f"<td class='num'>{'' if change is None else f'{change:+.1%}'}</td>")
            out.append(f"<tr><td>{html.escape(cell or '(binary)')}</td>{''.join(tds)}</tr>")
        out.append("</table></div>")
    return out


def _diff_sections(root, run: str | None) -> list[str]:
    """One table per stored diff: the claim and whether it held, then every cell that was refused, unusable or
    differed, with the worst slot -- a diff stores verdicts, and this shows exactly those."""
    if run is None:
        return []
    columns, rows = index.query(_DIFFS, (run,), root=root)
    verdicts = [dict(zip(columns, r, strict=True)) for r in rows]
    out = []
    for location in sorted({v["location"] for v in verdicts}):
        mine = [v for v in verdicts if v["location"] == location]
        head = mine[0]
        held = "HELD" if head["held"] else "DID NOT HOLD"
        out.append(f"<h2>diff <code>{html.escape(location)}</code></h2><p class='meta'>{html.escape(head['strategy'])}, "
                   f"expect {html.escape(head['expect'])}: <b>{held}</b> &middot; {head['compared']} cell(s) compared, "
                   f"{head['quantities']} quantities (minimum {head['minimum']})</p>")
        shown = [v for v in mine if v["cell_status"] != "ok" or not v["same"]]
        if not shown:
            out.append("<p class='meta'>every cell and quantity the same</p>")
            continue
        out.append("<div class='scroll'><table><tr><th>cell</th><th>status</th><th>quantity</th><th>same</th>"
                   "<th>error / allowance</th><th>bound by</th><th>why</th></tr>")
        for v in shown:
            out.append(f"<tr><td>{html.escape(v['cell'])}</td><td>{html.escape(v['cell_status'])}</td>"
                       f"<td>{html.escape(v['quantity'] or '')}</td><td>{'' if v['same'] is None else int(v['same'])}</td>"
                       f"<td class='num'>{_fmt(v['ratio'])}</td><td>{html.escape(v['bound_by'] or '')}</td>"
                       f"<td>{html.escape((v['why'] or '')[:90])}</td></tr>")
        out.append("</table></div>")
    return out


def write(out: Path | str, root: Path | str = ROOT, **reading) -> dict:
    page = render(root, **reading)
    Path(out).write_text(page)
    return {"out": str(out), "bytes": len(page)}


__all__ = ["render", "write"]
