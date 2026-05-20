(() => {
  if (globalThis.jdBrowser) return;

  const raw = globalThis.browser || globalThis.chrome;
  if (!raw) throw new Error('WebExtension API is unavailable');

  const DEFAULT_BRIDGE_URL = 'http://127.0.0.1:8787';
  const LOCAL_BRIDGE_HOSTS = new Set(['127.0.0.1', 'localhost']);
  const usePromiseApi = !!globalThis.browser;

  function targetFor(path) {
    return path.split('.').reduce((target, part) => target?.[part], raw);
  }

  function call(path, ...args) {
    const parts = path.split('.');
    const method = parts.pop();
    const target = targetFor(parts.join('.'));
    if (!target?.[method]) return Promise.reject(new Error(`missing extension API: ${path}`));

    if (usePromiseApi) {
      return Promise.resolve(target[method](...args));
    }

    return new Promise((resolve, reject) => {
      try {
        target[method](...args, (...values) => {
          const err = raw.runtime?.lastError;
          if (err) reject(new Error(err.message || String(err)));
          else resolve(values.length > 1 ? values : values[0]);
        });
      } catch (e) {
        reject(e);
      }
    });
  }

  function normalizeBridgeUrl(value) {
    const rawValue = String(value || DEFAULT_BRIDGE_URL).trim() || DEFAULT_BRIDGE_URL;
    let parsed;
    try {
      parsed = new URL(rawValue);
    } catch (_) {
      throw new Error('Bridge URL must be a valid URL');
    }
    if (parsed.protocol !== 'http:') throw new Error('Bridge URL must use http://');
    if (!LOCAL_BRIDGE_HOSTS.has(parsed.hostname)) {
      throw new Error('Bridge URL must point to 127.0.0.1 or localhost');
    }
    parsed.pathname = '';
    parsed.search = '';
    parsed.hash = '';
    return parsed.toString().replace(/\/$/, '');
  }

  async function storageGet(key) {
    return await call('storage.local.get', key);
  }

  async function storageSet(value) {
    return await call('storage.local.set', value);
  }

  async function fetchWithTimeout(url, opts = {}, timeoutMs = 10_000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...opts, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  globalThis.jdBrowser = {
    api: raw,
    call,
    DEFAULT_BRIDGE_URL,
    fetchWithTimeout,
    getURL: (path) => raw.runtime.getURL(path),
    normalizeBridgeUrl,
    storageGet,
    storageSet,
  };
})();
