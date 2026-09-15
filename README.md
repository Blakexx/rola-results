# rola-results

The interface every rola tool stores its measurements through (`rola_results`), and, by default, the records themselves.

```python
from rola_results import Store, checkout

store = Store("probe_cells")                       # the tool's own location
semantics = {"bench": "prefill_op", "cell": "nl64k-alt-k4", "binary": so_sha256, "instrument": code_key}
store.put(semantics, output=rows, wall_s=12.3, provenance=checkout(worktree))
store.put(semantics, error="RuntimeError: ...")    # a failure is a sample too
record = store.get(key(semantics))                  # Store.complete(record), store.output(record)
```

- **A location** names who stores: `probe_cells`, `bench_driver`, `suite/carry.sass`.
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
    python -m rola_results verdict [--cell C] [--subject S] [--baseline LABEL]   # each suite timing unit judged
    python -m rola_results dashboard --out suite.html [--group G]  # the newest sessions and memory rows as a page

The tables know no tool: `records(location, key, format, semantics)` and `samples(location, key, n, ok, utc, wall_s,
provenance, error, output_path, output, extra)`, the JSON fields read with SQLite's JSON functions. A tool's shape is a
view in `views/`, run after every index:

| view | from | one row per |
|---|---|---|
| `session_members` | `bench/session`, a lone arm's own location (`rola_devtools.graph`) | member of a composed session: group and claim, label, role, node, cell, subject, calls, samples and round medians, paired ratio, device, torch, commit |
| `memory_rows` | `rola/memory`, `bench/memory` (`rola_devtools.graph`) | arm alone on a cell: peak allocated and reserved bytes, what stayed allocated, bytes held outside the caching allocator (a paged state) and the totals with them, label, commit |
| `session_arms` | `compare`, `suite/timing.session` (through `tools/compare.py`, before the composer) | arm of an interleaved session: cell, subject, calls, label, role, arm name, samples and round medians, device, torch, commit, clock held |
| `timing_rows` | `probe_cells`, `suite/timing.session` (before `tools/compare.py`) | timed arm of a session at a cell: label, branch, commit, tree digest, unit, lane, ms, clock |
| `timing_pairs` | `timing_rows` | pair of arms of one session, cell and unit, with the ratio |
| `driver_rows` | `bench_driver` | driver result: subject, cell, median and IQR, or an A/B's paired ratio and verdict |
| `cells` | fleet and local grids | stored grid cell: bench, config, cell, image or local checkouts, row |

The questions the old measurements database answered, as SQL:

```sql
-- last: the newest time of a cell at a commit
SELECT utc, label, ms FROM timing_rows WHERE cell = 'nl64k-alt-k4' AND git_sha LIKE 'b729e70%' ORDER BY utc DESC LIMIT 1;
-- history: a cell on a branch over time
SELECT utc, git_sha, ms FROM timing_rows WHERE cell = 'nl64k-alt-k4' AND branch = 'master' ORDER BY utc;
-- compare: two commits measured in one session
SELECT cell, subject, calls, ratio FROM timing_pairs WHERE git_sha LIKE 'b729e70%' AND base_sha LIKE 'd652e77%';
-- baseline: what a stage measured
SELECT * FROM timing_rows WHERE stage = 'rola-results-landing';
-- regressions: arms of a stage slower than their session's base by more than 10%
SELECT utc, cell, subject, label, base_label, ratio FROM timing_pairs WHERE stage = ? AND ratio > 1.10;
```

**The verdict** is a query, never a stored row. `verdict` reads `session_members` and, for sessions from before the
composer, `session_arms`: for the newest suite session of each unit
(cell, subject, call count, arm names) and candidate commit, the baseline is the reference arm's samples over the newest
ten sessions of that unit on the same device and torch, the runs are the candidate's sessions at its commit, and the
paired differences are the last session's round medians, candidate minus reference. rola-devtools'
`rola_devtools.verdict.classify` judges them: a regression needs the effect over the baseline's derived threshold, a
significant paired test and a second run over the line; anything less says what it is.

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
