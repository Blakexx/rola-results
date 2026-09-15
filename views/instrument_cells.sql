-- Every cell of every stored instrument run (a rola checkout's `run_tool` targets, stored at `rola/<instrument>`): one
-- row per (sample, cell) from the sample's summary, whether the instrument ran on the cell (`ok`) or could not (`failed`,
-- with the tool's exit and error). The cells that ran hold their results in the sample's output file.
CREATE VIEW instrument_cells AS
SELECT s.location, s.key, s.n, s.utc,
       json_extract(s.extra, '$.run') AS run,
       substr(s.location, instr(s.location, '/') + 1) AS instrument,
       c.key AS cell,
       json_extract(c.value, '$.status') AS status,
       json_extract(c.value, '$.exit') AS exit,
       json_extract(c.value, '$.error') AS error
FROM samples s, json_each(s.extra, '$.summary.cells') c
WHERE s.ok AND json_type(s.extra, '$.summary.cells') = 'object';
