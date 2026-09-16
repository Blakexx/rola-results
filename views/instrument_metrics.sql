-- EVERY NUMBER AN INSTRUMENT RECORDED, one row each: the long form of the instrument outputs (`rola/<instrument>`), so
-- a reading across runs -- this build's phase times against a baseline's, a kernel's HMMA count before and after -- is
-- a self-join on (instrument, cell, metric) and never a parser per tool. `cell` is NULL for the whole-binary
-- instruments (`sass`, `registers`), whose outputs are keyed by the binary and not by a cell. `metric` is dotted:
-- `phase.fold`, `counter.dram__bytes_read.sum`, `census.FoldStream.hmma_per_unit`, `timeline.tensor_mean_full`,
-- `roofline.fraction`, `registers.FoldStream::step.peak`, `sass.<cubin>.<function>.hmma`. Booleans are 0/1.
CREATE VIEW instrument_metrics AS
WITH inst AS (
  SELECT s.location, substr(s.location, instr(s.location, '/') + 1) AS instrument, s.key, s.n, s.utc,
         json_extract(s.provenance, '$.run') AS run, s.output
  FROM samples s WHERE s.ok AND s.location LIKE 'rola/%' AND json_valid(s.output)
)
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key AS cell, 'phase.' || p.key AS metric, p.value AS value
  FROM inst, json_each(inst.output) c, json_each(c.value, '$.per_phase') p WHERE instrument = 'phases'
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, m.name, json_extract(c.value, '$.' || m.name)
  FROM inst, json_each(inst.output) c, (SELECT 'total' AS name UNION ALL SELECT 'cta_windows' UNION ALL SELECT 'launches') m
  WHERE instrument = 'phases' AND json_extract(c.value, '$.' || m.name) IS NOT NULL
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, 'counter.' || k.key, k.value
  FROM inst, json_each(inst.output) c, json_each(c.value, '$.launch') k WHERE instrument = 'counters'
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, 'census.' || comp.key || '.' || f.key, f.value
  FROM inst, json_each(inst.output) c, json_each(c.value, '$.census') comp, json_each(comp.value) f
  WHERE instrument = 'census'
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, 'census.' || m.name, json_extract(c.value, '$.' || m.name)
  FROM inst, json_each(inst.output) c,
       (SELECT 'instructions_per_unit' AS name UNION ALL SELECT 'wavefronts.excess_per_unit' UNION ALL SELECT 'budget_red') m
  WHERE instrument = 'census' AND json_extract(c.value, '$.' || m.name) IS NOT NULL
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, 'timeline.' || f.key, f.value
  FROM inst, json_each(inst.output) c, json_each(c.value, '$.summary') f WHERE instrument = 'timeline'
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, 'timeline.duration_us', json_extract(c.value, '$.duration_us')
  FROM inst, json_each(inst.output) c WHERE instrument = 'timeline' AND json_extract(c.value, '$.duration_us') IS NOT NULL
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, c.key, 'roofline.' || f.key, f.value
  FROM inst, json_each(inst.output) c, json_each(c.value, '$.rows[0]') f WHERE instrument = 'roofline' AND f.key != 'cell'
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, NULL, 'registers.' || r.key || '.' || f.key, f.value
  FROM inst, json_each(inst.output) member, json_each(member.value, '$.by_region') r, json_each(r.value) f
  WHERE instrument = 'registers'
UNION ALL
SELECT inst.location, inst.instrument, inst.key, inst.n, inst.utc, inst.run, NULL, 'sass.' || cub.key || '.' || fn.key || '.' || f.key, f.value
  FROM inst, json_each(inst.output) member, json_each(member.value) cub, json_each(cub.value, '$.functions') fn,
       json_each(fn.value) f
  WHERE instrument = 'sass';
