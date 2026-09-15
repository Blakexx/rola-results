# rola-results

The interface every rola tool stores its measurements through (`rola_results`), and, by default, the records themselves.

```python
from rola_results import Store, checkout

store = Store("mqar/local")                        # the tool's own location
semantics = {"bench": "mqar", "config": "local", "cell": "d1-n256", "local": checkouts}
store.put(semantics, output=rows, wall_s=12.3, provenance=checkout(worktree))
store.put(semantics, error="RuntimeError: ...")    # a failure is a sample too
record = store.get(key(semantics))                  # Store.complete(record), store.output(record)
```

- **A location** names who stores: `rola/sass`, `timing/session`, `mqar/<config>`.
- **A record** is everything kept under one key: the semantics the tool handed over and every sample.
- **The key** is sha256 over the semantics, so a repeat lands on the same record and a changed input on a new one.
- **A sample** is one execution: its output (JSON, or a file moved in) or its error, when, how long, its provenance
  (the checkouts and commits the tool names; the host).

Nothing derived from two records (a ratio, a baseline) is stored: that is the reader's.

    records/<location>/<key>.json            the record (format 1: key, location, format, semantics, samples)
    records/<location>/<key>.<n>.out.<ext>   sample n's output
    views/<name>.sql                         a query view over the index
    index.sqlite                             the index, derived from records/ (never committed)

## Queries

    python -m rola_results index                  # bring index.sqlite up to date (derived; never committed)
    python -m rola_results sql "SELECT ..."       # any query; the index is brought up to date first
    python -m rola_results history LOCATION [--where PATH=VALUE]   # every sample of the matching records
    python -m rola_results latest LOCATION [--where PATH=VALUE]    # each matching record's newest good output
    python -m rola_results verdict --reference LABEL [--candidate LABEL] [--cell C] [--arm A]   # judged in-session
    python -m rola_results dashboard --out suite.html [--reference LABEL] [--run RUN]   # one run's sessions as a page

The tables know no tool: `records(location, key, format, semantics)` and `samples(location, key, n, ok, utc, wall_s,
provenance, error, output_path, output, extra)`, the JSON fields read with SQLite's JSON functions. A tool's shape is a
view in `views/`, run after every index:

| view | from | one row per |
|---|---|---|
| `timing_members` | `timing/session` (rola-devtools' `measure_timing`, through a store target) | member of a stored session: the run, the session, its registration (`owner`), the label and arm read from it, the cell, whether it ran and why not, device, torch, the owner's commit and diff, the session's rounds, reps and clock reads |
| `timing_samples` | `timing_members` | timed call, in the order taken: its member's label, arm and cell, its round, rep and position in the rep's random order, and its milliseconds |
| `memory_rows` | `timing/memory` (rola-devtools' `measure_memory`) | timing entry alone on a central cell: peak allocated and reserved bytes, what was allocated before the build and after the calls, bytes held outside the caching allocator (a paged state) and the totals with them, label, arm, commit |
| `null_gates` | `timing/null` (rola-devtools' `measure_null_gate`) | cell of a null gate: the run, whether the entry's two workers agree (the per-rep ratios' interquartile range holds one), the ratio's median and quartiles |
| `cells` | fleet and local grids | stored grid cell: bench, config, cell, image or local checkouts, row |

A session stores raw samples and no ratio: which label is the reference is the reader's, in a query.

```sql
-- the runs, newest first
SELECT run, max(utc), count(DISTINCT session) FROM timing_members GROUP BY run ORDER BY max(utc) DESC;
-- one session's members that could not run, and why
SELECT session, label, arm, cell, error FROM timing_members WHERE run = ? AND status = 'failed';
-- a label's arm on a cell over time: its mean call per stored session
SELECT utc, git_sha, avg(ms) FROM timing_samples WHERE label = 'tip' AND arm = 'carry_forward' AND cell = 'nl64k-alt-k4'
GROUP BY location, key, n ORDER BY utc;
-- two labels in one session, round by round
SELECT a.round, avg(a.ms) / avg(b.ms) FROM timing_samples a JOIN timing_samples b USING (location, key, n, arm, cell, round)
WHERE a.label = 'tip' AND b.label = 'master' AND a.cell = 'flagship-dense' AND a.run = ? GROUP BY a.round;
```

**The verdict** is a query, never a stored row. `verdict --reference LABEL` pairs, in every stored session, each other
label's member with the reference label's member of the same arm on the same cell, and judges the pair within its
session: per round each member's median, their ratio and difference (`rola_devtools.verdict.session`). A unit is the
arm, the cell, the two labels and the code each ran (commit and diff); rola-devtools' `rola_devtools.verdict.classify`
reads a unit's sessions oldest first and judges the newest: a regression needs the session's median ratio over one plus
three sigmas of its own per-round ratio spread, a significant paired test, and a second session at the same code over its
own limit; anything less says what it is. Host drift between sessions moves both members of a pair and cancels.

The rola tree names this checkout as `store.root` in its dev config, and `tools/dev.py init` makes the package importable
from every interpreter it provisions.

    python -m rola_results check              every key recomputes, every location is its directory, every output exists
    python -m rola_results show [LOCATION]
    python -m rola_results commit -m MESSAGE  commits records/ only; the library goes through its gated commits

The commit gate (`.githooks/pre-commit`, `core.hooksPath`): ruff and the contract tests on the library (the verdict's
needs rola-devtools, which `tools/dev.py init` links beside this package), `check` on the records.

## Publishing

This repository is developed in the private `rola-results-dev` and published to the public `rola-results`: a push
to `master` runs `.github/workflows/mirror.yml`, which publishes the declared files as one snapshot commit
(`.github/mirror/declarations.json`; the export is [rola-devtools](https://github.com/Blakexx/rola-devtools)'). A record carries no machine path, so every record ships as
stored.
