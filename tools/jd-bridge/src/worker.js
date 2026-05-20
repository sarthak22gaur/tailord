import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';
import { loadConfig } from './config.js';
import { computeCostUsd, normalizeUsage } from './pricing.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;
const DEFAULT_OUTPUT_LIMIT_BYTES = 2 * 1024 * 1024;
const activeChildren = new Set();

function isChildRunning(child) {
  return child.exitCode == null && child.signalCode == null;
}

function intEnv(name, fallback) {
  const raw = process.env[name];
  if (!raw) return fallback;
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

let cachedTemplates = null;
async function loadTemplates() {
  if (cachedTemplates) return cachedTemplates;
  const path = resolve(__dirname, '../config/prompt.yaml');
  const raw = await readFile(path, 'utf8');
  const parsed = YAML.parse(raw);
  if (!parsed?.evaluate_template) throw new Error('config/prompt.yaml is missing "evaluate_template"');
  if (!parsed?.generate_template) throw new Error('config/prompt.yaml is missing "generate_template"');
  cachedTemplates = {
    evaluate: parsed.evaluate_template,
    generate: parsed.generate_template,
  };
  return cachedTemplates;
}

function render(tpl, vars) {
  return tpl.replace(/\{\{(\w+)\}\}/g, (_, k) => (vars[k] ?? ''));
}

async function readCandidateName(vaultRoot) {
  try {
    const raw = await readFile(resolve(vaultRoot, 'data/master.yaml'), 'utf8');
    const data = YAML.parse(raw) || {};
    return data?.profile?.name || 'the candidate';
  } catch (_) {
    return 'the candidate';
  }
}

function findResultMarkers(text) {
  const markers = [];
  const re = /(?:^|\r?\n)\s*RESULT:\s*/g;
  while (re.exec(text) !== null) {
    markers.push(re.lastIndex);
  }
  return markers;
}

function extractJsonObjectAt(text, start) {
  let i = start;
  while (i < text.length && /\s/.test(text[i])) i++;
  if (text[i] !== '{') throw new Error('RESULT marker is not followed by a JSON object');

  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let j = i; j < text.length; j++) {
    const ch = text[j];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === '\\') {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }

    if (ch === '"') {
      inString = true;
    } else if (ch === '{') {
      depth++;
    } else if (ch === '}') {
      depth--;
      if (depth === 0) return text.slice(i, j + 1);
    }
  }

  throw new Error('RESULT JSON object is incomplete');
}

export function parseResultLine(text) {
  // The model is instructed to emit a final RESULT object. Prefer the last marker
  // and tolerate pretty-printed JSON if the model wraps the object.
  const markers = findResultMarkers(text);
  const start = markers.at(-1);
  if (start == null) {
    throw new Error(`no RESULT object found. tail: ${text.slice(-500)}`);
  }
  try {
    return JSON.parse(extractJsonObjectAt(text, start));
  } catch (e) {
    throw new Error(`RESULT object is not valid JSON: ${e.message}`);
  }
}

export function extractAssistantText(stdout) {
  // With --output-format=json, stdout is a single JSON object whose `result`
  // field holds the final assistant text. Without that flag, stdout IS the
  // assistant text. Try JSON first; on any mismatch, fall back to raw.
  const trimmed = stdout.trim();
  const candidates = [trimmed, ...trimmed.split(/\r?\n/).reverse().filter((line) => line.trim().startsWith('{'))];
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.trim());
      if (typeof parsed.result === 'string') return parsed.result;
      if (typeof parsed.message?.content === 'string') return parsed.message.content;
      if (Array.isArray(parsed.message?.content)) {
        return parsed.message.content
          .map((part) => (typeof part === 'string' ? part : part?.text))
          .filter(Boolean)
          .join('\n');
      }
    } catch (_) {
      // not JSON — try the next candidate
    }
  }
  return stdout;
}

export function modelForPhase(phase) {
  const phaseKey = phase === 'evaluate' ? 'CLAUDE_MODEL_EVALUATE' : 'CLAUDE_MODEL_GENERATE';
  return process.env[phaseKey] || process.env.CLAUDE_MODEL || null;
}

function extractModelAndCost(parsed, aggregateUsage, fallbackModel) {
  const rawEntries = parsed.modelUsage && typeof parsed.modelUsage === 'object'
    ? Object.entries(parsed.modelUsage).filter(([, u]) => u && typeof u === 'object')
    : [];
  if (rawEntries.length > 0) {
    let total = 0;
    let [dominantModel, dominantU] = rawEntries[0];
    for (const [m, u] of rawEntries) {
      const perModel = normalizeUsage({
        input_tokens: u.inputTokens,
        output_tokens: u.outputTokens,
        cache_creation_input_tokens: u.cacheCreationInputTokens,
        cache_read_input_tokens: u.cacheReadInputTokens,
      });
      if (perModel) total += computeCostUsd(m, perModel);
      const out = Number(u.outputTokens) || 0;
      const dominantOut = Number(dominantU.outputTokens) || 0;
      if (out > dominantOut) {
        dominantModel = m;
        dominantU = u;
      }
    }
    return { model: dominantModel, cost_usd: total };
  }
  if (typeof parsed.model === 'string') {
    return {
      model: parsed.model,
      cost_usd: aggregateUsage ? computeCostUsd(parsed.model, aggregateUsage) : null,
    };
  }
  const fallback = fallbackModel || process.env.CLAUDE_MODEL || 'claude-sonnet-4-6';
  return {
    model: fallback,
    cost_usd: aggregateUsage ? computeCostUsd(fallback, aggregateUsage) : null,
  };
}

