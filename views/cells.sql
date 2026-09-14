-- Every stored grid cell, fleet or local (records whose semantics name a config and a cell): its code (the box image,
-- or the local checkouts), whether the sample succeeded, and its row.
CREATE VIEW cells AS
SELECT s.location, s.key, s.n, s.utc, s.ok,
       json_extract(r.semantics, '$.bench') AS bench,
       json_extract(r.semantics, '$.config') AS config,
       json_extract(r.semantics, '$.cell') AS cell,
       json_extract(r.semantics, '$.image') AS image,
       json_extract(r.semantics, '$.local') AS local,
       s.output, s.error
FROM samples s JOIN records r USING (location, key)
WHERE json_extract(r.semantics, '$.config') IS NOT NULL AND json_extract(r.semantics, '$.cell') IS NOT NULL;
