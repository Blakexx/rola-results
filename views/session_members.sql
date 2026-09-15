-- Every member of every session `rola_devtools.graph` stored (rola-bench's composed sessions at `bench/session`, a lone
-- timed arm at its unit's location): one row per (session sample, member). `grp` and `holds` are the session's relation
-- (the group and its claim); `role` is the member's instance's role there (subject, reference, attention); `node` is the
-- owner's node name (`time.carry_forward@flagship-dense`); `cell`, `subject`, `calls`, `device`, `torch` and
-- `manifest_sha256` are what the unit built; `samples` and `blocks` are JSON arrays (the raw samples in the order taken and
-- the per-round medians); `ratio_median` is the paired ratio to the reference instance's node of the same name, when the
-- session held one; `git_sha` is the member's checkout (the session's provenance). A ratio is only meaningful within one
-- session, or across sessions of one unit: `python -m rola_results verdict` reads this.
CREATE VIEW session_members AS
SELECT s.location, s.key, s.n, s.utc,
       json_extract(s.output, '$.session') AS session,
       json_extract(s.output, '$.relation.group') AS grp,
       json_extract(s.output, '$.relation.holds') AS holds,
       json_extract(m.value, '$.member') AS member,
       json_extract(m.value, '$.label') AS label,
       json_extract(s.output, '$.relation.roles."' || json_extract(m.value, '$.label') || '"') AS role,
       json_extract(m.value, '$.node') AS node,
       json_extract(m.value, '$.unit') AS unit,
       json_extract(m.value, '$.built.cell') AS cell,
       COALESCE(json_extract(m.value, '$.built.subject'), json_extract(m.value, '$.built.backend')) AS subject,
       COALESCE(json_extract(m.value, '$.built.calls'), 1) AS calls,
       json_extract(s.output, '$.instrument') AS instrument,
       json_extract(s.output, '$.rounds') AS rounds,
       json_extract(m.value, '$.median_ms') AS median_ms,
       json_extract(m.value, '$.iqr_ms') AS iqr_ms,
       json_extract(m.value, '$.ms') AS samples,
       json_extract(m.value, '$.blocks_ms') AS blocks,
       json_extract(m.value, '$.paired[0].reference') AS paired_reference,
       json_extract(m.value, '$.paired[0].ratio_median') AS ratio_median,
       json_extract(m.value, '$.built.device') AS device,
       json_extract(m.value, '$.built.torch') AS torch,
       json_extract(m.value, '$.built.manifest_sha256') AS manifest_sha256,
       (SELECT json_extract(p.value, '$.git_sha') FROM json_each(s.provenance, '$.members') p
         WHERE json_extract(p.value, '$.label') = json_extract(m.value, '$.label') LIMIT 1) AS git_sha
FROM samples s, json_each(s.output, '$.members') m
WHERE s.ok AND json_extract(s.output, '$.session') IS NOT NULL AND json_type(s.output, '$.members') = 'array';
