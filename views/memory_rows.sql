-- Every peak-memory row `rola_devtools.graph` stored (rola's `rola/memory`, rola-bench's `bench/memory`): an arm alone on
-- a cell, its peak allocated and reserved device bytes over its calls as the caching allocator counts them, what stayed
-- allocated, and the bytes it holds outside that allocator (a paged state mapped through the driver, whose value after
-- the calls is its peak). `peak_bytes` and `peak_reserved_total_bytes` add them in: the arm's whole peak.
CREATE VIEW memory_rows AS
SELECT s.location, s.key, s.n, s.utc,
       json_extract(s.provenance, '$.label') AS label,
       json_extract(s.provenance, '$.git_sha') AS git_sha,
       json_extract(r.semantics, '$.params.cell') AS cell,
       COALESCE(json_extract(r.semantics, '$.params.arm'), json_extract(s.output, '$.built.backend')) AS subject,
       json_extract(s.output, '$.peak_allocated_bytes') AS peak_allocated_bytes,
       json_extract(s.output, '$.peak_reserved_bytes') AS peak_reserved_bytes,
       json_extract(s.output, '$.allocated_after_bytes') AS allocated_after_bytes,
       COALESCE(json_extract(s.output, '$.outside_allocator_bytes'), 0) AS outside_allocator_bytes,
       json_extract(s.output, '$.peak_allocated_bytes') + COALESCE(json_extract(s.output, '$.outside_allocator_bytes'), 0)
         AS peak_bytes,
       json_extract(s.output, '$.peak_reserved_bytes') + COALESCE(json_extract(s.output, '$.outside_allocator_bytes'), 0)
         AS peak_reserved_total_bytes,
       json_extract(s.output, '$.built.device') AS device
FROM samples s JOIN records r USING (location, key)
WHERE s.ok AND json_extract(s.output, '$.peak_allocated_bytes') IS NOT NULL;
