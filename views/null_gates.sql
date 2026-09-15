-- Every cell of every stored null gate (rola-devtools' `measure_null_gate`, stored at `timing/null`): one registration's
-- entry timed against a copy of itself in a second worker. `trusted` is 1 when the per-rep ratios of the two copies put
-- one inside their interquartile range, 0 when they find a worker's bias, null when a copy could not run (`error`).
CREATE VIEW null_gates AS
SELECT s.location, s.key, s.n, s.utc,
       json_extract(s.provenance, '$.run') AS run,
       c.key AS cell,
       json_extract(c.value, '$.trusted') AS trusted,
       json_extract(c.value, '$.ratio_median') AS ratio_median,
       json_extract(c.value, '$.ratio_q1') AS ratio_q1,
       json_extract(c.value, '$.ratio_q3') AS ratio_q3,
       json_extract(c.value, '$.error') AS error
FROM samples s, json_each(s.output, '$.null') c
WHERE s.ok AND json_type(s.output, '$.null') = 'object' AND json_type(s.output, '$.samples') = 'array';
