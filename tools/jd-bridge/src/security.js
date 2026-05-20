import { createHash, timingSafeEqual } from 'node:crypto';

const EXTENSION_PROTOCOLS = new Set(['chrome-extension:', 'moz-extension:']);

export function requireBridgeTokenConfigured() {
  if (process.env.BRIDGE_TOKEN) return;
  if (process.env.BRIDGE_ALLOW_NO_TOKEN === '1') return;
  throw new Error('BRIDGE_TOKEN env var is required. Set BRIDGE_ALLOW_NO_TOKEN=1 only for local unauthenticated development.');
}

export function tokenMatches(provided, expected) {
  if (typeof provided !== 'string' || typeof expected !== 'string') return false;
  const providedHash = createHash('sha256').update(provided).digest();
  const expectedHash = createHash('sha256').update(expected).digest();
  return timingSafeEqual(providedHash, expectedHash);
}

export function allowedCorsOrigin(origin) {
  if (!origin) return false;

  const explicit = (process.env.BRIDGE_ALLOWED_ORIGINS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (explicit.includes(origin)) return origin;

  try {
    const url = new URL(origin);
    if (EXTENSION_PROTOCOLS.has(url.protocol)) return origin;
  } catch (_) {
    return false;
  }

  return false;
}

export function corsOrigin(origin, cb) {
  cb(null, allowedCorsOrigin(origin));
}
