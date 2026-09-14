"""rola_results: the interface every tool stores its measurements through.

A tool opens a STORE at its own LOCATION (`Store("probe_cells")`, `Store("suite/carry.sass")`) and hands it what it
measured. A RECORD is everything kept under one KEY: the SEMANTICS the tool handed over (what ran: its inputs, their
identities, its parameters), and every SAMPLE -- one execution under that key, its raw output or its failure, when, how
long, and its PROVENANCE (which checkout, which commit, which host). The key is sha256 over the semantics, so the same
measurement lands on the same record however many times and wherever it runs, and a changed input lands on a new one.
Every sample is kept, failures included; nothing derived from two records (a ratio, a baseline) is stored.

The default backend is the files of this repository: `records/<location>/<key>.json`, each sample's output beside it as
`<key>.<n>.out<suffix>`.
"""
from .store import ROOT, Store, check, checkout, digest, key, locations, machine_paths, outputs, portable

__all__ = ["ROOT", "Store", "check", "checkout", "digest", "key", "locations", "machine_paths", "outputs", "portable"]
