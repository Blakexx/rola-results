-- Every row of every stored memory pass (rola-devtools' `measure_memory`, stored at `timing/memory`): one timing entry
-- alone on a central cell, its peak allocated and reserved device bytes over its calls as the caching allocator counts
-- them, what stayed allocated, and the bytes it holds outside that allocator (a paged state mapped through the driver,
-- whose value after the calls is its peak). `peak_bytes` and `peak_reserved_total_bytes` add them in: the entry's whole
-- peak. `owner`, `label` and `arm` read as in `timing_members`; a row that could not run has `status` failed.
CREATE VIEW memory_rows AS
SELECT location, key, n, utc, run, owner, rtrim(prefix, '/') AS label, substr(owner, length(prefix) + 1) AS arm, cell,
       status, error, calls, peak_allocated_bytes, peak_reserved_bytes, allocated_after_bytes,
       allocated_before_build_bytes, outside_allocator_bytes,
       peak_allocated_bytes + outside_allocator_bytes AS peak_bytes,
       peak_reserved_bytes + outside_allocator_bytes AS peak_reserved_total_bytes, device,
       json_extract(provenance, '$.checkouts."' || owner || '".git_sha') AS git_sha
FROM (SELECT s.location, s.key, s.n, s.utc, s.provenance,
             json_extract(s.provenance, '$.run') AS run,
             json_extract(r.value, '$.owner') AS owner,
             rtrim(json_extract(r.value, '$.owner'), replace(json_extract(r.value, '$.owner'), '/', '')) AS prefix,
             json_extract(r.value, '$.cell') AS cell,
             json_extract(r.value, '$.status') AS status,
             json_extract(r.value, '$.error') AS error,
             json_extract(r.value, '$.calls') AS calls,
             json_extract(r.value, '$.peak_allocated_bytes') AS peak_allocated_bytes,
             json_extract(r.value, '$.peak_reserved_bytes') AS peak_reserved_bytes,
             json_extract(r.value, '$.allocated_after_bytes') AS allocated_after_bytes,
             json_extract(r.value, '$.allocated_before_build_bytes') AS allocated_before_build_bytes,
             COALESCE(json_extract(r.value, '$.outside_allocator_bytes'), 0) AS outside_allocator_bytes,
             json_extract(r.value, '$.built.device') AS device
      FROM samples s, json_each(s.output, '$.rows') r
      WHERE s.ok AND json_type(s.output, '$.rows') = 'array' AND json_extract(r.value, '$.owner') IS NOT NULL);
