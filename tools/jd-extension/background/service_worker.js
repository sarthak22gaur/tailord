// Service worker: polls the local bridge every ~30s, fires notifications
// when jobs reach `done` or `failed`, and brokers messages from the popup.
if (!globalThis.jdBrowser && typeof importScripts === 'function') {
  const loaderApi = globalThis.chrome || globalThis.browser;
  importScripts(loaderApi.runtime.getURL('shared/browser-api.js'));
}

const { api: ext, call, fetchWithTimeout, getURL, normalizeBridgeUrl, storageGet, storageSet } = globalThis.jdBrowser;

const POLL_ALARM = 'jd-poll';
const POLL_PERIOD_MIN = 0.5; // 30s — Chrome's effective production minimum

const KEY_CONFIG = 'config';      // { bridgeUrl, bridgeToken }
const KEY_SEEN = 'seenStatuses';  // { [jobId]: status }
const KEY_PDFS = 'pdfByNotif';    // { [notificationId]: jobId }

const DEFAULT_CONFIG = { bridgeUrl: 'http://127.0.0.1:8787', bridgeToken: '' };
const injectionPromises = new Map();
let pollPromise = null;

async function getConfig() {
  const { [KEY_CONFIG]: cfg } = await storageGet(KEY_CONFIG);
  const merged = { ...DEFAULT_CONFIG, ...(cfg || {}) };
  try {
    merged.bridgeUrl = normalizeBridgeUrl(merged.bridgeUrl);
  } catch (_) {
    merged.bridgeUrl = DEFAULT_CONFIG.bridgeUrl;
  }
  return merged;
}

async function bridgeFetch(path, opts = {}) {
  const cfg = await getConfig();
  const { timeoutMs = 10_000, headers = {}, ...fetchOpts } = opts;
  const url = normalizeBridgeUrl(cfg.bridgeUrl) + path;
  return fetchWithTimeout(url, {
    ...fetchOpts,
    headers: {
      'Content-Type': 'application/json',
      'X-Bridge-Token': cfg.bridgeToken,
      ...headers,
    },
  }, timeoutMs);
}

async function readJson(res, label) {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch (_) {
    throw new Error(`${label} returned non-JSON: ${text.slice(0, 120)}`);
  }
}

async function pollJobsOnce() {
  let res;
  try {
    res = await bridgeFetch('/jobs');
  } catch (e) {
    await call('action.setBadgeText', { text: '' });
    return; // bridge down — silently skip; popup will surface it
  }
  if (!res.ok) return;
  let body;
  try {
    body = await readJson(res, 'GET /jobs');
  } catch (_) {
    return;
  }
  const jobs = Array.isArray(body.jobs) ? body.jobs : [];
  const { [KEY_SEEN]: seen = {} } = await storageGet(KEY_SEEN);

  let inFlight = 0;
  const toNotify = [];
  for (const job of jobs) {
    if (job.status === 'pending' || job.status === 'running') inFlight++;
    const prev = seen[job.id];
    const transitioned = prev !== job.status;
    if (transitioned && (job.status === 'done' || job.status === 'failed' || job.status === 'evaluated')) {
      toNotify.push(job);
    }
    seen[job.id] = job.status;
  }

  // Drop entries for jobs no longer in the list (bridge prunes to last 100).
  const live = new Set(jobs.map((j) => j.id));
  for (const id of Object.keys(seen)) if (!live.has(id)) delete seen[id];

  await storageSet({ [KEY_SEEN]: seen });
  for (const job of toNotify) {
    try {
      await notify(job);
    } catch (_) {
      // Badge/list state is more important than one failed desktop notification.
    }
  }
  await call('action.setBadgeText', { text: inFlight ? String(inFlight) : '' });
  await call('action.setBadgeBackgroundColor', { color: '#2563eb' });
}

async function pollJobs() {
  if (!pollPromise) {
    pollPromise = pollJobsOnce().finally(() => {
      pollPromise = null;
    });
  }
  return await pollPromise;
}

async function notify(job) {
  const company = job.company || 'job';
  const score = job.compatibility_score != null && job.consideration_score != null
    ? `${job.compatibility_score}/${job.consideration_score}`
    : null;

  let title;
  let message;
  let priority = 1;
  if (job.status === 'done') {
    title = `Tailored: ${company}${score ? ` (${score})` : ''}`;
    message = job.title || 'Click to open PDF';
  } else if (job.status === 'failed') {
    title = `Failed: ${company}`;
    message = job.error || 'Check bridge logs';
  } else {
    const grade = job.grade ? ` ${job.grade}` : '';
    const rec = job.recommendation ? ` - ${job.recommendation}` : '';
    title = `Evaluated: ${company}${score ? ` (${score}${grade}${rec})` : ''}`;
    message = job.title || 'Open the popup to generate or skip';
    priority = 0;
  }

  const notifId = await call('notifications.create', {
    type: 'basic',
    iconUrl: getURL('icons/icon128.png'),
    title,
    message,
    priority,
  });

  if (job.status === 'done' && job.pdf_path) {
    const { [KEY_PDFS]: pdfs = {} } = await storageGet(KEY_PDFS);
    pdfs[notifId] = job.id;
    await storageSet({ [KEY_PDFS]: pdfs });
  }
}

