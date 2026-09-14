-- Each measured arm against every other arm of the same session, cell and unit (subject, call count): the only ratios a latency
-- supports (the arms ran interleaved under one clock lock).
CREATE VIEW timing_pairs AS
SELECT a.utc, a.stage, a.session, a.cell, a.subject, a.calls,
       a.label, a.branch, a.git_sha, a.tree_sha256, a.schedule, a.ms,
       b.label AS base_label, b.branch AS base_branch, b.git_sha AS base_sha, b.schedule AS base_schedule, b.ms AS base_ms,
       a.ms / b.ms AS ratio
FROM timing_rows a
JOIN timing_rows b ON a.location = b.location AND a.key = b.key AND a.n = b.n AND a.cell = b.cell
                  AND a.subject = b.subject AND a.calls = b.calls AND a.label <> b.label
WHERE a.ms IS NOT NULL AND b.ms IS NOT NULL;
