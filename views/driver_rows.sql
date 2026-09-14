-- Every result of every stored bench driver run (`bench_driver`): a subject alone at a cell, or an interleaved A/B.
CREATE VIEW driver_rows AS
SELECT s.key, s.n, s.utc,
       json_extract(s.provenance, '$.stage') AS stage,
       json_extract(s.provenance, '$.git_sha') AS git_sha,
       json_extract(s.provenance, '$.diff_sha256') AS diff_sha256,
       json_extract(r.semantics, '$.device') AS device,
       json_extract(r.semantics, '$.tier') AS tier,
       json_extract(x.value, '$.subject') AS subject,
       json_extract(x.value, '$.cell') AS cell,
       COALESCE(json_extract(x.value, '$.calls'), 1) AS calls,
       json_extract(x.value, '$.median_ms') AS median_ms,
       json_extract(x.value, '$.iqr_ms') AS iqr_ms,
       json_extract(x.value, '$.source') AS source,
       json_extract(x.value, '$.a') AS a,
       json_extract(x.value, '$.b') AS b,
       json_extract(x.value, '$.paired_ratio') AS paired_ratio,
       json_extract(x.value, '$.significance.verdict') AS verdict
FROM samples s JOIN records r USING (location, key), json_each(s.output) x
WHERE s.location = 'bench_driver' AND s.ok;
