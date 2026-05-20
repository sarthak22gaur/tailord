import { nanoid } from 'nanoid';
import { createReadStream } from 'node:fs';
import { stmts, deserialize } from './db.js';
import { enqueue, snapshot } from './queue.js';
import { bus } from './events.js';
import { resolveAllowedPdfPath } from './pdf-paths.js';
import { allowedCorsOrigin, tokenMatches } from './security.js';

// Paths that don't require X-Bridge-Token. /pdf/:id is here because browsers
// can't easily attach custom headers when opening a URL in a new tab; the
// bridge only listens on 127.0.0.1 so being on-host is the access control.
const isOpenPath = (path) =>
  path === '/health' || path.startsWith('/pdf/') || path.startsWith('/cover-letter/');

function nullableString(value, field) {
  if (value == null || value === '') return null;
  if (typeof value !== 'string') throw new Error(`${field} must be a string`);
  return value;
}

function optionalBoolean(value, field, fallback = false) {
  if (value == null) return fallback;
  if (typeof value !== 'boolean') throw new Error(`${field} must be a boolean`);
  return value;
}

export async function registerRoutes(app) {
  // Auth: require X-Bridge-Token header when BRIDGE_TOKEN is set.
  app.addHook('onRequest', async (req, reply) => {
    if (isOpenPath(req.url.split('?')[0])) return;
    const expected = process.env.BRIDGE_TOKEN;
    if (!expected && process.env.BRIDGE_ALLOW_NO_TOKEN === '1') return;
    const provided = req.headers['x-bridge-token'];
    if (!tokenMatches(Array.isArray(provided) ? provided[0] : provided, expected)) {
      return reply.code(401).send({ error: 'unauthorized' });
    }
  });

  app.get('/health', async () => ({ ok: true, ...snapshot() }));

  app.post('/jobs', async (req, reply) => {
    const { jd, url, company, title } = req.body ?? {};
    if (!jd || typeof jd !== 'string' || jd.trim().length < 20) {
      return reply.code(400).send({ error: 'jd (string, >=20 chars) required' });
    }
    let clean;
    let autoGenerate;
    let includeCoverLetter;
    try {
      clean = {
        url: nullableString(url, 'url'),
        company: nullableString(company, 'company'),
        title: nullableString(title, 'title'),
      };
      autoGenerate = optionalBoolean(req.body?.auto_generate, 'auto_generate');
      includeCoverLetter = optionalBoolean(req.body?.include_cover_letter, 'include_cover_letter');
    } catch (e) {
      return reply.code(400).send({ error: e.message });
    }
    const id = nanoid(12);
    const now = Date.now();
    stmts.insert.run({
      id,
      url: clean.url,
      company: clean.company,
      title: clean.title,
      jd,
      generate_requested_at: autoGenerate ? now : null,
      cover_letter_requested: includeCoverLetter ? 1 : 0,
      created_at: now,
    });
    enqueue({ id, phase: 'evaluate' });
    return reply.code(202).send({ id, status: 'pending' });
  });

  app.get('/jobs', async () => ({
    jobs: stmts.list.all().map(deserialize),
  }));

  app.get('/jobs/:id', async (req, reply) => {
    const row = stmts.get.get(req.params.id);
    if (!row) return reply.code(404).send({ error: 'not found' });
    return { ...deserialize(row), runs: stmts.runsForJob.all(req.params.id) };
  });

  app.post('/jobs/:id/generate', async (req, reply) => {
    const row = stmts.get.get(req.params.id);
    if (!row) return reply.code(404).send({ error: 'not found' });
    let includeCoverLetter;
    try {
      includeCoverLetter = optionalBoolean(req.body?.include_cover_letter, 'include_cover_letter');
    } catch (e) {
      return reply.code(400).send({ error: e.message });
    }
    const canGenerate =
      row.status === 'evaluated' ||
      (row.status === 'failed' && row.phase === 'generate');
    if (!canGenerate) {
      return reply.code(409).send({
        error: 'job must be evaluated, or failed during generation, before generating artifacts',
      });
    }
    const updated = stmts.requestGenerate.run({
      id: req.params.id,
      now: Date.now(),
      cover_letter_requested: includeCoverLetter ? 1 : 0,
    });
    if (updated.changes !== 1) return reply.code(409).send({ error: 'job could not be queued for generation' });
    const next = deserialize(stmts.get.get(req.params.id));
    enqueue({ id: req.params.id, phase: 'generate' });
    bus.emit('event', { type: 'generate-requested', id: req.params.id, include_cover_letter: includeCoverLetter });
    return reply.code(202).send(next);
  });

  app.post('/jobs/:id/skip', async (req, reply) => {
    const row = stmts.get.get(req.params.id);
    if (!row) return reply.code(404).send({ error: 'not found' });
    if (row.status !== 'evaluated' && row.status !== 'failed') {
      return reply.code(409).send({ error: 'only evaluated or failed jobs can be skipped' });
    }
    const skipped = stmts.markSkipped.run({ id: req.params.id, skipped_at: Date.now() });
    if (skipped.changes !== 1) return reply.code(409).send({ error: 'job could not be skipped' });
    const updated = deserialize(stmts.get.get(req.params.id));
    bus.emit('event', { type: 'skipped', id: req.params.id });
    return updated;
  });

  // Toggle "did I apply for this?" — purely a user-side flag, doesn't change
  // pipeline state. Token-protected like other mutating routes.
  app.post('/jobs/:id/applied', async (req, reply) => {
    const row = stmts.get.get(req.params.id);
    if (!row) return reply.code(404).send({ error: 'not found' });
    const applied = req.body?.applied;
    if (typeof applied !== 'boolean') {
      return reply.code(400).send({ error: 'applied (boolean) required' });
    }
    if (applied) {
      stmts.markApplied.run({ id: req.params.id, now: Date.now() });
    } else {
      stmts.clearApplied.run({ id: req.params.id });
    }
    const updated = deserialize(stmts.get.get(req.params.id));
    bus.emit('event', { type: 'applied', id: req.params.id, applied_at: updated.applied_at });
    return updated;
  });

  async function streamAllowedPdf(reply, candidate, filename) {
    const resolved = await resolveAllowedPdfPath(candidate);
    if (!resolved.ok) return reply.code(resolved.status).send({ error: resolved.error });
    reply
      .header('Content-Type', 'application/pdf')
      .header('Content-Length', resolved.size)
      .header('Content-Disposition', `inline; filename="${filename}"`);
    return reply.send(createReadStream(resolved.path));
  }

  app.get('/pdf/:id', async (req, reply) => {
    const row = stmts.get.get(req.params.id);
    if (!row) return reply.code(404).send({ error: 'job not found' });
    return streamAllowedPdf(reply, row.pdf_path, `${row.id}.pdf`);
  });

  app.get('/cover-letter/:id', async (req, reply) => {
    const row = stmts.get.get(req.params.id);
    if (!row) return reply.code(404).send({ error: 'job not found' });
    return streamAllowedPdf(reply, row.cover_letter_pdf_path, `${row.id}-cover.pdf`);
  });

  app.get('/events', (req, reply) => {
    reply.hijack();
    const res = reply.raw;
    const headers = {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    };
    const corsOrigin = allowedCorsOrigin(req.headers.origin);
    if (corsOrigin) {
      headers['Access-Control-Allow-Origin'] = corsOrigin;
      headers['Vary'] = 'Origin';
    }
    res.writeHead(200, headers);
    res.write(`event: hello\ndata: ${JSON.stringify(snapshot())}\n\n`);

    const send = (ev) => {
      res.write(`event: ${ev.type}\ndata: ${JSON.stringify(ev)}\n\n`);
    };
    const ping = setInterval(() => res.write(`: ping\n\n`), 25_000);

    bus.on('event', send);
    const cleanup = () => {
      clearInterval(ping);
      bus.off('event', send);
    };
    req.raw.once('close', cleanup);
    res.once('close', cleanup);
    res.once('error', cleanup);
  });
}
