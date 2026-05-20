import assert from 'node:assert/strict';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import test from 'node:test';

test('db reset creates the two-phase schema and run records', async () => {
  const vault = await mkdtemp(resolve(tmpdir(), 'tailord-bridge-'));
  const stateDir = resolve(vault, '.tailord');
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(resolve(stateDir, 'jobs.db'), 'old schema');
  writeFileSync(resolve(stateDir, 'jobs.db-wal'), 'old wal');

  process.env.RESUME_VAULT = vault;
  process.env.RESUME_FRAMEWORK = resolve('../../');

  const { default: db, stmts } = await import(`../src/db.js?schema=${Date.now()}`);
  const columns = new Set(db.prepare("SELECT name FROM pragma_table_info('jobs')").all().map((r) => r.name));
  const runColumns = new Set(db.prepare("SELECT name FROM pragma_table_info('job_runs')").all().map((r) => r.name));

  assert.equal(existsSync(resolve(stateDir, '.two-phase-reset.done')), true);
  assert.equal(columns.has('compatibility_score'), true);
  assert.equal(columns.has('generate_requested_at'), true);
  assert.equal(runColumns.has('attempt'), true);

  const now = Date.now();
  stmts.insert.run({
    id: 'job-1',
    url: null,
    company: 'Acme',
    title: 'Platform Engineer',
    jd: 'A long enough job description for the bridge test.',
    generate_requested_at: now,
    cover_letter_requested: 1,
    created_at: now,
  });
  stmts.recordRun.run({
    job_id: 'job-1',
    phase: 'evaluate',
    status: 'done',
    model: 'claude-test',
    input_tokens: 10,
    output_tokens: 5,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    cost_usd: 0.01,
    wall_time_ms: 100,
    started_at: now,
    completed_at: now + 100,
    error: null,
  });
  stmts.recordRun.run({
    job_id: 'job-1',
    phase: 'evaluate',
    status: 'failed',
    model: null,
    input_tokens: null,
    output_tokens: null,
    cache_creation_tokens: null,
    cache_read_tokens: null,
    cost_usd: null,
    wall_time_ms: 50,
    started_at: now + 200,
    completed_at: now + 250,
    error: 'retry check',
  });

  const attempts = stmts.runsForJob.all('job-1').map((r) => r.attempt);
  assert.deepEqual(attempts, [1, 2]);

  stmts.insert.run({
    id: 'failed-eval',
    url: null,
    company: 'Acme',
    title: 'Eval Fail',
    jd: 'A long enough job description for the eval failure route.',
    generate_requested_at: null,
    cover_letter_requested: 0,
    created_at: now,
  });
  assert.equal(stmts.claimPending.run({
    id: 'failed-eval',
    phase: 'evaluate',
    started_at: now,
    worker_id: 'test',
  }).changes, 1);
  assert.equal(stmts.markFailed.run({
    id: 'failed-eval',
    worker_id: 'test',
    error: 'eval failed',
    completed_at: now + 1,
  }).changes, 1);
  assert.equal(stmts.requestGenerate.run({
    id: 'failed-eval',
    now,
    cover_letter_requested: 0,
  }).changes, 0);

  stmts.insert.run({
    id: 'failed-generate',
    url: null,
    company: 'Acme',
    title: 'Generate Fail',
    jd: 'A long enough job description for the generate failure route.',
    generate_requested_at: null,
    cover_letter_requested: 0,
    created_at: now,
  });
  assert.equal(stmts.claimPending.run({
    id: 'failed-generate',
    phase: 'evaluate',
    started_at: now,
    worker_id: 'test',
  }).changes, 1);
  assert.equal(stmts.markEvaluated.run({
    id: 'failed-generate',
    worker_id: 'test',
    compatibility_score: 80,
    consideration_score: 75,
    grade: 'B',
    recommendation: 'apply',
    rationale: 'Good fit.',
    blockers: '[]',
    work_authorization: 'yes',
    evaluated_at: now + 1,
  }).changes, 1);
  assert.equal(stmts.requestGenerate.run({
    id: 'failed-generate',
    now,
    cover_letter_requested: 0,
  }).changes, 1);
  assert.equal(stmts.claimPending.run({
    id: 'failed-generate',
    phase: 'generate',
    started_at: now + 2,
    worker_id: 'test',
  }).changes, 1);
  assert.equal(stmts.markFailed.run({
    id: 'failed-generate',
    worker_id: 'test',
    error: 'generate failed',
    completed_at: now + 3,
  }).changes, 1);
  assert.equal(stmts.requestGenerate.run({
    id: 'failed-generate',
    now,
    cover_letter_requested: 1,
  }).changes, 1);
});

test('worker parses phase-specific RESULT objects', async () => {
  const worker = await import('../src/worker.js');
  const evalResult = worker.parseResultLine(`
Markdown output
RESULT: {
  "compatibility_score": 78,
  "consideration_score": 72,
  "grade": "B",
  "recommendation": "apply",
  "rationale": "Strong platform match.",
  "blockers": [],
  "work_authorization": "yes"
}`);
  assert.deepEqual(worker.normalizeEvalResult(evalResult), {
    compatibility_score: 78,
    consideration_score: 72,
    grade: 'B',
    recommendation: 'apply',
    rationale: 'Strong platform match.',
    blockers: [],
    work_authorization: 'yes',
  });

  const genResult = worker.parseResultLine(`
Done.
RESULT: {"pdf_path":"/tmp/resume.pdf","cover_letter_pdf_path":null,"variant_dir":"/tmp/jobs/acme-platform","variant_used":"acme-platform"}`);
  assert.deepEqual(worker.normalizeGenerateResult(genResult), {
    pdf_path: '/tmp/resume.pdf',
    cover_letter_pdf_path: null,
    variant_dir: '/tmp/jobs/acme-platform',
    variant_used: 'acme-platform',
  });
});
