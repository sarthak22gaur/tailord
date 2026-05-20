import Database from 'better-sqlite3';
import { existsSync, mkdirSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { loadConfig } from './config.js';

const DB_PATH = loadConfig().dbPath;
const DB_DIR = dirname(DB_PATH);
const RESET_SENTINEL = resolve(DB_DIR, '.two-phase-reset.done');

mkdirSync(DB_DIR, { recursive: true });

if (!existsSync(RESET_SENTINEL)) {
  for (const suffix of ['', '-journal', '-wal', '-shm']) {
    const path = DB_PATH + suffix;
    if (existsSync(path)) unlinkSync(path);
  }
}

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS jobs (
    id                      TEXT PRIMARY KEY,
    url                     TEXT,
    company                 TEXT,
    title                   TEXT,
    jd                      TEXT NOT NULL,
    status                  TEXT NOT NULL
                              CHECK (status IN ('pending','running','evaluated','done','failed','skipped')),
    phase                   TEXT
                              CHECK (phase IN ('evaluate','generate') OR phase IS NULL),

    compatibility_score     INTEGER,
    consideration_score     INTEGER,
    grade                   TEXT,
    recommendation          TEXT,
    rationale               TEXT,
    blockers                TEXT,
    work_authorization      TEXT,

    pdf_path                TEXT,
    cover_letter_pdf_path   TEXT,
    variant_dir             TEXT,
    variant_used            TEXT,

    generate_requested_at   INTEGER,
    cover_letter_requested  INTEGER NOT NULL DEFAULT 0,
    applied_at              INTEGER,
    skipped_at              INTEGER,
    error                   TEXT,
    worker_id               TEXT,

    created_at              INTEGER NOT NULL,
    started_at              INTEGER,
    evaluated_at            INTEGER,
    completed_at            INTEGER
  );

  CREATE TABLE IF NOT EXISTS job_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    phase                 TEXT NOT NULL CHECK (phase IN ('evaluate','generate')),
    attempt               INTEGER NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('done','failed')),
    model                 TEXT,
    input_tokens          INTEGER,
    output_tokens         INTEGER,
    cache_creation_tokens INTEGER,
    cache_read_tokens     INTEGER,
    cost_usd              REAL,
    wall_time_ms          INTEGER,
    started_at            INTEGER NOT NULL,
    completed_at          INTEGER NOT NULL,
    error                 TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
  CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
  CREATE INDEX IF NOT EXISTS idx_jobs_generate_requested
    ON jobs(status, generate_requested_at);
  CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job_id);
`);

if (!existsSync(RESET_SENTINEL)) {
  writeFileSync(RESET_SENTINEL, '', 'utf8');
}

export const stmts = {
  insert: db.prepare(`
    INSERT INTO jobs (
      id, url, company, title, jd, status, phase, generate_requested_at,
      cover_letter_requested, created_at
    )
    VALUES (
      @id, @url, @company, @title, @jd, 'pending', 'evaluate',
      @generate_requested_at, @cover_letter_requested, @created_at
    )
  `),
  claimPending: db.prepare(`
    UPDATE jobs SET
      status = 'running',
      phase = @phase,
      started_at = @started_at,
      completed_at = NULL,
      error = NULL,
      worker_id = @worker_id
    WHERE id = @id AND (
      (status = 'pending' AND @phase = 'evaluate') OR
      (status = 'evaluated' AND @phase = 'generate') OR
      (status = 'failed' AND phase = 'generate' AND @phase = 'generate')
    )
  `),
  markEvaluated: db.prepare(`
    UPDATE jobs SET
      status = 'evaluated',
      phase = 'evaluate',
      compatibility_score = @compatibility_score,
      consideration_score = @consideration_score,
      grade = @grade,
      recommendation = @recommendation,
      rationale = @rationale,
      blockers = @blockers,
      work_authorization = @work_authorization,
      evaluated_at = @evaluated_at,
      completed_at = NULL,
      worker_id = NULL
    WHERE id = @id AND status = 'running' AND worker_id = @worker_id
  `),
  markGenerated: db.prepare(`
    UPDATE jobs SET
      status = 'done',
      phase = 'generate',
      pdf_path = @pdf_path,
      cover_letter_pdf_path = @cover_letter_pdf_path,
      variant_dir = @variant_dir,
      variant_used = @variant_used,
      completed_at = @completed_at,
      worker_id = NULL
    WHERE id = @id AND status = 'running' AND worker_id = @worker_id
  `),
  markFailed: db.prepare(`
    UPDATE jobs SET
      status = 'failed',
      error = @error,
      completed_at = @completed_at,
      worker_id = NULL
    WHERE id = @id AND status = 'running' AND worker_id = @worker_id
  `),
  markSkipped: db.prepare(`
    UPDATE jobs SET
      status = 'skipped',
      skipped_at = @skipped_at,
      worker_id = NULL
    WHERE id = @id AND status IN ('evaluated','failed')
  `),
  requestGenerate: db.prepare(`
    UPDATE jobs SET
      generate_requested_at = COALESCE(generate_requested_at, @now),
      cover_letter_requested = @cover_letter_requested,
      status = CASE WHEN status = 'failed' AND phase = 'generate' THEN 'evaluated' ELSE status END,
      error = CASE WHEN status = 'failed' AND phase = 'generate' THEN NULL ELSE error END,
      completed_at = CASE WHEN status = 'failed' AND phase = 'generate' THEN NULL ELSE completed_at END
    WHERE id = @id AND (
      status = 'evaluated' OR
      (status = 'failed' AND phase = 'generate')
    )
  `),
  recordRun: db.prepare(`
    INSERT INTO job_runs (
      job_id, phase, attempt, status, model, input_tokens, output_tokens,
      cache_creation_tokens, cache_read_tokens, cost_usd, wall_time_ms,
      started_at, completed_at, error
    )
    VALUES (
      @job_id, @phase,
      COALESCE(
        (SELECT MAX(attempt) FROM job_runs WHERE job_id = @job_id AND phase = @phase),
        0
      ) + 1,
      @status, @model, @input_tokens, @output_tokens, @cache_creation_tokens,
      @cache_read_tokens, @cost_usd, @wall_time_ms, @started_at, @completed_at,
      @error
    )
  `),
  markApplied: db.prepare(`
    UPDATE jobs SET applied_at = COALESCE(applied_at, @now) WHERE id = @id
  `),
  clearApplied: db.prepare(`
    UPDATE jobs SET applied_at = NULL WHERE id = @id
  `),
  list: db.prepare(`SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100`),
  get: db.prepare(`SELECT * FROM jobs WHERE id = ?`),
  runsForJob: db.prepare(`SELECT * FROM job_runs WHERE job_id = ? ORDER BY id`),
  pendingEvaluate: db.prepare(`
    SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC
  `),
  pendingGenerate: db.prepare(`
    SELECT * FROM jobs
    WHERE status = 'evaluated' AND generate_requested_at IS NOT NULL
    ORDER BY generate_requested_at ASC
  `),
  running: db.prepare(`SELECT * FROM jobs WHERE status = 'running'`),
  failOrphan: db.prepare(`
    UPDATE jobs SET
      status = 'failed',
      error = @error,
      completed_at = @completed_at,
      worker_id = NULL
    WHERE id = @id AND status = 'running'
  `),
};

export function deserialize(row) {
  if (!row) return row;
  let blockers = [];
  if (row.blockers) {
    try {
      const parsed = JSON.parse(row.blockers);
      blockers = Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      blockers = [];
    }
  }
  return { ...row, blockers };
}

export default db;
