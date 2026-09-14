-- Every timed arm of every stored session, one row per (session, arm, cell): the probe's sessions (`probe_cells`, an
-- output of rows) and the suite's (`suite/timing.session`, an output whose `arms` are the rows). `subject` and `calls`
-- are the unit timed (a suite session states it; a probe row's lane is its unit); `lane_bench` and `lane_calls` are how
-- that arm's checkout spelled it. A ratio is only meaningful between rows of one session, which `timing_pairs` builds.
CREATE VIEW timing_rows AS
SELECT s.location, s.key, s.n, s.utc,
       json_extract(s.provenance, '$.stage') AS stage,
       json_extract(x.value, '$.session') AS session,
       COALESCE(json_extract(x.value, '$.label'), json_extract(x.value, '$.binary')) AS label,
       json_extract(x.value, '$.role') AS role,
       (SELECT json_extract(a.value, '$.branch') FROM json_each(s.provenance, '$.arms') a
         WHERE json_extract(a.value, '$.label') = COALESCE(json_extract(x.value, '$.label'), json_extract(x.value, '$.binary'))) AS branch,
       json_extract(x.value, '$.git_sha') AS git_sha,
       NULLIF(json_extract(x.value, '$.tree_sha256'), '') AS tree_sha256,
       json_extract(x.value, '$.manifest_sha256') AS manifest_sha256,
       json_extract(x.value, '$.cell') AS cell,
       COALESCE(json_extract(s.output, '$.subject'), json_extract(x.value, '$.bench')) AS subject,
       COALESCE(json_extract(s.output, '$.calls'), json_extract(x.value, '$.calls'), 1) AS calls,
       json_extract(x.value, '$.bench') AS lane_bench,
       COALESCE(json_extract(x.value, '$.calls'), 1) AS lane_calls,
       json_extract(x.value, '$.schedule') AS schedule,
       json_extract(x.value, '$.state_arm') AS state_arm,
       json_extract(x.value, '$.median_of_round_medians_ms') AS ms,
       json_extract(x.value, '$.clock_locked') AS clock_locked,
       json_extract(x.value, '$.error') AS error
FROM samples s,
     json_each(CASE WHEN s.location = 'probe_cells' THEN s.output ELSE json_extract(s.output, '$.arms') END) x
WHERE s.ok AND s.location IN ('probe_cells', 'suite/timing.session');