export function extractClaudeOutput(stdout, fallbackModel = null) {
  const trimmed = stdout.trim();
  const candidates = [trimmed, ...trimmed.split(/\r?\n/).reverse().filter((line) => line.trim().startsWith('{'))];
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.trim());
      const text = typeof parsed.result === 'string'
        ? parsed.result
        : extractAssistantText(candidate);
      const usage = normalizeUsage(parsed.usage);
      const { model, cost_usd } = extractModelAndCost(parsed, usage, fallbackModel);
      return { text, usage, model, cost_usd };
    } catch (_) {
      // not JSON — try the next candidate
    }
  }
  return { text: stdout, usage: null, model: null, cost_usd: null };
}

const VARIANT_SLUG_RE = /^[a-z][a-z0-9_-]{0,63}$/;

function normalizeScore(value, field) {
  if (!Number.isInteger(value) || value < 0 || value > 100) {
    throw new Error(`${field} must be an integer from 0 to 100`);
  }
  return value;
}

function normalizeText(value, field, max = 1000) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${field} must be a non-empty string`);
  }
  return value.replace(/\s+/g, ' ').trim().slice(0, max);
}

export function normalizeEvalResult(result) {
  const recommendation = typeof result?.recommendation === 'string' ? result.recommendation : null;
  const grade = typeof result?.grade === 'string' ? result.grade : null;
  const workAuthorization = typeof result?.work_authorization === 'string'
    ? result.work_authorization
    : null;
  if (!['A', 'B', 'C', 'D', 'F'].includes(grade)) {
    throw new Error('grade must be one of A, B, C, D, F');
  }
  if (!['apply', 'long-shot', 'skip'].includes(recommendation)) {
    throw new Error('recommendation must be apply, long-shot, or skip');
  }
  if (!['yes', 'no', 'not_mentioned', 'ambiguous', 'na'].includes(workAuthorization)) {
    throw new Error('work_authorization has an invalid value');
  }

  return {
    compatibility_score: normalizeScore(result?.compatibility_score, 'compatibility_score'),
    consideration_score: normalizeScore(result?.consideration_score, 'consideration_score'),
    grade,
    recommendation,
    rationale: normalizeText(result?.rationale, 'rationale'),
    blockers: Array.isArray(result?.blockers) ? result.blockers.filter((b) => typeof b === 'string') : [],
    work_authorization: workAuthorization,
  };
}

export function normalizeGenerateResult(result) {
  const variantUsedRaw = typeof result?.variant_used === 'string' ? result.variant_used.trim() : null;
  const variantUsed = variantUsedRaw && VARIANT_SLUG_RE.test(variantUsedRaw)
    ? variantUsedRaw
    : null;
  const pdfPath = typeof result?.pdf_path === 'string' && result.pdf_path.trim()
    ? result.pdf_path
    : null;
  const variantDir = typeof result?.variant_dir === 'string' && result.variant_dir.trim()
    ? result.variant_dir
    : null;

  if (!pdfPath) throw new Error('pdf_path is required for generate RESULT');
  if (!variantDir) throw new Error('variant_dir is required for generate RESULT');
  if (!variantUsed) throw new Error('variant_used must be a kebab-case slug');

  return {
    pdf_path: pdfPath,
    cover_letter_pdf_path: typeof result?.cover_letter_pdf_path === 'string'
      ? result.cover_letter_pdf_path
      : null,
    variant_dir: variantDir,
    variant_used: variantUsed,
  };
}

function normalizeResultForPhase(phase, result) {
  if (phase === 'evaluate') return normalizeEvalResult(result);
  if (phase === 'generate') return normalizeGenerateResult(result);
  throw new Error(`unknown job phase: ${phase}`);
}

function flagsWithJsonOutput(flags) {
  const out = [];
  let skipNext = false;
  let found = false;
  for (let i = 0; i < flags.length; i++) {
    if (skipNext) {
      skipNext = false;
      continue;
    }
    if (flags[i] === '--output-format') {
      out.push('--output-format=json');
      skipNext = i + 1 < flags.length;
      found = true;
      continue;
    }
    if (flags[i].startsWith('--output-format=')) {
      out.push('--output-format=json');
      found = true;
      continue;
    }
    out.push(flags[i]);
  }
  if (!found) out.push('--output-format=json');
  return out;
}

function flagsWithModel(flags, model) {
  if (!model) return flags;
  // Strip any user-supplied --model and force ours so CLAUDE_MODEL is the
  // single source of truth for both invocation and cost accounting.
  const out = [];
  let skipNext = false;
  for (let i = 0; i < flags.length; i++) {
    if (skipNext) {
      skipNext = false;
      continue;
    }
    if (flags[i] === '--model') {
      skipNext = i + 1 < flags.length;
      continue;
    }
    if (flags[i].startsWith('--model=')) continue;
    out.push(flags[i]);
  }
  out.push(`--model=${model}`);
  return out;
}

export async function runJob(job, { onProgress } = {}) {
  // Vault holds user data; framework holds .claude/skills which is what the
  // spawned `claude -p` auto-discovers when cwd is set to it.
  const { vault: vaultRoot, frameworkRoot } = loadConfig();
  if (!vaultRoot) throw new Error('vault root could not be resolved');

  const templates = await loadTemplates();
  const tpl = templates[job.phase];
  if (!tpl) throw new Error(`no prompt template for phase: ${job.phase}`);

  const candidateName = await readCandidateName(vaultRoot);
  const prompt = render(tpl, {
    url: job.url || '',
    company: job.company || '',
    title: job.title || '',
    jd: job.jd,
    vault_root: vaultRoot,
    vault_jobs: resolve(vaultRoot, 'jobs/generated'),
    candidate_name: candidateName,
    include_cover_letter: job.cover_letter_requested ? 'true' : 'false',
    prior_grade: job.grade || '',
    prior_compatibility: job.compatibility_score ?? '',
    prior_consideration: job.consideration_score ?? '',
    prior_work_authorization: job.work_authorization || '',
    prior_rationale: job.rationale || '',
  });

  const bin = process.env.CLAUDE_BIN || 'claude';
  const cwd = frameworkRoot;

  const rawFlags = (process.env.CLAUDE_FLAGS || '').trim().split(/\s+/).filter(Boolean);
  const phaseModel = modelForPhase(job.phase);
  const extraFlags = flagsWithModel(
    flagsWithJsonOutput(rawFlags),
    phaseModel,
  );
  const args = [...extraFlags, '-p'];
  const timeoutMs = intEnv('CLAUDE_TIMEOUT_MS', DEFAULT_TIMEOUT_MS);
  const outputLimitBytes = intEnv('CLAUDE_OUTPUT_LIMIT_BYTES', DEFAULT_OUTPUT_LIMIT_BYTES);

  return await new Promise((resolveP, rejectP) => {
    let child;
    let stdout = '';
    let stderr = '';
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let settled = false;
    let abortReason = null;
    let killTimer = null;
    let timeoutTimer = null;

    const cleanup = () => {
      clearTimeout(timeoutTimer);
      clearTimeout(killTimer);
      if (child) activeChildren.delete(child);
    };

    const settle = (fn, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn(value);
    };

    const abortChild = (err) => {
      if (abortReason) return;
      abortReason = err;
      if (child && isChildRunning(child)) {
        child.kill('SIGTERM');
        killTimer = setTimeout(() => {
          if (child && isChildRunning(child)) child.kill('SIGKILL');
        }, 5_000);
      }
    };

    try {
      child = spawn(bin, args, {
        cwd,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: process.env,
      });
    } catch (e) {
      return settle(rejectP, e);
    }

    activeChildren.add(child);
    timeoutTimer = setTimeout(() => {
      abortChild(new Error(`claude timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdin.on('error', (e) => abortChild(e));
    child.stdin.end(prompt);

    child.stdout.on('data', (d) => {
      stdoutBytes += d.length;
      if (stdoutBytes > outputLimitBytes) {
        abortChild(new Error(`claude stdout exceeded ${outputLimitBytes} bytes`));
        return;
      }
      stdout += d.toString();
      onProgress?.({ kind: 'stdout', bytes: stdout.length });
    });
    child.stderr.on('data', (d) => {
      stderrBytes += d.length;
      if (stderrBytes > outputLimitBytes) {
        abortChild(new Error(`claude stderr exceeded ${outputLimitBytes} bytes`));
        return;
      }
      stderr += d.toString();
    });

    child.on('error', (e) => settle(rejectP, e));
    child.on('close', (code) => {
      if (abortReason) return settle(rejectP, abortReason);
      if (code !== 0) {
        return settle(rejectP, new Error(
          `claude exited with code ${code}\n--- stderr tail ---\n${stderr.slice(-1000)}`
        ));
      }
      try {
        const claudeOutput = extractClaudeOutput(stdout, phaseModel);
        const result = parseResultLine(claudeOutput.text);
        settle(resolveP, {
          ...normalizeResultForPhase(job.phase, result),
          usage: claudeOutput.usage,
          model: claudeOutput.model,
          cost_usd: claudeOutput.cost_usd,
        });
      } catch (e) {
        settle(rejectP, e);
      }
    });
  });
}

export async function terminateActiveJobs() {
  const children = Array.from(activeChildren);
  for (const child of children) {
    if (isChildRunning(child)) child.kill('SIGTERM');
  }
  await Promise.race([
    Promise.allSettled(children.map((child) => new Promise((resolveP) => child.once('close', resolveP)))),
    new Promise((resolveP) => setTimeout(resolveP, 5_000)),
  ]);
  for (const child of children) {
    if (isChildRunning(child)) child.kill('SIGKILL');
  }
}
