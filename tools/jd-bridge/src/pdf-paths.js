import { lstat, realpath } from 'node:fs/promises';
import { basename, extname, isAbsolute, relative, resolve } from 'node:path';
import { loadConfig } from './config.js';

const { vault: vaultRoot } = loadConfig();
const outputRoot = resolve(vaultRoot, 'output');
const generatedRoot = resolve(vaultRoot, 'jobs/generated');

function isInside(child, parent) {
  const rel = relative(parent, child);
  return rel === '' || (!!rel && !rel.startsWith('..') && !isAbsolute(rel));
}

async function realpathIfExists(path) {
  try {
    return await realpath(path);
  } catch (_) {
    return null;
  }
}

export async function resolveAllowedPdfPath(candidate) {
  if (typeof candidate !== 'string' || !candidate.trim()) {
    return { ok: false, status: 404, error: 'job has no pdf_path yet' };
  }

  const requested = resolve(vaultRoot, candidate);
  if (extname(requested).toLowerCase() !== '.pdf') {
    return { ok: false, status: 403, error: 'pdf_path is not an allowed PDF' };
  }

  let linkStat;
  try {
    linkStat = await lstat(requested);
  } catch (_) {
    return { ok: false, status: 404, error: 'PDF missing on disk' };
  }

  if (linkStat.isSymbolicLink()) {
    return { ok: false, status: 403, error: 'pdf_path cannot be a symlink' };
  }
  if (!linkStat.isFile()) {
    return { ok: false, status: 404, error: 'pdf_path is not a file' };
  }

  const [realRequested, realOutputRoot, realGeneratedRoot] = await Promise.all([
    realpathIfExists(requested),
    realpathIfExists(outputRoot),
    realpathIfExists(generatedRoot),
  ]);
  if (!realRequested) {
    return { ok: false, status: 404, error: 'PDF missing on disk' };
  }

  const allowedStaticPdf = realOutputRoot && isInside(realRequested, realOutputRoot);
  const allowedGeneratedFile = realGeneratedRoot
    && isInside(realRequested, realGeneratedRoot)
    && ['resume.pdf', 'cover-letter.pdf'].includes(basename(realRequested));

  if (!allowedStaticPdf && !allowedGeneratedFile) {
    return { ok: false, status: 403, error: 'pdf_path is outside allowed resume output directories' };
  }

  return { ok: true, path: realRequested, size: linkStat.size };
}
