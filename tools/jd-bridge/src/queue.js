import { randomUUID } from 'node:crypto';
import { runJob, terminateActiveJobs } from './worker.js';
import { deserialize, stmts } from './db.js';
import { bus } from './events.js';

function parseConcurrency() {
  const value = Number.parseInt(process.env.CONCURRENCY || '2', 10);
  return Number.isFinite(value) && value > 0 ? value : 2;
}

const CONCURRENCY = parseConcurrency();
const WORKER_ID = `${process.pid}:${randomUUID()}`;

const pending = [];
const queuedKeys = new Set();
const activeRuns = new Set();
let running = 0;
let shuttingDown = false;

function keyOf(job) {
  return `${job.id}:${job.phase}`;
}

function enqueuePhase(job, phase) {
  enqueue({ ...job, phase });
}

export function enqueue(job) {
  if (!job?.id) return;
  const phase = job.phase || 'evaluate';
  const item = { ...job, phase };
  const key = keyOf(item);
  if (shuttingDown || queuedKeys.has(key)) return;
  pending.push(item);
  queuedKeys.add(key);
  bus.emit('event', { type: 'queued', id: item.id, phase: item.phase });
  pump();
}

function pump() {
  if (shuttingDown) return;
  while (running < CONCURRENCY && pending.length > 0) {
    const job = pending.shift();
    running++;
    const run = Promise.resolve()
      .then(() => runOne(job))
      .catch((err) => {
        bus.emit('event', {
          type: 'failed',
          id: job.id,
          phase: job.phase,
          error: err?.message ?? String(err),
        });
      });
    activeRuns.add(run);
    run.finally(() => {
      queuedKeys.delete(keyOf(job));
      activeRuns.delete(run);
      running--;
      pump();
    });
  }
}

function runUsage(result) {
  return {
    model: result?.model ?? null,
    input_tokens: result?.usage?.input_tokens ?? null,
    output_tokens: result?.usage?.output_tokens ?? null,
    cache_creation_tokens: result?.usage?.cache_creation_tokens ?? null,
    cache_read_tokens: result?.usage?.cache_read_tokens ?? null,
    cost_usd: result?.cost_usd ?? null,
  };
}

function recordRun({ job, phase, status, startedAt, completedAt, result = null, error = null }) {
  stmts.recordRun.run({
    job_id: job.id,
    phase,
    status,
    ...runUsage(result),
    wall_time_ms: completedAt - startedAt,
    started_at: startedAt,
    completed_at: completedAt,
    error,
  });
}

async function runOne(job) {
  const phase = job.phase || 'evaluate';
  const startedAt = Date.now();
  const claim = stmts.claimPending.run({
    id: job.id,
    phase,
    started_at: startedAt,
    worker_id: WORKER_ID,
  });
  if (claim.changes !== 1) return;

  const claimed = deserialize(stmts.get.get(job.id));
  bus.emit('event', {
    type: phase === 'generate' ? 'generating' : 'running',
    id: job.id,
    phase,
  });

  try {
    const result = await runJob({ ...claimed, phase });
    const completedAt = Date.now();
    let changed = 0;

    if (phase === 'evaluate') {
      const evaluated = stmts.markEvaluated.run({
        id: job.id,
        worker_id: WORKER_ID,
        compatibility_score: result.compatibility_score,
        consideration_score: result.consideration_score,
        grade: result.grade,
        recommendation: result.recommendation,
        rationale: result.rationale,
        blockers: JSON.stringify(result.blockers),
        work_authorization: result.work_authorization,
        evaluated_at: completedAt,
      });
      changed = evaluated.changes;
      if (changed === 1) {
        recordRun({ job: claimed, phase, status: 'done', startedAt, completedAt, result });
        const updated = deserialize(stmts.get.get(job.id));
        bus.emit('event', {
          type: 'evaluated',
          id: job.id,
          phase,
          company: updated.company,
          title: updated.title,
          result,
        });
        if (updated.generate_requested_at != null) {
          enqueuePhase(updated, 'generate');
        }
      }
    } else {
      const generated = stmts.markGenerated.run({
        id: job.id,
        worker_id: WORKER_ID,
        pdf_path: result.pdf_path,
        cover_letter_pdf_path: result.cover_letter_pdf_path,
        variant_dir: result.variant_dir,
        variant_used: result.variant_used,
        completed_at: completedAt,
      });
      changed = generated.changes;
      if (changed === 1) {
        recordRun({ job: claimed, phase, status: 'done', startedAt, completedAt, result });
        bus.emit('event', {
          type: 'done',
          id: job.id,
          phase,
          company: claimed.company,
          title: claimed.title,
          result,
        });
      }
    }

    if (changed !== 1) return;
  } catch (err) {
    const msg = err?.message ?? String(err);
    const completedAt = Date.now();
    const failed = stmts.markFailed.run({
      id: job.id,
      worker_id: WORKER_ID,
      error: msg,
      completed_at: completedAt,
    });
    if (failed.changes !== 1) return;
    recordRun({ job, phase, status: 'failed', startedAt, completedAt, error: msg });
    bus.emit('event', { type: 'failed', id: job.id, phase, error: msg });
  }
}

export function bootstrap() {
  const now = Date.now();
  const runningRows = stmts.running.all();
  for (const row of runningRows) {
    const phase = row.phase || 'evaluate';
    const startedAt = row.started_at || now;
    const error = 'bridge restart while running';
    recordRun({
      job: row,
      phase,
      status: 'failed',
      startedAt,
      completedAt: now,
      error,
    });
    stmts.failOrphan.run({ id: row.id, error, completed_at: now });
  }

  const evalRows = stmts.pendingEvaluate.all();
  const generateRows = stmts.pendingGenerate.all();
  for (const row of evalRows) enqueuePhase(row, 'evaluate');
  for (const row of generateRows) enqueuePhase(row, 'generate');
  if (evalRows.length || generateRows.length) pump();
  return {
    resumedPending: evalRows.length + generateRows.length,
    resumedEvaluate: evalRows.length,
    resumedGenerate: generateRows.length,
    failedOrphans: runningRows.length,
  };
}

export function snapshot() {
  return { concurrency: CONCURRENCY, running, pendingDepth: pending.length };
}

export async function shutdownQueue() {
  shuttingDown = true;
  pending.length = 0;
  queuedKeys.clear();
  await terminateActiveJobs();
  await Promise.race([
    Promise.allSettled(Array.from(activeRuns)),
    new Promise((resolveP) => setTimeout(resolveP, 5_000)),
  ]);
}