ext.notifications.onClicked.addListener(async (notifId) => {
  const { [KEY_PDFS]: pdfs = {} } = await storageGet(KEY_PDFS);
  const jobId = pdfs[notifId];
  if (jobId) {
    const cfg = await getConfig();
    const url = `${normalizeBridgeUrl(cfg.bridgeUrl)}/pdf/${encodeURIComponent(jobId)}`;
    await call('tabs.create', { url });
    delete pdfs[notifId];
    await storageSet({ [KEY_PDFS]: pdfs });
  }
  await call('notifications.clear', notifId);
});

// Try to message the content script; if it isn't loaded yet (tab predates
// extension install/reload), inject it programmatically and retry once.
async function ensureInjected(tabId) {
  if (injectionPromises.has(tabId)) return await injectionPromises.get(tabId);
  const injected = call('scripting.executeScript', {
    target: { tabId },
    files: [
      'content/registry.js',
      'content/adapters/linkedin.js',
      'content/extract.js',
    ],
  }).catch((e) => {
    throw new Error(`could not inject LinkedIn extractor: ${e.message}`);
  }).finally(() => {
    injectionPromises.delete(tabId);
  });
  injectionPromises.set(tabId, injected);
  return await injected;
}

async function extractFromTab(tabId) {
  const ask = () => call('tabs.sendMessage', tabId, { type: 'extract-jd' });
  try {
    return await ask();
  } catch (_) {
    await ensureInjected(tabId);
    return await ask();
  }
}

ext.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const handler = HANDLERS[msg?.type];
  if (!handler) return;
  handler(msg).then(sendResponse, (e) => sendResponse({ error: e?.message ?? String(e) }));
  return true; // async response
});

const HANDLERS = {
  'queue-current-tab': async () => {
    const [tab] = await call('tabs.query', { active: true, currentWindow: true });
    if (!tab?.id) throw new Error('no active tab');
    if (!/^https:\/\/www\.linkedin\.com\/jobs\//.test(tab.url || '')) {
      throw new Error('not a LinkedIn job page (v1 only supports linkedin.com/jobs/*)');
    }
    const extraction = await extractFromTab(tab.id);
    if (!extraction || extraction.error) throw new Error(extraction?.error || 'extract failed');
    const { data } = extraction;
    const res = await bridgeFetch('/jobs', {
      method: 'POST',
      body: JSON.stringify({
        jd: data.jd,
        url: data.url,
        company: data.company,
        title: data.title,
      }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`bridge ${res.status}: ${t.slice(0, 200)}`);
    }
    const body = await readJson(res, 'POST /jobs');
    await pollJobs();
    return { ok: true, id: body.id, company: data.company, title: data.title };
  },

  'list-jobs': async () => {
    const res = await bridgeFetch('/jobs');
    if (!res.ok) throw new Error(`bridge ${res.status}`);
    return await readJson(res, 'GET /jobs');
  },

  'health': async () => {
    const res = await bridgeFetch('/health');
    if (!res.ok) throw new Error(`bridge ${res.status}`);
    return await readJson(res, 'GET /health');
  },

  'poll-now': async () => {
    await pollJobs();
    return { ok: true };
  },

  'mark-applied': async ({ id, applied }) => {
    if (typeof id !== 'string' || !id) throw new Error('id required');
    if (typeof applied !== 'boolean') throw new Error('applied (bool) required');
    const res = await bridgeFetch(`/jobs/${encodeURIComponent(id)}/applied`, {
      method: 'POST',
      body: JSON.stringify({ applied }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`bridge ${res.status}: ${t.slice(0, 200)}`);
    }
    return { ok: true };
  },

  'generate-job': async ({ id, include_cover_letter: includeCoverLetter }) => {
    if (typeof id !== 'string' || !id) throw new Error('id required');
    if (typeof includeCoverLetter !== 'boolean') {
      throw new Error('include_cover_letter (bool) required');
    }
    const res = await bridgeFetch(`/jobs/${encodeURIComponent(id)}/generate`, {
      method: 'POST',
      body: JSON.stringify({ include_cover_letter: includeCoverLetter }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`bridge ${res.status}: ${t.slice(0, 200)}`);
    }
    await pollJobs();
    return { ok: true };
  },

  'skip-job': async ({ id }) => {
    if (typeof id !== 'string' || !id) throw new Error('id required');
    const res = await bridgeFetch(`/jobs/${encodeURIComponent(id)}/skip`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`bridge ${res.status}: ${t.slice(0, 200)}`);
    }
    await pollJobs();
    return { ok: true };
  },
};

call('alarms.create', POLL_ALARM, { periodInMinutes: POLL_PERIOD_MIN }).catch(() => {});
ext.alarms.onAlarm.addListener((a) => {
  if (a.name === POLL_ALARM) pollJobs().catch(() => {});
});
ext.runtime.onStartup.addListener(() => pollJobs().catch(() => {}));
ext.runtime.onInstalled.addListener(() => pollJobs().catch(() => {}));
