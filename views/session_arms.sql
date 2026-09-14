-- Every arm of every interleaved comparison session, one row per (session, arm): rola's tools/compare.py results stored at
-- `compare`, and the suite's timing sessions that ran through it (`suite/timing.session` outputs carrying `result`).
-- `samples` and `blocks` are JSON arrays: the arm's raw samples in the order taken and its per-round medians. `role` is
-- the suite's (subject, reference, attention) and NULL for a bare comparison; `subject` is NULL for a foreign arm.
-- `git_sha` is the arm's checkout (the suite's provenance, a comparison's semantics). A ratio or a verdict is only
-- meaningful between arms of one session, or across sessions of one unit; `python -m rola_results verdict` reads this.
CREATE VIEW session_arms AS
WITH sessions AS (
  SELECT s.location, s.key, s.n, s.utc, s.provenance, r.semantics,
         CASE WHEN s.location = 'compare' THEN s.output ELSE json_extract(s.output, '$.result') END AS result,
         json_extract(s.output, '$.roles') AS roles
  FROM samples s JOIN records r USING (location, key)
  WHERE s.ok AND (s.location = 'compare'
                  OR (s.location = 'suite/timing.session' AND json_extract(s.output, '$.result') IS NOT NULL)))
SELECT x.location, x.key, x.n, x.utc,
       json_extract(x.result, '$.point.cell') AS cell,
       json_extract(a.value, '$.cell.subject') AS subject,
       COALESCE(json_extract(a.value, '$.cell.calls'), 1) AS calls,
       json_extract(a.value, '$.label') AS label,
       json_extract(x.roles, '$."' || json_extract(a.value, '$.label') || '"') AS role,
       json_extract(a.value, '$.arm') AS arm,
       json_extract(a.value, '$.provider') AS provider,
       json_extract(x.result, '$.instrument') AS instrument,
       json_extract(x.result, '$.rounds') AS rounds,
       json_extract(a.value, '$.median_ms') AS median_ms,
       json_extract(a.value, '$.ms') AS samples,
       json_extract(a.value, '$.blocks_ms') AS blocks,
       json_extract(a.value, '$.cell.device') AS device,
       json_extract(a.value, '$.cell.torch') AS torch,
       json_extract(a.value, '$.cell.manifest_sha256') AS manifest_sha256,
       COALESCE((SELECT json_extract(p.value, '$.git_sha') FROM json_each(x.provenance, '$.arms') p
                  WHERE json_extract(p.value, '$.label') = json_extract(a.value, '$.label')),
                (SELECT json_extract(q.value, '$.git_sha') FROM json_each(x.semantics, '$.arms') q
                  WHERE json_extract(q.value, '$.label') = json_extract(a.value, '$.label'))) AS git_sha,
       json_extract(x.result, '$.clock.held') AS clock_held
FROM sessions x, json_each(x.result, '$.arms') a;
