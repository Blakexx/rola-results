-- Every timed call of every stored timing session, in the order taken: one row per sample, with its member's label,
-- arm and cell (`timing_members`), the round and rep it was timed in, its position in that rep's random order, and its
-- milliseconds. Samples compare only within one session (`location`, `key`, `n`).
CREATE VIEW timing_samples AS
SELECT m.location, m.key, m.n, m.utc, m.run, m.session, m.member, m.label, m.arm, m.cell, m.git_sha, m.diff_sha256,
       json_extract(x.value, '$.round') AS round,
       json_extract(x.value, '$.rep') AS rep,
       json_extract(x.value, '$.position') AS position,
       json_extract(x.value, '$.ms') AS ms
FROM timing_members m JOIN samples s USING (location, key, n), json_each(s.output, '$.samples') x
WHERE json_extract(x.value, '$.member') = m.member;
